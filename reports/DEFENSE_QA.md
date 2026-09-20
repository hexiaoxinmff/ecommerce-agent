# Defense Q&A（答辩问答速查）

> 用途：覆盖答辩高频问题，每题给出「一句话回答 → 解释 → 证据」，可现场直接说。
> 口径红线：所有数字均为冻结数据；E3 只能表述为「机制验证 / 观测差异」；未实现能力如实说明。
> 标记：**【高风险·必背】** 为评委最可能追问的问题（对应 §十四 专项）。

---

## A. 项目背景

### Q1 为什么做这个项目？
### 标准回答
> 针对电商运营"提数难、等数久"的痛点：业务人员不会写 SQL，取数依赖分析师排期。本项目让用户用自然语言直接查库，把取数从小时级缩短到秒级。
### 追问
老师问：市面上 BI / 报表工具不也能做到吗？
### 追问回答
> BI 报表面向预设问题，新问题要新建报表；本项目是"任意自然语言问题 → 自动生成可执行 SQL"，并保留 SQL 与执行链路可验证，答案可追溯。
### 证据
`docs/PRD.md` §2（背景与痛点）、§5（使用场景）。

### Q2 为什么选择 Text2SQL？
### 标准回答
> Text2SQL 是"自然语言 → 可执行 SQL"的成熟技术路线，有 Spider 等公开基准与 DB-GPT-Hub 等参考实现；任务书明确要求该方向，且能形成「提问—查询—出图—结论」闭环。
### 追问
老师问：为什么不用 RAG 直接答？
### 追问回答
> 分析类问题要求具体数字与可验证口径，RAG 生成结论无法保证与库内数据一致；Text2SQL 以真实 SQL 执行为准，数字可回溯。
### 证据
任务书 1.1/1.2；`docs/tech-research.md`。

### Q3 和普通 ChatGPT 生成 SQL 有什么区别？ 【高风险·必背】
### 标准回答
> ChatGPT 只"生成 SQL 文本"；本项目把生成结果送入独立安全校验、只读执行、失败自动修复，并用 100 条基准评测，形成「生成 → 安全 → 执行 → 修复 → 评测」闭环。
### 追问
老师问：那核心还是模型的 SQL 能力，你们做的工作在哪？
### 追问回答
> 在工程可靠性：确定性代码把关 LLM 输出（写操作/多语句/语法/表列全部拦截）、数据库双只读保护、有界 Repair、全链路 Trace 与评测门禁，这些是模型本身不具备的。
### 证据
`docs/PRD.md` §2.5；`backend/app/sqlgen/safety.py`；`FINAL_ACCEPTANCE_REPORT.md` §5/§6。

---

## B. 技术架构

### Q4 为什么使用 LangGraph？ 【高风险·必背】
### 标准回答
> LangGraph 提供显式状态图：节点、条件边、有界循环。链路固定为 Schema→Few-shot→生成→安全→执行→Repair，每个环节可观测、可归因、不会失控。
### 追问
老师问：和线性脚本串起来有什么区别？
### 追问回答
> 脚本无法表达条件分支与状态流转（如"执行失败才走 Repair"）、无法约束重试次数；LangGraph 把这些变成图结构，代码即架构、可审计。
### 证据
`docs/langgraph-agent.md`；`backend/app/agent/graph.py`（`repair_count≤1 / execute_count≤2`）。

### Q5 为什么不用普通 Agent / ReAct 自由循环？
### 标准回答
> 自由 ReAct 循环不可预测、可能无限重试、难以评测。本项目是"控制式 Agent"：固定 7 节点链路 + 有界 Repair，可执行、可验证、可评测。
### 追问
老师问：这是不是放弃 Agent 智能性？
### 追问回答
> 不是。自由的"思考—行动"循环在本场景弊大于利；我们把智能集中在高质量 SQL 生成，可靠性交给确定性代码，两者分工。
### 证据
`backend/app/main.py`（明确"未接入：自由 ReAct Agent / SQL 无限自循环"）；`FINAL_ACCEPTANCE_REPORT.md` §5。

