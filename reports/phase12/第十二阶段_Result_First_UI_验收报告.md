# 第十二阶段 Result First 智能分析页重构 — 验收报告

> 阶段目标：把智能分析页从「流程展示优先」升级为「**结果优先 + 流程可解释**」的真实业务产品界面。
>
> 最终状态：**RESULT_FIRST_VERIFIED**（2026-09-29）
> 约束遵守：仅改 v1.1 开发线前端展示层；`POST /api/agent/analyze` 请求体仍为 `{ "question": "..." }`，后端 API / Agent 核心 / SQL 生成 / RAG / 评测数据零触碰；v1.0.0 FINAL_DELIVERY_LOCKED 哈希不变。

---

## 1. 当前问题（改造前审计结论）

只读审计对象：`frontend/src/pages/AnalysisPage.tsx`、`components/AnalysisWorkflow.tsx`、`components/AgentTrace.tsx`、`components/SqlPanel.tsx`、`styles/analysis.css`、既有测试。

| # | 审计项 | 改造前事实 |
|---|--------|-----------|
| 1 | 结果区域在哪 | `section.card.result-card`，位于 `.analysis-grid` 双列网格**右列（0.85fr）** |
| 2 | 执行流程区域在哪 | `AnalysisWorkflow` 垂直 7 阶段列表，占同网格**左列（1.15fr 主导宽度）** |
| 3 | DOM 顺序 | 页头 → 输入卡 → **流程(左)+结果(右)** → 图表 → SQL(`defaultOpen` 全展开)+Trace(全列表) |
| 4 | 占空间的 CSS | `grid-template-columns: 1.15fr 0.85fr`；7 阶段成功后每阶段都渲染 `wf-detail`（含 SQL 预览/摘要 chips）；`.result-card{min-height:320px}` 挤在右列；SqlPanel 默认展开、AgentTrace 全量渲染 |
| 5 | 组件独立性 | `AgentTrace` / `SqlPanel`（自带折叠）/ `ResultTable` / `AnalysisWorkflow` 均已独立 → 可复用，只需重排+折叠 |
| 6 | 状态模型 | `"idle" \| "loading" \| "success" \| "error"` 四态 + `result` + `errorInfo`；Agent 级失败保留 result 作诊断证据 |
| 7 | loading/success/error | loading 有 700ms 视觉滚动（不虚构节点完成）；success 只在右列表格；error 卡有标题/原因/重试 |
| 8 | 测试覆盖 | **无 AnalysisPage 专属测试**（改前 11 个测试文件均不触及该页 DOM） |

结论：视觉顺序是「问题 → 执行流程 → 结果」，与产品要求「问题 → 结果 → 图表 → SQL/Trace/执行流程」相反。

## 2. UI 改造前后

```text
改造前（流程占据主视觉）                 改造后（Result First）
┌──────────┬──────────┐                ┌───────────────────────────┐
│ 输入卡    │ 输入卡    │                │ 输入卡                     │
├──────────┼──────────┤                ├───────────────────────────┤
│ 执行流程  │ 结果(挤)  │                │ 分析结果 + 完成态 + 耗时     │
│ (1.15fr  │ (0.85fr  │                │ 2,000 / user_count         │
│  垂直7段) │  窄列)   │                │ 结果表格 + 执行指标          │
├──────────┴──────────┤                ├───────────────────────────┤
│ SQL(全展开) + Trace  │                │ 图表（属于结果）             │
│ (全量渲染)           │                ├───────────────────────────┤
└─────────────────────┘                │ 执行证据（默认全部折叠）      │
                                       │ ▶查看SQL ▶执行过程 ▶Trace   │
                                       └───────────────────────────┘
```

- 视觉顺序：问题 → **结果** → 图表 → SQL / Trace / 执行流程（§四 要求达成）。
- 成功后首屏（1440×900）直接可见：问题、结果值、结果状态、耗时，无需滚动（§十四 达成）。
- loading 期间结果卡保持在同一位置（显示「分析中」），进度流程卡紧随其后；成功后流程自动折叠，结果不动位置。

## 3. Result First 设计

