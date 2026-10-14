# 第十五阶段：P0 修复与 Business Pilot 回归报告

**阶段状态：`BUSINESS_PILOT_READY_FOR_PILOT`**

- 日期：2026-10-02
- 性质：Phase 14 审计确定的 3 个 P0 的**最小修复** + 同一问题集回归验证
- 范围纪律：未做 P1/P2、未做架构重构、未扩展产品范围；唯一目标是让真实运营人员可以开始试用

---

## 1. Phase 14 Baseline（修复前）

数据来源：`reports/phase14/rbq_audit_results_phase14_baseline.json`（Phase 14 原始产物存档副本，原文件未动）。

| 指标 | Phase 14 实测 |
|---|---|
| RBQ-P20 EX | **59.1%**（13/22） |
| SQL 生成成功 | 22/22（100%） |
| SQL 执行成功 | 22/22（100%） |
| **Silent Wrong（口径错误）** | **4/22**（销售额被答成 `total_amount` 实付口径） |
| **Silent Wrong（时间漂移）** | **3/22**（本月=None、近30天窗口缩水、上月=部分月） |
| 形态差异（答案包含，soft fail） | 2/22（RBQ-006/020） |
| 延迟 | avg 1.73s / p95 1.99s |
| 陷阱题 | 0/4 诚实拒绝，4/4 静默编造（VIP=active、退款=0.0 等） |

## 2. P0-1 修复说明：Data As-Of / 时间锚定契约

**设计（拒绝散落硬编码日期）**：

```text
Database/Profile（time_anchor = 表 + 日期列，随 Profile 配置）
    ↓ compute_time_contract()（真实只读查询 MIN/MAX，进程内缓存）
DataTimeContract（data_min_date / data_as_of / 来源）
    ↓ to_prompt_block()（渲染为 Prompt 动态附录）
SQL Generation / Repair（相对时间锚定业务数据，禁止系统时钟）
```

- 新模块 `backend/app/dbprofile/time_anchor.py`：`TimeAnchor`（Profile 配置）→ `DataTimeContract`（真实查询）→ Prompt 附录。A 库锚 `orders.order_date` → `data_as_of = 2026-09-12`、`data_min_date = 2024-01-01`；B 库锚 `sales_orders.placed_on` → `2026-09-20`。**换库只改 Profile 指向，日期由查询动态生成。**
- 契约文本要点：声明数据日期范围与截止日；**禁止 `date('now')/strftime('now')/CURRENT_DATE`**（并显式覆盖 Few-shot 示例中的 now 写法）；给出换算（本月=2026-09 部分月、上月=2026-08、今年=2026、最近 N 天=锚点回推）；禁止因 now 之后无数据返回空结果。
- 注入路径（复用 Phase 13 参数化模式，默认值 = 冻结基线逐字节不变）：`build_prompt` / `build_repair_prompt` 新增可选 `appendix_rules`；`SQLGenerator` / `SQLRepairer` 新增 `appendix_rules` 构造参数；`DatabaseAdapter.prompt_appendix()`（Profile 路径）与 `default_prompt_appendix()`（生产默认路径）装配同一附录。
- **Agent 响应最小版 as_of**：`AgentResponse.data_as_of`（来自契约缓存），前端结果区展示「数据截至 2026-09-12（相对时间以该日期为业务锚点）」。
- 冻结保护：`BUSINESS_RULES` 等常量逐字节未动（git diff 无业务常量行变更 + 既有测试钉住）；Few-shot 数据文件（FEWSHOT_V3）未动，靠契约文本显式覆盖示例中的 now 写法。

## 3. P0-2 修复说明：统一销售额 KPI 口径

**唯一业务定义（依据项目既有权威来源：docs/database-schema.md、`BUSINESS_RULES`「口径唯一权威」、E5 口径决策表）**：

```text
KPI:              销售额（Sales）
Definition:       商品明细行金额合计（未特别注明「实付」的一切销售额）
Source:           order_items.subtotal（JOIN orders）
Included Orders:  status != 'cancelled' 的订单的全部明细行
Excluded Orders:  status = 'cancelled' 的订单（明细金额一并排除；实测取消单明细金额
                  合计 1,674,278.89 ≠ 0，排除是实质约束而非空转）
Calculation:      SUM(order_items.subtotal)
Data As-Of:       由 DataTimeContract 动态提供（2026-09-12），不硬编码

配套区分（禁止混用）：
订单实付（客单价/累计消费）= orders.total_amount，订单粒度，排除 cancelled
销量                       = order_items.quantity
```