### Q6 Schema Linking 有什么作用？
### 标准回答
> 5 张表、几十个字段，全量塞给模型会引入噪声。Schema Linking 先定位问题相关的表/字段/置信度，缩小生成空间，提高准确率且失败可归因。
### 追问
老师问：输出怎么保证可信？
### 追问回答
> Linking 结果会与数据库真实 Schema 复核（`SchemaCatalog`），不存在的表/列会被拒绝；前端页面可见"匹配到哪些表/字段"。
### 证据
`docs/schema-linking.md`；`backend/app/schema/`；`/api/schema/link`。

### Q7 Few-shot 如何检索？
### 标准回答
> 规则型本地检索：按表/字段/关键词与示例做相似度打分，返回 Top-K（上限 50）个「问题—SQL」示例，不依赖向量库与网络。
### 追问
老师问：示例哪来的？会不会和测试题重复造成泄漏？
### 追问回答
> 示例为人工整理入库且评审过（FEWSHOT_V3，23 条）；运行前有 Leakage Gate 校验示例与 Benchmark 无泄漏，Leakage Gate 记录 PASS。
### 证据
`docs/fewshot-retrieval.md`；`/api/fewshot/retrieve`；`data/fewshot/ecommerce_examples.json`；`scripts/check_benchmark_leakage.py`。

### Q8 为什么需要 SQL Safety？
### 标准回答
> LLM 生成的 SQL 不可直接信任：可能语法错误、引用不存在的列、甚至写操作。安全校验用确定性代码（sqlglot AST）把关：只读白名单、多语句禁止、表列存在性、强制 LIMIT≤500。
### 追问
老师问：拒到什么程度？
### 追问回答
> 生成后、执行前各校验一次；Executor 执行前再校验一次（最后一道防线），写操作/多语句在进入数据库前即被拒（HTTP 422）。
### 证据
`docs/sql-generator.md`（安全部分）；`backend/app/sqlgen/safety.py`；`backend/app/sqlexec/executor.py`；`docs/TEST_REPORT.md` §2。

### Q9 为什么数据库必须只读？
### 标准回答
> 防止自然语言被诱导执行危险语句（提示词注入）。两层双保险：连接 `mode=ro`（文件只读）+ `PRAGMA query_only=ON`（会话只读），数据库层拒绝一切写操作。
### 追问
老师问：那数据更新怎么办？
### 追问回答
> 本项目是查询分析场景，数据由 `scripts/init_db.py` 用固定 seed 重建；查询侧只读不影响分析功能，也满足任务书"只读账号 + 禁用 DROP/DELETE"要求。
### 证据
`docs/sql-executor.md`；`backend/app/db/sqlite.py`；任务书 6.2。

### Q10 Repair 为什么限制为 ≤1？
### 标准回答
> 有界性保证系统不会无限重试：最多 1 次修复 + 最多 2 次执行，修复后再做安全校验再执行，仍失败则返回完整诊断，绝不死循环。
### 追问
老师问：1 次够吗？
### 追问回答
> 评测显示 Repair 触发率仅 1% 左右；1 次修复覆盖绝大多数可修复错误（如表/列引用错误），更多次数收益极低且失控风险上升。
### 证据
`docs/sql-repair.md`；`FINAL_ACCEPTANCE_REPORT.md` §5；`clean_baseline_v1_1.md` §3（Repair Trigger 1.0%）。

---

## C. SQL / 数据库

### Q11 为什么使用 SQLite？
### 标准回答
> 课程项目/本地 Demo 定位：SQLite 单文件、零运维、跨平台，够支撑 5 张表约 4.3 万行的分析场景；任务书数据库栏也指定 sqlite3。
### 追问
老师问：生产上用 SQLite 有局限吧？
### 追问回答
> 有——并发写、大规模不适用。本项目定位本地 Demo 与教学验证；后续若上生产可平滑迁到 MySQL/PostgreSQL，SQL 语义基本兼容。
### 证据
`docs/database-schema.md` §1；`docs/DEPLOYMENT.md` §8（定位声明）。