1. **结果第一视觉中心**：结果卡全宽置顶，紧跟输入卡；卡头显示「分析结果 + 问题回显 + 分析完成徽标 + 真实总耗时（`formatDuration`：<1s 显示 ms，否则 s）」。
2. **KPI / 数字型结果**（§五.2）：`singleValueOf()` 判定 1 行 × 1 列且非空 → 渲染 `.result-hero` 大数字（`Intl.NumberFormat` 千分位，如 `2,000`）+ 列名标签（来自真实 SQL 别名，本次链路为 `user_count`，不硬编码）。实测「平台注册用户有多少？」→ `2,000`。
3. **表格型结果**（§五.3）：多行结果第一视觉为 `ResultTable`（保留前 50 行 + 截断说明），执行流程折叠。
4. **图表属于结果，不属于 Trace**（§五.4）：图表区紧跟结果卡、位于证据区之前（测试以 DOM 顺序断言钉住）；单值结果不再绘制无意义单柱图（改造前会对 `[[2000]]` 画一根柱子），单值时 KPI 即是可视化；「执行诊断」指标图保留（真实指标）。

## 4. Trace 新定位

- Trace / 执行流程 / SQL 统一收进「**执行证据**」区，副标题明示定位：*解释与审计层 · 默认折叠，点击展开*。
- 三组控件（均为真实 button，`aria-expanded` 同步，键盘 Enter/Space 可操作）：
  - `查看 SQL`（SqlPanel，默认收起；展开后含「复制 SQL」与 SQL 全文）
  - `查看执行过程`（CollapsiblePanel 包裹 AnalysisWorkflow：问题理解→Schema 匹配→Few-shot→SQL 生成→SQL 校验→SQL 执行→结果生成，7 阶段详情由真实 Trace 驱动）
  - `查看 Trace`（CollapsiblePanel 包裹 AgentTrace：8 个真实节点、耗时、状态、输入/输出摘要）
- 展开后可见 `SQL 校验：只读校验 true`、`SQL 执行：返回行数 1`、`sql_repair 未执行（无需修复）` 等审计信息；完成态文案改为「结果见上方结果区」（原「右侧」已不成立）。
- Trace 能力、SQL 展示、执行步骤**全部保留**，零删除（§一 禁止项遵守）。

## 5. 组件修改

| 文件 | 修改 |
|------|------|
| `frontend/src/pages/AnalysisPage.tsx` | 核心重构：删除流程+结果双列网格；结果卡全宽置顶；新增单值 KPI hero（`singleValueOf` / `formatKpiValue` / `formatDuration`）；错误分类四态（`ErrorKind`：`analysis_error` / `service_unavailable` / `backend_unavailable` / `invalid_request`）；证据区折叠编排；单值不画图表 |
| `frontend/src/components/CollapsiblePanel.tsx` | **新增**：审计折叠面板（button + `aria-expanded`/`aria-controls`，原生键盘可操作，无新 UI 框架） |
| `frontend/src/components/SqlPanel.tsx` | `defaultOpen` 默认改 `false`；切换按钮文案「查看 SQL / 收起 SQL」；补 `aria-expanded` |
| `frontend/src/components/AnalysisWorkflow.tsx` | 仅 1 行文案修正：「见右侧结果区」→「结果见上方结果区」 |
| `frontend/src/styles/analysis.css` | 新增 `result-card__question/__status/__duration`、`result-hero`、`evidence-stack`、`collapsible-panel` 样式（全部复用既有 tokens）；移除仅本页使用的 `analysis-grid--bottom`（`.analysis-grid` 基类保留——HomePage 仍在使用） |
| `frontend/src/pages/AnalysisPage.test.tsx` | **新增**：7 条用例（见 §6） |

未改动：`AnalysisFlow.tsx`（首页用）、后端全部、`api/agent.ts` 契约、汇报模式数据来源逻辑。

## 6. 测试结果

新增 `AnalysisPage.test.tsx`（vitest + RTL，mock fetch / mock echarts，与 `test/integration.test.tsx` 同口径），对齐任务书 §十二 8 场景：

| 任务书场景 | 用例 | 结果 |
|-----------|------|------|
| 1. success → Result First | 场景1+2：KPI `2,000`/列名/完成态/`7.4 s`；流程、Trace、SQL 均不在 DOM；三个按钮 `aria-expanded=false` | ✅ |
| 2. success → Trace collapsed | 同上（`Agent Trace` 文本不在 DOM） | ✅ |
| 3. expand Trace → 正常 | 场景3+4：展开后 `Agent 执行流程`、7 阶段、`schema_link`/`sql_execute` 节点全部渲染 | ✅ |
| 4. SQL collapsed / expanded | 场景3+4：查看 SQL → SELECT 可见 → 收起 SQL → 消失；`aria-expanded` 同步 | ✅ |
| 5. backend unavailable | 场景5：「后端服务不可用」+ `role=alert`「请检查后端是否启动」+「重新加载」；**无 Demo 横幅、无 2,000 假值** | ✅ |
| 6. analysis error | 场景6：Agent 级失败显示「分析未完成 + final_error + 重新分析」，证据区保留，无假结果 | ✅ |
| 7. loading | 场景7：「分析中」徽标 + 进度流程可见 + 无结果 | ✅ |
| 8. chart result | 场景8：多行结果表格+图表先于证据区（`compareDocumentPosition` DOM 顺序断言），无 KPI | ✅ |
| （加试）可访问性 | 折叠面板键盘 Enter 展开成功 | ✅ |