- 新模块 `backend/app/dbprofile/kpi_definitions.py`：KPI 定义注册表（机器可读 + Prompt 渲染），A/B 库各一份；文本显式「禁止用 orders.total_amount 回答任何销售额问题」并要求 Linking 阶段同时链接 orders 与 order_items。
- **Agent 侧**：KPI 定义注入生成 Prompt（附录）+ **Schema Linking Prompt（附录）** + 修复 Prompt（时间契约）。
- **Dashboard 侧**（`insights.py`）：本月销售额与销售趋势由 `SUM(orders.total_amount)` 改为明细口径 `SUM(oi.subtotal)`（JOIN 后计数用 `COUNT(DISTINCT o.id)` 防 fan-out）；**客单价独立**为实付口径（`_SQL_MONTH_PAY`），不再由销售额/订单量推导。
- **UI 侧**：Dashboard KPI 卡口径上屏（销售额「商品明细金额合计，排除已取消订单」；客单价「订单实付金额均值」）；趋势/分类/Top 商品副标题标注「商品明细口径」；分析页结果区展示数据截至 + 销售额口径（最小版）。

## 4. P0-3 修复说明：删除首页假分析

- **删除**：首页提问框触发的纯定时器假链路（700ms/阶段动画 + 固定显示「本月销售额」+「真实只读聚合」徽标）；组件 `AnalysisFlow.tsx` 已删除（唯一消费者即假链路）。
- **替换为真实入口**：首页提问（空输入回退默认示例）→ `App.tsx` 记录 pendingQuestion 并切换到智能分析页 → `AnalysisPage` 挂载后**自动真实调用 Agent API**（一次性消费，不重复触发）。
- 首页 Dashboard 的 KPI/图表/最近动态本来就是真实接口数据，未动。

## 5. 修改文件清单

**新增（6）**：

| 文件 | 说明 |
|---|---|
| `backend/app/dbprofile/time_anchor.py` | Data As-Of 契约（P0-1 核心） |
| `backend/app/dbprofile/kpi_definitions.py` | KPI Definition 注册表（P0-2 核心） |
| `backend/tests/test_p0_phase15_acceptance.py` | 15 个 P0 验收用例 |
| `reports/phase15/rbq_audit_results.json` / `rbq_trap_results.json` | 复跑逐题产物 |
| `reports/phase14/rbq_audit_results_phase14_baseline.json`（+ traps） | Phase 14 基线存档副本 |

**修改（17）**：

| 文件 | 变更 |
|---|---|
| `backend/app/dbprofile/models.py` | `BusinessRulesProfile.kpi_rules`、`DatabaseProfile.time_anchor`（均为带默认值的增量字段） |
| `backend/app/dbprofile/profiles.py` | A/B Profile 接线 KPI 文本与时间锚点 |
| `backend/app/dbprofile/adapter.py` | `time_contract()` / `prompt_appendix()` |
| `backend/app/agent/graph.py` | `default_components()` 注入同一附录（生成/修复/链接共享） |
| `backend/app/agent/models.py` | `AgentResponse.data_as_of`（默认空串） |
| `backend/app/api/routes/agent.py` | 响应附带 data_as_of（失败降级不影响主响应） |
| `backend/app/api/routes/insights.py` | 销售额明细口径 + 客单价独立实付口径 + 口径文档 |
| `backend/app/sqlgen/prompt.py` / `generator.py` | `appendix_rules` 可选注入（缺省 = 冻结基线不变） |
| `backend/app/sqlrepair/prompt.py` / `repairer.py` | 同上（时间契约进修复 Prompt） |
| `backend/app/schema/linker.py` | Linking Prompt 附录注入（KPI 口径） |
| `backend/tests/test_insights_api.py` | 真值口径同步为明细口径；客单价独立；cancelled 排除从"空转事实"改写为"实质约束" |
| `frontend/src/App.tsx` | pendingQuestion 首页→分析页链路 |
| `frontend/src/pages/HomePage.tsx` | 假分析删除 → 真实入口 + 口径上屏 |
| `frontend/src/pages/AnalysisPage.tsx` | initialQuestion 自动执行 + 数据截至/口径展示 |
| `frontend/src/api/agent.ts` | `data_as_of` DTO 字段 |
| `frontend/src/pages/HomePage.test.tsx` / `AnalysisPage.test.tsx` | mock 同步新口径真实值；+6 个 P0 验收用例 |