### Q12 为什么用 sqlite3 而不是 SQLAlchemy？ 【高风险·必背】
### 标准回答
> 本系统对数据库只读、无对象映射需求（不写 ORM），Python 标准库 sqlite3 零依赖、够用。任务书技术表是"sqlite3 / SQLAlchemy"，差异已如实披露。
### 追问
老师问：这是不是没按任务书做？
### 追问回答
> 任务书允许二选一；我选用 sqlite3 并保留只读 URI + query_only 双重保护，在验收报告和 README 中明确写了"SQLAlchemy 未使用"，不包装成"全部采用"。
### 证据
任务书 3.2「SQL 执行引擎 sqlite3 / SQLAlchemy」；`README.md` §4（未使用清单）；`docs/backend-architecture.md`。

### Q13 subtotal 和 total_amount 有什么区别？
### 标准回答
> `order_items.subtotal` 是单行明细金额（=单价×数量）；`orders.total_amount` 是订单最终实付金额，含折扣、运费等订单级调整，两者可以不同。
### 追问
老师问：会不会是数据乱？
### 追问回答
> 不会。全库经 `scripts/init_db.py` 验证：`total_amount = Σsubtotal − discount + shipping` 不一致订单数为 0，差异来自可解释业务因素。
### 证据
`docs/database-schema.md` §4；`docs/PRD.md` §15.1/15.2。

### Q14 cancelled 为什么排除？
### 标准回答
> 统一销售口径：取消订单保留明细但实付为 0，不计入任何"实际销售"类统计（销售额/销量/客单价）。该口径在 Schema、Prompt、示例库、Gold 四端统一。
### 追问
老师问：所有查询都要排除吗？
### 追问回答
> 只针对"实际销售"类指标；订单量、状态分布等结构统计不排除。Prompt 与示例库中已固化该约定。
### 证据
`data/eval/README.md` §6；`docs/PRD.md` §15.3；`data/prompts/sql_generator_v1.3.txt`（BUSINESS_RULES）。

### Q15 Fan-out 是什么？ 【高风险·必背】
### 标准回答
> 一对多 JOIN（如订单 × 订单明细）会让事实表行数成倍放大，若直接对放大后的结果做 SUM 等聚合，数值被错误放大——这就是 fan-out。
### 追问
老师问：具体影响多大？
### 追问回答
> E-0086 中 `SUM(total_amount)` 直连明细后累计消费额放大约 4.14×：369854.65 对真实 89397.46，属典型粒度错误。
### 证据
`reports/eval/E3_FINAL_FREEZE.md`；`reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` §7（E-0086）。

---

## D. Evaluation

### Q16 为什么 EX 是核心指标？ 【高风险·必背】
### 标准回答
> EX（Execution Accuracy）把 pred 的真实执行结果与 Gold 的真实执行结果做归一化比较，反映"系统最终给用户的数字对不对"，比文本匹配更贴近业务价值。
### 追问
老师问：字符串匹配不是更严格吗？
### 追问回答
> 字符串相等太苛刻（列顺序、别名不同就判错），会低估系统能力；本项目用 `evaluation/normalization.py` 归一化后再比（集合/数值/排名口径），并配套 Exec Rate、Pass@1。
### 证据
`docs/evaluation-plan.md`；`evaluation/normalization.py`；`reports/FINAL_ACCEPTANCE_REPORT.md` §9。

