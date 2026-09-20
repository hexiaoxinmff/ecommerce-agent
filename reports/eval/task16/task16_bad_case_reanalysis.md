# Task 16：Clean Baseline 10 个 Bad Case 重新分析

> Task 15 Clean Baseline：ECO-SQL-Bench v1.1 + SQLGENERATOR_PROMPT_V1.3 + FEWSHOT_V3（23条）= EX 90.0%
> 本文对 10 个 Bad Case（E-0057/E-0077/E-0082/E-0083/E-0086/E-0090/E-0095/E-0096/E-0099/E-0100）
> 基于 question / gold_sql / pred_sql / final_sql / expected / actual / normalized comparison /
> failure_stage / error_type / operators / difficulty / scenario / Schema Linking trace / Few-shot 检索 trace
> 进行逐例静态分析，输出系统问题归类（A/B/C/D 四类 + 例外项）。
>
> 不修正任何正式文件；所有修改建议均为候选方向。

---

## 0. 逐例证据表（事实层，与 Task 15 报告一致）

| eval_id | diff | scenario | schema_link 命中表 | few-shot 检索 | failure_stage | error_type | normalized 结论 |
|---|---|---|---|---|---|---|---|
| E-0057 | hard | user_analysis | users, orders(3列) | ex_010, ex_016, ex_007 | result | result_mismatch | 结果集合不一致（11单及以上 36 vs 19） |
| E-0077 | hard | regional_analysis | **仅 orders(4列)** | ex_005, ex_015, ex_009 | result | result_mismatch | 结果集合不一致（各地区金额不同） |
| E-0082 | hard | ratio | 四表(8列) | ex_003, ex_008, ex_001 | result | result_mismatch | **列数不一致 gold=2 pred=1**（值 0.81 相同） |
| E-0083 | hard | ratio | 四表(11列) | ex_003, ex_001, ex_022 | result | result_mismatch | **列数不一致 gold=2 pred=1**（值 28.98 相同） |
| E-0086 | extra_hard | user_analysis | users,orders,order_items(7列) | ex_010, ex_016, ex_009 | result | result_mismatch | 结果集合不一致（金额 fan-out 4.1×） |
| E-0090 | extra_hard | order_analysis | **仅 orders(2列)** | ex_009, ex_023, ex_015 | result | result_mismatch | **列数不一致 gold=4 pred=3**；且缺2025过滤 |
| E-0095 | extra_hard | time_analysis | 四表(11列) | ex_003, ex_001, ex_019 | result | result_mismatch | 结果集合不一致（pred 多 1 行） |
| E-0096 | extra_hard | time_analysis | orders,order_items(4列) | ex_015, ex_005, ex_001 | result | result_mismatch | 排名题集合不一致（金额不同） |
| E-0099 | extra_hard | ratio | 四表(11列) | ex_003, ex_001, ex_006 | sql_repair | SQL 执行失败: no such column: r.region | pred 无法执行 |
| E-0100 | extra_hard | comparison | orders,order_items(6列) | ex_015, ex_023, ex_001 | result | result_mismatch | 结果集合不一致（金额不同，订单量相同） |

---

## A. 输出结构（E-0082 / E-0083 / E-0090）

### A1. E-0082 / E-0083：值正确、列数不足 —— 属「结果结构错误」，不是「SQL 逻辑错误」

**证据**：
- E-0082：gold `SELECT c.name, ROUND(SUM(oi.subtotal)*100.0/(子查询),2) AS pct`（2列）；pred `SELECT ROUND(100.0*SUM(CASE...)/SUM(oi.subtotal),2) AS percentage`（1列）；**pred 计算值 0.81 与 gold 0.81 完全一致**，仅少一列 `c.name`。
- E-0083：gold 2列（name, pct=28.98）；pred 1列（percentage=28.98），同样值一致，缺 `c.name`。

**判定**：pred 的数值逻辑正确（分子分母口径、排除取消、金额字段都正确），唯一差异是**输出列数不足**。因此这两条属于「结果结构错误」（Result Shape Error），不是 SQL 逻辑错误。D1（列数可比）把它们判为不等价。