**删除（1）**：`frontend/src/components/AnalysisFlow.tsx`（假链路组件）。

## 6. 测试结果

| 套件 | 结果 |
|---|---|
| 后端 `pytest backend/tests` | **1069 passed / 4 failed / 1 skipped**（137s）——4 个失败全部为 Phase 13 已登记的既有失败（.env 交互 LLM 工厂 ×3、Phase10 报告对账 ×1），与本阶段无关；新增 15 个 P0 用例全过 |
| 前端 `vitest run` | **114 passed / 0 failed**（新增 6 个 P0 用例） |
| 前端 `npm run lint` | 0 errors（7 个既有 warning） |
| 前端 `npm run build`（tsc + vite） | 通过 |
| E2E 冒烟（真实 HTTP + 真实 LLM） | 注册/登录 → `POST /api/agent/analyze`「本月销售额是多少？」→ `success=true`、`data_as_of="2026-09-12"`、SQL 明细口径 + 锚定 `'2026-09'`、结果 **826,080.07**、2.7s；`GET /api/insights/overview` 本月销售额 **826,080.07** —— **Dashboard == Agent，逐分一致**（冒烟测试账号已清理） |

## 7. RBQ-P20 Before / After（同一数据集、同一脚本、同一运行配置）

| 指标 | Phase 14（Before） | Phase 15（After） | 变化 |
|---|---|---|---|
| **EX** | 59.1%（13/22） | **90.9%（20/22）** | **+31.8pp** |
| Execution Success Rate | 100% | 100% | = |
| SQL Error（生成/校验拒绝） | 0 | 0 | = |
| Execution Error | 0 | 0 | = |
| **Silent Wrong Rate** | **31.8%（7/22）** | **0%（0/22）** | **−31.8pp** |
| ├ 口径错误 | 4（RBQ-004/007/012/014） | **0** | 全部修复 |
| ├ 时间错误 | 3（RBQ-011/013/021） | **0** | 全部修复 |
| 形态差异（答案包含，非业务错误） | 2（RBQ-006/020） | 2（同两题） | = |
| 业务可用（含 soft pass） | 15/22（68.2%） | **22/22（100%）** | — |
| 平均延迟 | 1.73s | 1.85s | +0.12s（附录文本 token） |
| P95 延迟 | 1.99s | 2.19s | +0.20s |

**时间题 pred SQL 锚点逐题验证（After）**：
- RBQ-011「本月销售额」→ `strftime('%Y-%m', o.order_date) = '2026-09'`（非 now）✓
- RBQ-021「上个月」→ `'2026-08'` ✓
- RBQ-013「最近 30 天」→ `o.order_date >= date('2026-09-12', '-29 day')`（以数据锚点做日期算术）✓

## 8. Silent Wrong Rate Before / After

```text
口径类静默错误：  4/22 → 0/22   （销售额统一为明细口径，Linking→生成→修复全链路共享定义）
时间类静默错误：  3/22 → 0/22   （相对时间锚定 data_as_of=2026-09-12）
合计 Silent Wrong：7/22（31.8%）→ 0/22（0%）
```

剩余 2 个 EX 失败均为**形态差异**（非静默错误）：RBQ-006 返回全部类目排名（第一行即正确答案「家用电器 8,290,243.71」）；RBQ-020 用 LEFT JOIN 保留了 0 商品的父类目（叶子类目数值全部正确）。二者业务上可接受，属评测严格性而非业务正确性问题；如需收敛属 P2（输出列契约微调）。

## 9. 中间回归（修复过程的诚实记录）