### Q17 90% EX 怎么得到？ 【高风险·必背】
### 标准回答
> 用 ECO-SQL-Bench v1.1（100 条）串行实测：Mimo V2.5 Pro + Prompt V1.3 + FEWSHOT_V3(23) + dev-2026-09-14 库，得到 Clean Baseline EX=90.0%、Exec 99.0%、Pass@1 90.0%、Provider 0、Timeout 0。
### 追问
老师问：能复现吗？会不会是你挑的结果？
### 追问回答
> 可复现：`python scripts/run_eval.py` 启动前强制 Gold Hash Gate（100/100 重算一致）+ Leakage Gate（无泄漏）+ 数据库前后 hash 校验，报告完整落盘在 `reports/eval/clean_baseline_v1_1/`。
### 证据
`reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md`（含实验指纹与全部 hash 字段）。

### Q18 Benchmark 有多少题？
### 标准回答
> ECO-SQL-Bench v1.1 共 100 条：Easy 25 / Medium 30 / Hard 30 / Extra Hard 15，覆盖销售、商品、用户、地区、趋势、Top-N 等电商场景。
### 追问
老师问：题怎么来的？质量怎么保证？
### 追问回答
> 分批人工撰写并按 Gold 验收规范（人工审核语义 → 真实库执行 → 人工核对 → 记录 hash）入库；100 条均通过结构与可执行校验。
### 证据
`data/eval/ecommerce_eval_v1.json`；`data/eval/README.md`；`docs/evaluation-dataset-spec.md`。

### Q19 Gold Hash Gate 是干什么的？
### 标准回答
> 每次评测运行前，用同一数据库重算全部 100 题 Gold 的执行结果哈希与期望记录比对，防止 Gold 或数据库漂移导致结果不可复现。
### 追问
老师问：验证到什么粒度？
### 追问回答
> 100/100 全部重算比对，任何一处不一致即整体停止；此外还校验评测前后数据库文件 hash 一致，确认评测过程未改动数据库。
### 证据
`backend/tests/test_eval_runner.py`（hash gate 用例）；`reports/eval/clean_baseline_v1_1/` §2。

### Q20 为什么 Easy/Medium 100% 而 Extra Hard 60%？
### 标准回答
> 简单题覆盖基础聚合与单表查询；Extra Hard 集中在多表、嵌套、排名与多口径问题，模型在这些场景更易犯聚合粒度、过滤遗漏、输出结构错误。如实呈现，不做"好坏"包装。
### 追问
老师问：这算不算系统能力不足？
### 追问回答
> 是所有 LLM 的共性局限（任务书 6.3 也说明复杂多表/嵌套准确率下降）；这正是我们沉淀 Bad Case 反哺示例库与提示词的迭代点。
### 证据
`clean_baseline_v1_1.md` §4；`reports/FINAL_BAD_CASE_CATALOG.md`。

---

## E. E3

### Q21 E3 为什么不直接使用 Gold？
### 标准回答
> 因为"有 Gold 才知道对错"无法在真实拦截场景使用；E3 的 Detector 只输入预测 SQL（Gold-independent）做静态风险检测，不依赖标准答案，更接近部署时的真实可用形态。
### 追问
老师问：那怎么验证它检测得对？
### 追问回答
> 用离线审计验证：Task 17 对 20 条候选双表题人工审计漏报 0/20；Task 19 独立审计确认无真实漏报；再与 Gold 对照做相关性分析（Task 18）。
### 证据
`reports/eval/E3_FINAL_FREEZE.md`；`reports/eval/task17~19`。

### Q22 Fan-out Detector 检测什么？
### 标准回答
> 检测 Pred SQL 中「订单 × 订单明细」粒度风险：如直接对该连接结果做 `SUM`、`COUNT(*)` 歧义等模式，判断是否存在聚合放大风险。静态规则，无 LLM 调用。
### 追问
老师问：只覆盖这两张表吗？
### 追问回答
> 是，当前限定 orders×order_items（P2-4）；子查询剪枝未生效、未限定列名存在漏报盲区，属下一版本工作，已在冻结文档披露。
### 证据
`backend/app/sqlcheck/fanout_detector.py`（冻结）；`reports/eval/task17_e3_fanout_validator/detector_rules.md`。