**为什么列数不足？—— 5 个候选原因逐项排除**：
1. LLM 没理解需要返回哪些列 → **不是**（pred 返回了问题要求的"比例"这一项，问题原文只问"比例是多少？"，未显式要求返回分类名）
2. Few-shot 没有多列输出示范 → **部分相关**。当前检索到的 ex_003（类目销售额排名）示范了 name+total_sales 两列，但检索到 E-0082/E-0083 的 top-3 中没有"单行占比 + label"示范；ex_023（金额档占比）是**单行单列**示范（只有 pct），检索集中没有命中也无妨。
3. **Prompt 没有明确输出契约** → **核心相关**。V1.3 的输出契约只有 JSON 结构约束，无"占比题必须同时输出分类名"这类列级契约（E4 是专项规则，且 Task 14.2 已证纯规则无效）。
4. Schema linking → 不相关（四表 8~11 列齐全）。
5. **Evaluation 输出比较方式** → **关键复杂性**。Gold 本身把 `c.name` 也放进 SELECT 输出；而问题问的是"比例是多少？"，从用户视角返回一个数值也合理。判定错在于 D1 要求列数可比且 Gold 多了一列 label。**这里存在 Benchmark=Gold 输出形状 vs 问题文本的轻微错位**：问题未要求 label，Gold 却把 label 作为输出列 → 这直接决定了 ex 判定。但既然 Gold 已固定（不得修改），模型侧必须学会"占比题默认输出维度列+数值列"（多列）来对齐 Gold 形状。

**结论（A）**：
- E-0082/E-0083 = **结果结构错误（输出列契约）**，不是逻辑错误；根因是"问题语句与 Gold 输出形状的对齐关系"没有在 Prompt/Few-shot 中示范，模型按最小回答返回单值。
- 修复候选：示范型 Few-shot（输出结构：label+value 两列）或 E8 输出形状校验（见 validation_candidate）。
- **是否"真正的系统问题"**：是，但规模=2 条，且属于"输出列契约"单一可教能力。

### A2. E-0090：复合问题 —— 过滤遗漏 + 缺总数列 + 取消订单口径

**证据**：
- gold（4列）：`status, high_cnt, normal_cnt, total_cnt`，且带 `WHERE order_date 2025`；
- pred（3列）：`status, high_amount_orders, normal_amount_orders`，**无 2025 过滤**，无 `total_cnt`；
- pred 将 cancelled 取消订单的 478 笔全部计入了 `normal_amount_orders`（gold 中 cancelled 的 high/normal 均为 0，只有 total_cnt=202）。

**判定**：E-0090 不是单一"输出结构"问题，而是**三个问题叠加**：
1. **过滤遗漏（filter placement）**：题面明说"2025年"，pred 丢了 WHERE 年份条件（与 E-0095 同族，见 §C）；
2. **输出列契约**：题面明确"并给出...分别是多少"且附注"含取消订单的结构统计"，Gold 用 total_cnt 表达"结构统计"，pred 未输出 → 结果结构错误；
3. **取消订单口径**：取消订单应只进结构统计（total_cnt），不参与金额分档（high/normal）；pred 把取消订单全归入 normal。

**是否属于 A 类**：只有第 2 点属于输出结构；第 1、3 点分别属于 C 类（过滤位置）与业务口径执行。

---

## B. 金额语义（E-0077 / E-0096 / E-0100）

### B0. 关键前置发现：三条不是同一个问题

| 题 | question 措辞 | Gold 金额字段 | pred 金额字段 | 真正原因 |
|---|---|---|---|---|
| E-0077 | 地区"非取消订单销售额" | **subtotal**（明细） | total_amount | schema_link 只给了 orders（无 order_items），模型用不了 subtotal |
| E-0096 | 月份"当月销售额" | **total_amount**（订单实付） | subtotal | Gold 用 total_amount，但 Prompt V1.3 规则对"销售额"默认 subtotal → 模型跟随规则用 subtotal 反而错 |
| E-0100 | 月份"非取消订单销售额" | **total_amount** | subtotal | 同上 |

**E-0077 的真正根因是 Schema Linking 覆盖不足**，不是金额语义：
- schema_link 表只有 `["orders"]`，columns（order_date/region/status/total_amount），**没有 order_items**；
- Generator 的硬性约束是"只能使用 Schema Linking 结果中提供的表和字段" → 模型无法引用 `order_items.subtotal`，只能在 orders 内选金额字段 → 用了 total_amount；
- Gold 用 subtotal 判定 → 金额不同 → mismatch。
- 也就是说：**这不是模型"不知道该选哪个字段"，而是上游没给它 subtotal 可用的路径**。Few-shot 即使示范 subtotal，模型因硬约束也用不了。
- 附加因素：检索到的 few-shot ex_005/ex_015/ex_009 恰都是 total_amount 类示范（上个月各地区销售额/月度趋势/平均订单金额都用 total_amount），对金额口径自我一致，无矛盾，但也不含 subtotal 正例 → 无帮助。