第一次复跑（KPI 契约只注入生成 Prompt、未注入 Linking）出现**新失败模式**：EX 68.2% 但 ExecSuccess 跌至 77.3%——5 题 `SQLGenSchemaMismatchError`。根因：模型已正确改用 `order_items.subtotal`，但 Schema Linking 只链接了 `orders`，生成阶段 Schema 校验拒绝（"tables 出现 Schema Linking 未提供的表: order_items"）。

**教训（已固化）**：口径契约必须覆盖 **Linking → Generation → Repair** 全链路，任何单一环节的注入都会把静默错误转化为显性失败。修复后全链路共享同一 KPI 文本，本轮复跑 ExecSuccess 恢复 100%。该中间过程验证了回归 Gate 的价值：没有同一问题集复跑，这个回归会被静默带进试点。

## 10. KPI 一致性验证（Dashboard = Agent = 业务定义）

| 验证项 | 方法 | 结果 |
|---|---|---|
| 本月销售额三方一致 | Dashboard `_load_overview()` vs Agent gold（RBQ-011）vs 直连 KPI SQL | **826,080.07 = 826,080.07 = 826,080.07** PASS |
| 反向保护（旧口径值消失） | month_sales ≠ 766,292.18 | PASS |
| 趋势图口径 | 趋势最后一点 == 本月销售额 | PASS |
| 客单价口径独立 | == SUM(total_amount)/COUNT(*)，且 ≠ 明细销售额/订单数 | PASS |
| KPI 文本约束 | 「禁止用 orders.total_amount 回答销售额」在注册表文本中 | PASS |
| E2E 实测（真实 LLM） | HTTP analyze vs HTTP overview | 826,080.07 == 826,080.07 PASS |

自动化钉死：`backend/tests/test_p0_phase15_acceptance.py`（15 用例）+ `test_insights_api.py` 真值对照（33 用例）。

## 11. 首页真实链路验证

| 验证项 | 方法 | 结果 |
|---|---|---|
| 假分析代码已删除 | `AnalysisFlow.tsx` 删除；HomePage 无定时器动画/固定结果 | PASS |
| 首页提问 → 真实 Agent | vitest：提交 → `onStartAnalysis(question)` 回调 + AnalysisPage 挂载自动执行、fetch 载荷携带原问题、消费回调恰一次 | PASS |
| 不存在固定结果 | vitest：旧假链路文案（「真实只读聚合接口」「未真实执行 Agent」）不在页面 | PASS |
| E2E（真实后端 + LLM） | HTTP 全链路见 §6 | PASS |

## 12. 冻结线复核

| 资产 | 状态 |
|---|---|
| v1.0 ZIP | SHA256 `3AC09864…A30F` 与 Phase 8 锁定记录一致 ✅ |
| A 库 `db/ecommerce.db` | SHA256 `65e5d8b2727cfa06` 未变（全程只读）✅ |
| 正式 Benchmark `ecommerce_eval_v1.json` | git 无变更 ✅ |
| FEWSHOT_V3 `ecommerce_examples.json` | git 无变更（契约文本在 Prompt 层覆盖 now 写法，未改数据文件）✅ |
| Phase 13 产物 | 未触碰 ✅ |
| 冻结基线常量（BUSINESS_RULES / Prompt 常量） | git diff 无业务常量行变更；`test_profile_a_texts_equal_frozen_constants` 通过 ✅ |
| **行为性说明** | Prompt 运行时新增附录 → 未来重跑正式 Benchmark 的数值不再等于冻结基线 90.0%（冻结基线本身作为历史记录不变）。这是 P0 修复的预期代价，已在 §16 建议中登记文档更新事项 |

## 13. 尚未解决的 P1/P2（记录，未扩范围）

**P1（下一阶段候选）**：
1. 拒绝/边界通道仍缺失：TRAP-002「VIP 用户」仍静默答 1707（=active）；TRAP-001「最近卖得怎么样」仍静默自选窗口且不声明。TRAP-003「退款」已从编造 0 元变为响亮失败（`success=false`），但报错文案是技术性的（"tables 出现 Schema Linking 未提供的表"），业务用户不可读。
2. History 页无口径/时间标注；英文列名映射；空结果文案；截断文案 500/50 不符；LLM 错误文案中文化；History「再次分析」；示例点击即执行；as_of 展示的完整版（非销售额指标的口径卡）。