最终全量回归：**Test Files 12 passed / Tests 108 passed**（改前 11 files / 101 tests → 新增 1 文件 7 测试，存量 101 全部保持绿）；
`npx tsc -b` **exit 0**；`oxlint` **0 errors / 7 warnings**（与第十阶段基线一致，无新增）。
证据：`evidence/vitest_final_run.txt`、`evidence/tsc_final_exit.txt`。

## 7. 真实浏览器结果

真实环境：`python scripts/start_dev.py` 拉起后端（uvicorn :8000，DB `ecommerce.db` ok，LLM mimo/deepseek-chat）+ Vite :5173；真实登录账号 `p12resultfirst`；全部走真实 Agent 链路（POST `/api/agent/analyze`，请求体 `{"question": ...}` 未变）。

| Case | 操作 | 实测 | 结论 |
|------|------|------|------|
| Case 1 单值结果 | 「平台注册用户有多少？」 | 3s 返回；首屏即见 **2,000 / user_count** + 「分析完成 · 3.0 s」；执行过程/SQL/Trace 默认折叠（DOM 快照确认无「Agent 执行流程」标题、无 SELECT 文本） | ✅ |
| Case 2 复杂结果 | 「销售额最高的 5 个商品是什么？」 | 2.7s 返回；首屏第一视觉为 5 行真实结果表（恒源祥笔记本电脑Plus 944,485.34 …），图表区（结果可视化柱图 + 执行诊断）紧随其后、在证据区之前 | ✅ |
| Case 3 展开 Trace | 依次点开三个证据面板 | 7 阶段全部 ✓（匹配表 users / 置信度 0.95 / 3 个 few-shot 案例 / 真实 SQL / 只读校验 true）；Trace 8 节点含耗时与状态（schema_link 2188ms、sql_generate 829ms、sql_repair 未执行）；SQL 展开 `SELECT COUNT(*) AS user_count FROM users`，「收起 SQL」回切正常 | ✅ |
| Case 4 后端不可用 | 受控 `taskkill` uvicorn（页面保持加载态）→ 再发起分析 | 2s 内显示「后端服务不可用 / 无法连接后端服务，请检查后端是否启动，再重新加载。[重新加载]」；**无 Demo、无 Mock、无静态结果**；页头数据库徽标降为「状态未知」（不降级成「已连接」） | ✅ |
| Case 4 恢复 | 重启 uvicorn → 点「重新加载」 | 3s 内真实 Agent 重跑成功，KPI `2,000` 恢复（2.5s / 2467ms） | ✅ |
| （加试）loading | 发起分析后 1s 内截屏 | 「分析中」徽标 ×2 + 进度流程「问题理解 · 正在理解问题…」可见（DOM 断言 badge=2、workflow=1） | ✅ |
| （加试）应用级守卫 | 后端宕机时整页刷新 | 第十阶段 `BackendUnavailable` 全局守卫照常工作（非本阶段范围，截图留证） | ✅ |

附带验证：两次成功分析自动进入「最近动态」历史（`GET /api/history` 真实记录），业务闭环未破坏。

## 8. 故障状态结果

| 状态 | 呈现 | 禁止项核查 |
|------|------|-----------|
| LOADING | 结果卡原位「分析中」+ 进度流程卡（仅当前阶段 active，不虚构节点完成） | 无假结果 ✅ |
| SUCCESS | KPI/表格 + 「分析完成」+ 真实耗时 | — |
| ANALYSIS_ERROR | 「分析未完成/分析失败」+ 错误原因 + `role=alert` + 重新分析；Agent 级失败保留 SQL/Trace 证据可展开 | 不显示假数值 ✅ |
| BACKEND_UNAVAILABLE | 「后端服务不可用」+「请检查后端是否启动」+ [重新加载]（分析页级）；整页刷新则命中应用级守卫 | 无 Demo/Mock/静态结果 ✅；恢复后重新加载正常 ✅ |
| LLM 上游 503/502 | 「分析服务暂时不可用（LLM 服务异常）」+ 重新分析（区别于后端不可用，四态分类） | ✅ |

已知行为（沿袭第十阶段设计，非本阶段引入）：`useHealthStatus` 仅挂载时取一次健康状态、不轮询；故后端宕机期间挂载的分析页在服务恢复并「重新加载」分析成功后，页头数据库徽标仍显示「状态未知」——诚实不降级，需整页刷新才更新。任务书 §十五「不过度设计」范围内未改动该行为。

