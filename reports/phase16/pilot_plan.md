# Phase 16：Business Pilot 实际试点与反馈闭环 —— 试点实施方案

**阶段状态：`BUSINESS_PILOT_KICKED_OFF`（试点方案与记录基础设施就绪，等待真实使用数据）**

- 上一状态：`BUSINESS_PILOT_READY_FOR_PILOT`（Phase 15，2026-10-02）
- 试点周期：10 个工作日，开跑当天在下方填写起止日期
- 试点日期：____-__-__ ~ ____-__-__（第 5 个工作日中期检查点，第 10 个工作日出结论）

---

## 0. 一句话定位

> 本阶段不是继续开发，也不是继续评测：把系统交给真实业务人员每天真实使用，
> 用真实行为决定下一轮产品改什么。真实用户一句「最近销售怎么样」，
> 往往比一整套精心设计的 Benchmark 更能暴露产品问题。

## 1. 本阶段原则（红线）

- 第一原则：**真实用户反馈优先于继续堆功能。**
- 试点期间**禁止**新增：多 Agent、多轮对话、向量数据库、微服务、企业级权限、
  多租户、复杂 BI、大规模监控、PostgreSQL、新 Benchmark。
- 试点期间只允许「小修复」（见 §9），否则无法区分用户反馈来自真实系统，
  还是来自连续改代码造成的环境变化。
- **不为了得到「成功」状态而修改统计口径**；所有数字以真实结果为准。
- 不要急着修 Unsupported Concept（见 §5）：先观察真实样本，试点结束再做策略。

## 2. 人员与角色（不扩大样本）

| 角色 | 人数 | 职责 |
|---|---|---|
| 核心用户：电商运营专员 | 1 | 每工作日 15~30 分钟真实使用，随手提问，给出真实判断 |
| 辅助用户：运营主管 | 1 | 少量使用 + 验收视角（结果敢不敢拿去做业务） |
| 陪跑：项目维护人员 | 1 | 记录反馈与原始 Trace、每日复盘、问题入池；**不引导提问** |

对用户如实说明的前提：当前库为演示合成电商数据；试点评估的是「真实工作流中的产品能力」。

## 3. 场景与节奏

- 场景：**运营日常销售速查**——开屏看 Dashboard KPI → 自然语言追问细节
  （某类目/地区/时间窗的销售、Top 榜、状态分布）→ 参考结果做当日运营动作。
- 周期：**10 个工作日**，每工作日 15~30 分钟真实使用。
- **必须允许自然输入，不要刻意按测试题提问。** 鼓励例如：
  - 「今天销售怎么样？」
  - 「哪个商品最近卖得最好？」
  - 「女装这块表现怎么样？」
  - 「为什么这个月销售额下降了？」
  - 「VIP 用户有多少？」
  - 「上个月比这个月怎么样？」
- 用户放弃、换问法、重复提问都是数据，必须如实记录（反馈表 + History 均可体现）。

## 4. 反馈机制：pilot_feedback.csv（零代码起步）

每条真实问题一行，陪跑人当场记录、用户口头确认；字段与取值约定：

| 字段 | 含义 | 取值约定 |
|---|---|---|
| date | 试点日 | YYYY-MM-DD |
| user_role | 提问者 | specialist / supervisor |
| question | 用户原话 | 逐字记录，不改写、不翻译 |
| result_available | 用户有没有得到结果 | yes / no |
| result_correct | 数值是否正确（陪跑可核对 History/SQL） | yes / no / unclear |
| business_meaning_correct | 业务意义是否正确（口径理解） | yes / no / unclear |
| time_range_correct | 时间范围是否符合用户意图 | yes / no / unclear |
| kpi_definition_clear | 用户是否知道这个指标怎么算 | yes / no |
| user_trust | 用户是否愿意拿这个数字继续做业务 | yes / no |
| user_actionable | 结果是否足以支持下一步动作 | yes / no |
| latency_acceptable | 等待时间是否可接受 | yes / no |
| failure_type | 失败归类（§6，无失败填 none） | none / technical / schema_error / business_semantic / user_intent_ambiguity / concept_not_exists / other |
| user_comment | 用户点评 | 自由文本（尽量记原话） |
| concept_exists | **问题的概念在库中是否存在**（Phase 15 Q2 要求陪跑逐条核对） | yes / no / unclear |
| observation_tag | 重点观察项标记（§5） | none / unsupported_concept / ambiguous_time / both |
| trace_ref | 对应原始 Trace（pilot_raw_log.csv 行号 / History 条目） | 如 R0007 |