### Q23 E-0086 为什么会放大 4.14×？
### 标准回答
> 该题统计"累计消费金额"，正确做法先按订单粒度聚合；模型却把 `SUM(o.total_amount)` 直接作用于订单×明细连接结果，行数被放大，金额随之膨胀。
### 追问
老师问：4.14× 怎么来的？
### 追问回答
> 数据库直连验证：Pred SQL 得 369854.65，正确的双 CTE Gold 口径为 89397.46，二者比值约 4.14×。
### 证据
`reports/eval/task20_e3_hint_intervention/single_case_e0086.md`。

### Q24 为什么 OFF 90 / ON 93 不能说提升 3pt？ 【高风险·必背】
### 标准回答
> 因为两组不是严格单变量：单题超时不同（60s vs 90s）、管道不同（正式 Agent vs 独立脚本）、样本独立且 alarm 仅 1 条；93% 中只有 E-0086 的 +1pt 有 Hint 直接归因证据。
### 追问
老师问：E-0099/E-0100 不是也变对了吗？
### 追问回答
> 是，但这两题本轮未触发 alarm（未注入 Hint），改善来自独立样本随机性，不接受 Hint 归因。因此禁止表述"Hint 提升 3 个百分点"。
### 证据
`reports/eval/task21_e3_hint_intervention/comparison.md`；`reports/eval/E3_FINAL_FREEZE.md` §二。

### Q25 alarm n=1 意味着什么？
### 标准回答
> 证据强度低：只有一个 Hit 样本，无法支撑"整体 EX 稳定提升 / 高召回 / 普遍有效"等结论；E3 定位为机制验证（proof of concept）。
### 追问
老师问：那这个创新点算不算成立？
### 追问回答
> 成立的是"机制可运行且单例实证修复成功"；但结论边界必须如实：alarm n=1，需要更多样本才能谈推广性。
### 证据
`reports/eval/E3_FINAL_FREEZE.md` §四（限制）。

---

## F. 项目不足

### Q26 为什么没有 Multi-turn？ 【高风险·必背】
### 标准回答
> 多轮追问、上下文继承在 PRD 中明确属于阶段 2 / Out-of-Scope；当前交付聚焦单轮最小闭环从提问到可验证结果，E2E Q5 也验证了"多轮追问"按单轮行为处理。
### 追问
老师问：任务书明确要多轮，为什么没做？
### 追问回答
> 在有限工期做了取舍：先把单轮链路做到可评测（90% EX）、安全与修复闭环稳定，再接多轮；这属于优先级而非能力缺失，已在验收报告中如实列入。
### 证据
`docs/PRD.md` §7/§20（阶段2）；`FINAL_ACCEPTANCE_REPORT.md` §3/§12；`reports/FINAL_DELIVERY_GAP_CHECK.md` P1-4。

### Q27 为什么没有用户登录？
### 标准回答
> 任务书用户管理模块属产品级功能，与核心 Text2SQL 闭环解耦；PRD 明确 Out of Scope（角色克制，不做用户/权限体系），本次聚焦分析能力。
### 追问
老师问：安全审计不要用户体系吗？
### 追问回答
> 单机/本地 Demo 场景无多用户暴露面；查询安全通过只读 + Safety 层保证，账号体系列入后续工作。
### 证据
`docs/PRD.md` §4（角色克制）；`reports/FINAL_DELIVERY_GAP_CHECK.md` P1-5。

### Q28 为什么没有完整结论生成？
### 标准回答
> 运行侧没有"结论"节点：当前返回结构化结果 + Trace，结论式文案（归因/解读）属后续能力；评测侧已有的归一化与结果判定不等同于结论生成。
### 追问
老师问：任务书要求"生成与数据一致的经营结论文字"？
### 追问回答
> 是，该项未实现并在验收/缺口报告中如实标注；已实现的是可验证的查询结果与透明链路，结论生成列为后续工作优先级第 2 位。
### 证据
`backend/app/main.py`（"未接入：结论与图表生成"）；`reports/FINAL_DELIVERY_GAP_CHECK.md` P1-6。