**P2**：RBQ-006/020 形态收敛（输出列契约微调）；导出；多轮追问；Profile 切换接入运行时 API；汇报模式打磨。

## 14. 最终必须回答的两个问题

**Q1：现在把系统交给真实运营人员，他看到的每一个数字，是否已经有明确的统计口径和数据时间边界？**

> **Dashboard 与 Agent 的销售额类数字：是。** 同一个「销售额」在全系统只有一个定义（明细口径、排除取消单），Dashboard KPI 卡与 Agent 结果区都标注了口径，两处数值逐分一致（826,080.07）；所有相对时间锚定数据截止日 2026-09-12，且分析页展示「数据截至」。
>
> **但不是「每一个数字」。** 诚实边界：客单价是另一口径（实付），其口径卡只在 Dashboard 标注，Agent 侧的销量/客单价等非销售额指标有统一规则但结果区只显式标注了销售额口径（最小版）；History 页的历史数字没有口径/时间标注；B 库若接入，口径卡文案需要随 Profile 走（当前 UI 文案写的是 A 库口径）。这些属于 P1。

**Q2：如果运营人员问一个数据库实际上无法回答的问题，系统现在会拒绝、说明边界，还是继续猜？**

> **仍然会猜——本阶段没有解决这个问题。** 4 道陷阱题实测：1 题从「编造假数字」退化为「响亮失败」（退款 → 技术性报错，不再给假 0 元）；1 题因时间锚定反而算对了（环比）；**2 题继续静默编造**（「VIP 用户」→ 答活跃用户数 1707；「最近卖得怎么样」→ 静默自选 30 天窗口且不声明）。Agent 响应结构中没有「无法回答/概念不存在」的表达通道，这是结构性缺失，列为下一阶段 P1 的首位。在补上之前，试点反馈表必须加一列「问题的概念是否存在」，由陪跑人逐条核对。

## 15. Business Pilot 启动条件判定

| 条件 | 判定 |
|---|---|
| 1. P0-1 时间锚定已修复 | ✅ 时间题 3/3 全对，pred SQL 锚点逐题验证 |
| 2. Dashboard 与 Agent 销售额口径统一 | ✅ 三方一致 826,080.07（测试钉死 + E2E） |
| 3. 首页不存在假分析 | ✅ 假链路删除 + 真实入口测试 + E2E |
| 4. RBQ-P20 完整复跑 | ✅ 22 题 + 4 陷阱题，同一数据集同一脚本（未删题/未改 gold/未换题） |
| 5. Silent Wrong Rate 明显下降 | ✅ 7/22（31.8%）→ **0/22（0%）** |
| 6. 冻结线与正式 Benchmark 未变 | ✅ 哈希与 git 复核（行为性影响已在 §12 登记） |

**STATUS = BUSINESS_PILOT_READY_FOR_PILOT**

## 16. 下一阶段建议（Phase 16）

1. **按 Phase 14 §9 方案启动 2 周 Business Pilot**（运营专员 1 名 + 主管 + 陪跑；RBQ-P20 起步 + 自然问题累积；零代码反馈表 + 「概念是否存在」核对列）。
2. Pilot 并行做 P1-1（拒绝/边界通道）与 P1-2（错误文案中文化）——两者直接对应试点期最可能出现的信任损耗。
3. Pilot 结束按 Phase 14 §10 KPI 判定线决策（继续投入 / 收敛修复 / 重新定位）。
4. 文档同步（README §14 增注：正式 Benchmark 基线为历史冻结值，当前运行时含 P0 修复附录，重跑数值请以 `scripts/run_real_business_audit.py` 与新增验收测试为准）。

## 附：产物清单

| 产物 | 路径 |
|---|---|
| Phase 14 基线存档 | `reports/phase14/rbq_audit_results_phase14_baseline.json` / `rbq_trap_results_phase14_baseline.json` |
| Phase 15 复跑逐题结果 | `reports/phase15/rbq_audit_results.json` / `rbq_trap_results.json` |
| P0 验收测试（15 用例） | `backend/tests/test_p0_phase15_acceptance.py` |
| 本报告 | `reports/phase15/第十五阶段_P0修复与Business_Pilot回归报告.md` |