## 5. 两个重点观察项（只观察，不预先修）

Phase 15 遗留两个未解决问题。本阶段不先假设怎么修，真实观察：

```text
用户问什么 → Agent 怎么回答 → 用户是否相信 → 用户是否发现概念不对
```

### 观察项 A：Unsupported Concept（预登记 ISSUE-PRE-001）

- 背景：Phase 15 陷阱题实测「有多少 VIP 用户？」仍静默答 1707（= active 用户数）。
- 观察点：真实用户会不会问这类概念不存在的问题？会问哪些？哪些最容易被误解？
  用户能接受什么拒答方式？
- 目标：试点结束按真实样本设计 **Unsupported / Ambiguous Intent Policy**，
  而不是凭空设计几十条拒答规则。

### 观察项 B：Ambiguous Time（预登记 ISSUE-PRE-002）

- 背景：Phase 15 陷阱题实测「最近卖得怎么样？」静默自选 30 天窗口且不声明。
- 观察点：Agent 自选时间范围，还是用户需要补充？用户是否接受这个解释？

## 6. 失败四分类（每条问题必须归类）

1. `technical`：技术失败——API/LLM timeout、SQL 执行错误、前端报错。
2. `schema_error`：找错表、找错字段、Join 错误。
3. `business_semantic`：销售额理解错误、有效订单理解错误、业务概念理解错误。
4. `user_intent_ambiguity`：「最近」「现在」「表现」「情况如何」「好不好」等模糊表达。
   **这一类不直接算 Agent 错误**——需区分用户本身没有给出足够明确的条件。

补充标记 `concept_not_exists`：库中根本没有该概念而 Agent 编造或猜近义概念
（business_semantic 的特例，单独标记以便 Unsupported Concept 统计）。

## 7. 真实 Trace 强制保留（已核查，不关闭）

试点期间**不关闭**：SQL、Trace、latency、data_as_of、history。
它们主要用于出现问题时维护人员可以追溯；**不要求运营人员理解它们**。

- 用户看到：结果、数据截至、指标口径。
- 维护人员可展开：SQL、Trace、Profile、Business Rule。

已核查（2026-10-02）：

| 核查项 | 结果 |
|---|---|
| History 落库字段 | question / sql / success / error_message / result_summary / row_count / total_time_ms / created_at（`backend/app/api/routes/history.py`）✅ |
| data_as_of | Agent 响应携带（Phase 15 P0-1 契约）✅ |
| 启动冒烟 | `GET /api/health` → status=ok、database=ok(ecommerce.db)、llm provider 正常解析 ✅ |

**原始数据保留（每条真实问题一行，`pilot_raw_log.csv`）**：
Question / Agent Response / SQL / Result / data_as_of / latency / User Feedback /
Final Classification。数据来源用 History 接口（`GET /api/history`）与 Agent 响应载荷，
**不要凭记忆补填**。这份原始数据后续沉淀为 Real Business Dataset v2，
比课程 Benchmark 更有价值。

## 8. 核心指标与判定线（每日记录，期末判定）

不重新使用单纯 EX 作为唯一指标。每日从 pilot_feedback.csv 计算：

| 指标 | 定义 | 判定线 |
|---|---|---|
| Query Success Rate | result_available=yes 且用户认可业务含义（business_meaning_correct≠no）的比率；严格数值正确率（result_correct=yes）另行如实记录 | ≥ 95% |
| 首次可用率 | 用户无需重问/换问法即得到可用答案的比率 | ≥ 70% |
| Silent Wrong Rate | 陪跑逐条核对发现「表面有结果但口径/时间窗错误」的比率（用户未必发现） | ≤ 10% |
| 用户主动修正率 | 用户主动换问法/重问/纠正后才成功的比率 | 记录 |
| 重复提问率 | 同一问题 7 天内被再次提问的比率（History + 反馈表） | 记录（目标 ≤20%） |
| 平均响应时间 | total_time_ms 均值 | 记录（目标 ≤5s） |

信任指标：用户是否继续使用、是否愿意参考结果做下一步动作、是否主动回来再次查询。

**试点成功条件（10 个工作日结束后判定）**：

- 业务可用：Query Success Rate ≥95%，首次可用率 ≥70%，Silent Wrong Rate ≤10%。
- 用户行为：至少出现用户主动发起非测试问题；且第 2 周没有明显使用衰减
  （第 2 周使用天数 ≥ 第 1 周）。

**不要提前假设一定达到。** 期末状态三选一，按真实数字判定：

```text
BUSINESS_PILOT_VALIDATED / BUSINESS_PILOT_PARTIALLY_VALIDATED / BUSINESS_PILOT_BLOCKED
```