### Q29 为什么平均响应时间超过 8 秒？ 【高风险·必背】
### 标准回答
> Clean Baseline 平均约 10.9s（P50 10.5s / P95 15.4s），主要耗时是 Mimo 推理（Schema Linking + SQL 生成两次调用占大头），数据集本身查询毫秒级。
### 追问
老师问：任务书要求 ≤8s，怎么解释？
### 追问回答
> 如实披露未达标：8s 是任务书目标，当前为串行两段 LLM 调用 + 未做缓存/并行优化。改进方向：Schema Linking 缓存、并行化、超时分档——列为后续工作，不回避。
### 证据
`clean_baseline_v1_1.md` §5（Latency）；`reports/FINAL_DELIVERY_GAP_CHECK.md` P1-3。

### Q30 为什么没有使用 Spider 原始样例？ 【高风险·必背】
### 标准回答
> 如实说明差异：任务书要求基于 Spider 电商表格建库、建评测集；项目采用自建规则化合成库（固定 seed 可复现）+ 自建 100 条 ECO-SQL-Bench，数量要求达成、数据来源不同。
### 追问
老师问：自己造数据会不会自说自话？
### 追问回答
> 我们做了三重弥补：Gold 全部人工审核 + 真实库执行 + 结果 hash 入库；评测带 Gold Hash 与 Leakage 门禁；数据生成脚本与 seed 全量归档可复现。来源差异在 README 与缺口中如实披露。
### 证据
`data/eval/README.md`；`scripts/init_db.py`（seed 20260914）；`reports/FINAL_DELIVERY_GAP_CHECK.md` P1-8。

### Q31 为什么没有 SSE？ 【高风险·必背】
### 标准回答
> 任务书技术表含"RESTful / SSE 流式 API"；当前实现为 REST 请求-响应（整包返回结果 + Trace），未实现 SSE 流式输出，差异已披露。
### 追问
老师问：前端加载流程是假的流式吗？
### 追问回答
> 前端"阶段滚动"是本地视觉动画，真实结果整包返回后渲染——文档已明确这不是流式。SSE 列为后续工作（优先级 5）。
### 证据
`docs/UI-UX.md`（阶段动画说明）；`reports/FINAL_DELIVERY_GAP_CHECK.md` P1-7。

---

## G. AI 协作

### Q32 TRAE / WorkBuddy / ChatGPT / Mimo 分别负责什么？
### 标准回答
> ChatGPT：总体架构、实验设计与验收口径；TRAE：主开发实现、测试与实验执行；WorkBuddy：独立审计、反例检查与实验复核；Mimo V2.5 Pro：运行时 SQL 生成（推理模型）。
### 追问
老师问：Mimo 既是工具又是系统模型？
### 追问回答
> 对：开发期它参与讨论/评审，运行期它是系统实际调用生成 SQL 的模型（Runtime 角色），本文档中"运行时 SQL Generation"特指后者。
### 证据
`docs/AI_COLLABORATION.md` §1/§2。

### Q33 AI 写的代码怎么保证正确？
### 标准回答
> 四道校验：单元测试 367 passed；评测门禁（Gold Hash / Leakage / DB hash）；Task 22 对冻结数据做哈希级复核；Task 23 人工实测验收（Backend/Frontend/E2E 全 PASS）。
### 追问
老师问：测试没覆盖的怎么办？
### 追问回答
> 靠文档如实披露 + 验收清单：FINAL_REQUIREMENTS_CHECKLIST 逐项对勾，已知限制（多轮、SSE 等）全部列入，不把未实现写成已实现。
### 证据
`docs/TEST_REPORT.md`；`reports/FINAL_REQUIREMENTS_CHECKLIST.md`；`reports/FINAL_ACCEPTANCE_REPORT.md`。