## 9. v1.0 冻结线验证

| 项 | 结果 |
|----|------|
| ZIP SHA256（开工前基线） | `3AC09864B3A6EB58661AA56E5C308CDB2644655C6B16A838184CDE719E23A30F` |
| ZIP SHA256（收工复测） | `3ac09864b3a6eb58661aa56e5c308cdb2644655c6b16a838184cde719e23a30f` — **MATCH** |
| `_delivery_build/` 写入 | `find _delivery_build -newermt 2026-09-28` 为空 → 本阶段**零写入** ✅ |
| 21 项冻结资产 / 评测数据 / 业务库结构 | 未触碰 ✅ |
| 后端 / Agent / SQL 生成 / RAG | 未触碰（工作树中 backend 等处的改动均为本阶段开工前已存在的 v1.1 未提交内容，见会话起点 git status 快照）✅ |
| API 语义 | `POST /api/agent/analyze` 请求体仍为 `{"question": "..."}`，浏览器实测真实链路 ✅ |
| 验证账号 | 为本阶段验证注册 `p12resultfirst`（id=34，写入 `db/app.db` 应用库用户表，属运行数据，未改业务库结构） |

## 10. 截图 / DOM / 测试证据

全部位于 `reports/phase12/evidence/`：

| 文件 | 内容 |
|------|------|
| `case1_success_kpi_first_viewport.png` | Case 1 首屏：问题 + `2,000/user_count` + 分析完成 3.0s 同屏可见，证据区未展开 |
| `case2_multi_result_first_viewport.png` | Case 2 首屏：5 行真实结果表第一视觉 |
| `case2_charts_area.png` | Case 2 图表区：结果可视化柱图 + 执行诊断，位于证据区之前 |
| `case3_sql_expanded.png` | 查看 SQL 展开（SELECT COUNT(*) AS user_count FROM users，按钮变「收起 SQL」） |
| `case3_trace_expanded.png` | Agent Trace 8 真实节点（耗时/状态/输入输出摘要） |
| `case4_analysis_page_backend_unavailable.png` | 分析页故障态：后端服务不可用 + [重新加载]，无任何假数据 |
| `case4_recovered_after_reload.png` | 点击重新加载后恢复：2,000 / 分析完成 2.5s |
| `case4_app_level_guard_backend_down.png` | （加试）整页刷新命中应用级守卫 |
| `loading_state_with_progress.png` | loading 态：分析中徽标 + 进度流程（DOM 断言 badge=2 / workflow=1） |
| `vitest_final_run.txt` / `tsc_final_exit.txt` | 最终测试与类型检查证据 |

DOM 断言摘录（Case 1 成功态，AI/ARIA 快照）：`分析结果 → 平台注册用户有多少？ → 分析完成 → 3.0 s → 2,000 → user_count → table(2000) → 执行证据(SQL 查询[查看 SQL] / ▶查看执行过程 / ▶查看 Trace)`，且无「Agent 执行流程」「SELECT」字样——流程与 Trace 默认折叠成立。

验证过程备注（如实披露）：
- 本环境 In-app Browser 的 Playwright `click()` 持续超时（`fill`/`press`/查询正常），交互改用坐标点击完成；产品本身无关。
- 该浏览器偶发截取到旧帧（2 次），凡截图与 DOM 断言不一致时以 DOM 快照为准，并已删除与 DOM 证据不符的旧帧截图后重拍。
- 首页输入框与分析页输入框同名（aria-label 相同），验证脚本曾误在首页触发——属测试脚本定位问题，已通过路由标题断言纠正，非产品缺陷。

## 验收标准对照（§十六）

```text
✅ 结果成为首要视觉信息          ✅ KPI / 表格 / 图表优先
✅ Trace 默认折叠               ✅ SQL 默认折叠（紧凑头部 + 查看 SQL）
✅ 可以完整展开 Trace           ✅ Loading / Error / Backend unavailable 清晰
✅ 不存在 Demo fallback         ✅ 真实 Agent 链路不变（请求体不变）
✅ 真实浏览器验证通过（4 Case + 加试）✅ 前端测试全绿（108/108）
✅ TypeScript 全绿（exit 0）     ✅ lint 不新增错误（0e/7w，与基线一致）
✅ v1.0 ZIP SHA256 不变
```

**最终状态：RESULT_FIRST_VERIFIED。本阶段到此停止；「换数据库效果会不会变」留待第十三阶段 Database / Business Adapter。**