**E-0096 / E-0100 的真正根因是 Gold 与 Prompt 的业务规则冲突**：
- Prompt V1.3 金额口径唯一权威：「未特别注明'实付'的『销售额』一律用 subtotal」；而 E-0096/E-0100 的题面"销售额"未注明实付，**模型按 Prompt 正确使用了 subtotal**；
- 但 Gold 使用 total_amount（订单实付）→ 模型遵守正式规则反而被判错。
- 这不是模型缺陷，是 **Benchmark Gold 与正式 Prompt 规则不一致**（E-0096/E-0100 的 Gold 口径与 V1.3 "唯一权威"规则冲突）。
- 轮数观察：ex_015（月份销售趋势）也用 total_amount —— few-shot 与 Gold 方向一致，与 Prompt 冲突 → 三方（Prompt / Few-shot / Gold）在"月份销售额"上口径不一致。

**Metric Semantic Selection Failure 判断**：
- 不能定义为一个统一系统问题。三者成因互不相同：
  - E-0077：Schema Linking（缺表）→ 非文本层可修；
  - E-0096/E-0100：Benchmark Gold 口径与 Prompt 规则冲突 → 只能通过"基准口径仲裁"解决，不能用文本规则/few-shot 掩盖（因为那会破坏与其他 98 题的 Prompt 一致性）。
- **结论**：E-0077 与 E-0096/E-0100 都不属于"Few-shot 能稳定修复的 Metric Semantics"范畴。任何"金额字段选择"规则或示范都无法同时满足：对 E-0096/100 要求 total_amount 就会破坏 E-0077 需要的 subtotal 路径（且 E-0077 根本不是字段选择错误）。

### B1. Few-shot 内部一致性补充观察
- 正式 23 条内，subtotal 类示范：ex_001/ex_003/ex_019/ex_022（商品/类目/销售额）用 subtotal；total_amount 类示范：ex_005/ex_009/ex_010/ex_015（地区/平均/用户消费/月度趋势）用 total_amount。两类并存本身不矛盾（字段语义不同场景），但**"月份销售额"这一格：ex_015 用 total_amount 而 E-0096/E-0100 Gold 也用 total_amount，Prompt 却规定 subtotal** → 需要基准口径仲裁。

---

## C. 聚合与查询结构（E-0057 / E-0086 / E-0095）

### C1. E-0086：订单级金额 × 明细行 → fan-out 放大（半个 J 你也逃不掉）

**证据**：gold 双 CTE（user_orders 订单粒度 + user_sku 明细粒度，JOIN 维度键）；pred 单 CTE 直连 users×orders×order_items，`SUM(o.total_amount)` 被每行明细重复累计 → 黄冬梅 total_spent=369854.65（gold 89397.46，放大 4.1×）；订单数/商品种数用 COUNT DISTINCT 正确（10/31 与 gold 一致），**只有金额被放大**。

**判定**：经典的 **JOIN fan-out**。属于"两阶段聚合/粒度分离"能力缺失：用户先订单粒度聚合金额，再与明细粒度指标 JOIN。这是一个真实的、频率最高的结构性失败（Task 14 归因同见 wrong 用户均值/grain 类）。

### C2. E-0095：第二层平均基准口径错误 + 显式阈值遗漏

**证据**：题面显式阈值"销售金额高于30000元"且"高于该地区各组合的平均销售金额"：
- gold：`pair_sales` CTE 内 `HAVING SUM>30000` **前置过滤**，再对达标组合按地区求 AVG 作第二层基准；
- pred：CTE **无 30000 过滤**，直接对全组合按地区求 AVG → 平均基准被低值组合拉低 → 多放行"山东_家用电器 72746.95"（gold 不包含）→ 多 1 行。
- 注意 pred 的 `WHERE ... o.order_date BETWEEN '2026-08-14'...` 时间窗正确，说明不是全局过滤失败，而是**第二层聚合的"基准集合"错误**（阈值过滤应前置）。

**判定**：属于 **filter placement / 两阶段聚合基准口径**，与 E-0086 相邻但不相同：E-0086 是一对多 join 放大，E-0095 是第二层 AVG 的分母集合错误。二者共同能力 = "先确定每层聚合的统计窗口/过滤集合，再做第二层"。

### C3. E-0057：CASE 分桶边界（下界 0 落入 ELSE）+ 实体错位

**证据**：题面"按用户累计下单次数分三档（1-3/4-10/11+）"：
- gold：`FROM orders` 出发（只统计有订单的用户），CASE `cnt<=3 / <=10 / ELSE`；
- pred：`users LEFT JOIN orders`（补 0 订单用户 17 人），CASE `BETWEEN 1-3 / 4-10 / ELSE` → **0 单用户落入 ELSE（11单及以上）**，导致 36 vs 19，且包含无订单用户（490+1474+36=2000 全量用户，gold 1983）。
- 两个偏差：①统计实体（有订单用户 vs 全用户）；②CASE 下界（BETWEEN 1-3 把 0 漏到 ELSE）。