**暂停线（Phase 14 §9 F1~F4，触发即暂停试点）**：

- F1：用户基于结果做出错误业务决策，且源头是静默错误（口径/时间）；
- F2：抽检 Silent Wrong Rate 连续两周 >10%；
- F3：平均等待 >10s 或失败率 >20% 导致放弃；
- F4：用户第 2 周起不再自发使用。

## 9. 试点期间只允许「小修复」

允许：明显文案错误、明显 UI 可用性问题、日志记录问题、数据展示问题、明确确定的业务规则错误。

暂不允许：大规模 Prompt 重写、Agent 架构重构、更换模型、更换数据库、更换评测体系。

每个小修复必须在 `pilot_issue_log.md` 登记（Issue → Proposed Action → Status），
保证「反馈来自系统还是来自环境变化」可追溯。

## 10. 问题池

- 所有问题登记入 `pilot_issue_log.md`（Issue ID / Category / Severity / Frequency …）。
- Severity：P0 = 可能造成错误业务决策；P1 = 明显影响使用；P2 = 体验问题；P3 = 优化项。
- **一次问题不一定值得改；连续出现 ≥3 次才进入候选产品问题。**
- Phase 15 已知问题预登记为 ISSUE-PRE-001/002/003，试点期观察真实发生率，不预先修复。

## 11. 冻结线（本阶段零触碰）

v1.0 ZIP、`_delivery_build/`、正式 Benchmark（ecommerce_eval_v1.json）、
Phase 13 实验数据、Phase 14 RBQ baseline、Phase 15 P0 回归结果——
一律不修改、不覆盖。真实试点产生的新数据只新增于 `reports/phase16/`，不覆盖历史结果。

## 12. 开跑前就绪核查（2026-10-02 已执行）

| 核查项 | 结果 |
|---|---|
| Phase 15 STATUS | BUSINESS_PILOT_READY_FOR_PILOT：P0-1/2/3 全部修复，RBQ-P20 EX 90.9%（20/22），执行率 100%，Silent Wrong 0/22，Dashboard/Agent/KPI 三方一致，首页假分析已删除，前端 114/114，后端 P0 验收全过 |
| 后端启动冒烟 | uvicorn 启动成功；`GET /api/health` → status=ok / database=ok(ecommerce.db) / llm provider 正常解析 |
| Day-0 全链路冒烟 | `python scripts/pilot_day0_smoke.py --full`：注册(201) → 登录(bearer) → 真实 LLM 分析「本月销售额是多少？」826,080.07（SQL 明细口径，data_as_of=2026-09-12，3.99s）→ Dashboard 一致（826,080.07 == 826,080.07）→ History 落库（含 SQL + total_time_ms）→ 冒烟账号清理，**7/7 PASS**（2026-10-02，产物 `pilot_day0_smoke_result.json`） |
| Trace 保留 | History 落库字段齐全；data_as_of 在 Agent 响应中 |
| 冻结资产 | 本阶段仅新增 `reports/phase16/` 与 `scripts/pilot_day0_smoke.py`，无任何覆盖 |

## 13. 每日流程（陪跑人员）

0. 开机自检：`python scripts/pilot_day0_smoke.py --base-url http://127.0.0.1:8000`
   （health-only，零 LLM 成本；退出码 0 才开跑。Day-0 用 `--full` 走一次全链路）；
1. 用户真实使用 15~30 分钟（陪跑只记录，不引导）；
2. 每条问题当场填 `pilot_feedback.csv` 一行 + `pilot_raw_log.csv` 一行
   （从 History 接口 / Agent 响应载荷取数，不凭记忆）；
3. 新问题入 `pilot_issue_log.md`（先观察，连续 ≥3 次才成候选）；
4. 收工前 5 分钟填 `pilot_daily_review.md` 当日一节；
5. 第 5 个工作日：中期检查点（是否触发暂停线、重复问题模式）；
6. 第 10 个工作日：填写 `第十六阶段_Business_Pilot试点总结报告.md`，
   按真实数字输出最终状态（VALIDATED / PARTIALLY_VALIDATED / BLOCKED）。

## 14. 试点结束后必须回答的 5 个问题

这 5 个问题的答案，比继续提高 Benchmark 2~3 个百分点更重要：

1. 真实运营人员最常问什么？
2. 真实运营人员最不满意什么？
3. 哪个问题是实验阶段完全没有发现的？
4. 用户是否真的因为 Agent 少做了一些原本需要人工完成的工作？
5. 用户是否愿意主动再次使用？