### Q34 WorkBuddy 为什么要做独立审计？
### 标准回答
> 实现方自证有立场偏差。WorkBuddy 以独立身份做反例检查与实验复核，例如 Task 19 漏报审计（0/20 FN）、Task 22 冻结 hash 复核（结论 PASS WITH RESERVATIONS）。
### 追问
老师问：审计的保留项是什么？
### 追问回答
> 主要是 alarm n=1 证据强度低与 Detector 已知局限（子查询剪枝、列名盲区）——这些已成为 E3 冻结边界的一部分。
### 证据
`docs/AI_COLLABORATION.md` §4.3；`reports/eval/task19_e3_fanout_audit/audit_report.md`。

### Q35 如何避免 AI 编造实验结论？
### 标准回答
> 规则是"先冻结、后引用"：实验数据由 evaluation/ 框架计算并落盘，人工验收后 FROZEN；此后任何文档/PPT 只引用冻结数字，并明文禁止"提升 3pt"类表述。
### 追问
老师问：谁来执行这条规则？
### 追问回答
> 每阶段有独立审计（WorkBuddy）+ 最终半自动检查（全文搜索禁用表述，如"显著提升/准确率100"），Task 22~25 均执行过该检查。
### 证据
`reports/eval/E3_FINAL_FREEZE.md`；`docs/AI_COLLABORATION.md` §5；`reports/FINAL_DELIVERY_GAP_CHECK.md` §3。

---

## H. 高风险问题专项速答（最可能被追问）

| 问题 | 一句话回答 | 证据 |
|---|---|---|
| 90% 怎么来的？ | 100 条 ECO-SQL-Bench v1.1 串行实测，双门禁（Gold Hash + Leakage）把关，报告落盘可复现 | `clean_baseline_v1_1/clean_baseline_v1_1.md` |
| E3 是不是调 Prompt 涨了 3%？ | 90→93 是观测差异且非严格单变量；仅 E-0086 +1pt 有 Hint 直接归因；alarm n=1 | `task21_e3_hint_intervention/comparison.md`、`E3_FINAL_FREEZE.md` |
| 任务书 ≤8s 为什么没做到？ | 平均 10.9s，主因两次 Mimo 串行推理；未缓存未并行，如实披露为 P1，改进已列后续 | `clean_baseline_v1_1.md` §5、`FINAL_DELIVERY_GAP_CHECK.md` P1-3 |
| 任务书要 Spider，为什么自造数据？ | 采用自建合成库（seed 可复现）+ 自建 100 条评测集，数量达成、来源不同，差异如实披露并用三重校验保证可信 | `data/eval/README.md`、`FINAL_DELIVERY_GAP_CHECK.md` P1-8 |
| 任务书要 Multi-turn，为什么没做？ | PRD 阶段 2 / Out-of-Scope；先做单轮可评测闭环，多轮属后续工作，验收已如实列 | `PRD.md` §7、`FINAL_ACCEPTANCE_REPORT.md` §3 |
| 任务书要 SSE，为什么没有？ | 当前 REST 整包返回，前端阶段动画非流式；SSE 列后续工作（P1-7） | `FINAL_DELIVERY_GAP_CHECK.md` P1-7 |
| 你的项目创新点到底是什么？ | ①Gold-independent Fan-out 检测（无标签可拦截，E3 实证单例修复）②有界可审计的控制式 Agent 闭环 ③规则型可解释 Few-shot（无向量库）④只读安全 + 有界自修复；E3 定位 PoC 有证据 | `E3_FINAL_FREEZE.md`、`backend/app/sqlcheck/` |

---

*编写：Task 27（2026-09-16）。所有回答基于冻结数据与仓库真实实现；高风险题以「先一句话 → 再解释 → 给证据」结构组织。*