**判定**：CASE 边界（下界）属于 Task 14.2 E7 范畴（已证纯规则无效）；同时掺有"统计实体/驱动表"选择错误。归类为 **case boundary + 实体选择**。它不是高清的单一"聚合粒度"问题 —— 更接近"边界语义"。

### C 类总结论
- E-0086 = JOIN fan-out（两阶段粒度分离）；
- E-0095 = 第二层 AVG 分母集合（过滤前置）；
- E-0057 = CASE 边界 + 实体选择。
- **三者不是同一种 failure**。把它们合叫"Structural SQL Reasoning Failure"会掩盖三种不同的可教能力。建议拆分为：`aggregation_grain（两阶段）`、`filter_placement（第二层基准）`、`case_boundary + entity_selection`。

---

## D. Repair（E-0099）

**证据**：
- initial（生成）：`SELECT r.region, ... FROM region_sales rs JOIN ...` —— SQL 内引用别名 `r.region`，但 CTE `region_sales` 的别名是 `rs`，随后还存在 `ras`/`par` 两个别名；生成 SQL 中 SELECT 用 `r.region`，WHERE 用 `rs.total_sales`/`ras`/`par` 混合 → `r` 未定义。
- sql_execute：报 `no such column: r.region`（SQLite 在解析阶段报列不存在）。
- sql_repair：尝试修复但上图报错 → repair 也失败（"Repair SQL 引用了不存在的字段: rs.region"——加注：repair 生成的 SQL 继续引用不存在的字段），最终 exec=False。

**分析**：
1. 原始 SQL 为什么错误：生成器在 CTE 多别名场景下别名不一致（SELECT 用 r，FROM 用 rs）。这是生成阶段的**别名引用 bug**，非业务逻辑错误。
2. 是否易被 SQLGlot 静态检查发现：**是**。SQLGlot 解析后，只需对 SELECT 投影的列限定符做"已定义别名集合"校验：`r` 不在 FROM/JOIN/CTE 别名集合 → 立即报错。这是纯语法层（不需要元数据）可拦截的结构错误 → **E8 Output Shape/引用校验的可行子集**。
3. Repair 为什么没修掉：repair 仍引用了不存在的字段（rs 在中间产物中不再可用/未正确限定），且 repair 流程没有"列引用存活性"校验 → 需要 repair 前也做同样的静态引用校验。
4. 是生成问题、校验问题还是 Repair 问题：生成 bug + 校验/Repair 二者都未拦截 → **生成问题和校验缺口**。

**是否值得专门立项**：单例（1/100）。
- 若只修 E-0099：不建议直接改 Repair 主流程（改流程风险大、收益 1 例）。
- **建议判断：`continue_observe`（继续观察）**。将"列/别名引用静态校验"作为 E8 的一个低成本功能点（不碰 Repair 主流程，只在 Safety/前置校验阶段加一层只读过滤），若后续该 pattern 重现（超过 1 例）再升级为专项。

---

## E. 系统问题归类总表（核心输出）

| 组 | 系统问题 | 题目 | 数量 | 是否文本层(Few-shot/Prompt)可修 | 是哪种 automation 更合适 |
|---|---|---|---|---|---|
| A1 | 输出列契约（label+value 多列） | E-0082, E-0083 | 2 | 部分（示范型 Few-shot） | Few-shot（能力示范）或 E8 形状校验 |
| A2 | 过滤遗漏 + 结构总数列 | E-0090 | 1 | 部分 | Few-shot（示范）+ 需同时示范过滤前置 |
| C1 | JOIN fan-out / 两阶段聚合粒度 | E-0086 | 1 | 是（示范型 Few-shot） | Few-shot（结构示范） |
| C2 | 第二层 AVG 基准集合（过滤前置） | E-0095 | 1 | 是（示范型 Few-shot） | Few-shot（结构示范） |
| C3 | CASE 边界 + 实体选择 | E-0057 | 1 | 弱 | 低优先 / continue_observe |
| B1 | Schema Linking 缺表（orders 无 order_items） | E-0077 | 1 | **否（上游输入）** | Schema Linking 覆盖（另一个实验域） |
| B2 | Gold 金额口径与正式 Prompt 冲突 | E-0096, E-0100 | 2 | **否（基准口径仲裁）** | Benchmark 口径审议（非文本层） |
| D | 别名引用 bug | E-0099 | 1 | 否 | E8 静态校验子集（低成本） |

**关键结论**：
1. **真正可被"示范型 Few-shot"修复的 target = E-0082/E-0083/E-0086/E-0095（+E-0090 输出列部分）**（约 5~6 例的可修复子集）；
2. E-0077 / E-0096 / E-0100 / E-0057 是**非本轮优化可达**（基准口径/上游输入/低价值单例），不应作为 Few-shot/Prompt/Validator 优化目标；
3. E-0099 可作为 E8 静态校验的零成本附带验证点。