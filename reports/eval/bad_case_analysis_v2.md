# ECO-SQL-Bench · Bad Case 分析 v2（Task 14.3 统一归因）

> 对象：Baseline（run 20260915_41066）28 个 `result_mismatch`（B-1008~B-1035）。
> 相对 v1（bad_case_analysis_v1.md）修正：
> 1. E-0082 / E-0083 / E-0090 统一归为 `wrong_output_shape`（SELECT 输出列不完整，按 spec §D1 判错）；
>    v1 的 `wrong_ratio_denominator` 为误判（这些题分子分母实际正确，问题在少输出列）；
> 2. E-0097 根因统一表述为 `wrong_amount_field`（subtotal vs total_amount），
>    「订单数需 COUNT(DISTINCT o.id)」仅为次因，不再单列错误根因；
> 3. E-0098 标记 `ranking_tie_risk`（ROW_NUMBER 并列无稳定 tiebreaker → 结果非确定性；
>    Task 14.3 已为 Gold 增加 `ORDER BY sold DESC, p.id` tiebreaker 修复）；
> 4. 枚举不含复合字符串（v1 的 `wrong_cancelled + join_duplication` 已拆分）。

## 1. Failure Type Pareto（v2）

| failure_type | count | pct | 说明 |
|---|--:|--:|---|
| wrong_cancelled | 12 | 42.9% | 结构统计误加取消过滤 |
| enum_hallucination | 4 | 14.3% | 枚举值幻想 |
| wrong_amount_field | 3 | 10.7% | subtotal/total_amount/price/unit_price 选错 |
| wrong_output_shape | 3 | 10.7% | SELECT 输出列不完整（§D1） |
| wrong_avg_granularity | 2 | 7.1% | 两阶段聚合粒度错误 |
| wrong_date_group | 1 | 3.6% | strftime %Q 等非法格式 |
| wrong_daily_avg | 1 | 3.6% | 日均分母用固定天数 |
| wrong_context_filter | 1 | 3.6% | 遗漏 HAVING>30000 前置过滤 |
| ranking_tie_risk | 1 | 3.6% | 排名并列无 tiebreaker |

## 2. 逐条归因（v2）

| eval | difficulty | failure_type | root_cause |
|---|---|---|---|
| E-0002 | easy | enum_hallucination | region 用 '广东省'（库内为 '广东'）→ COUNT=0 |
| E-0014 | easy | wrong_cancelled | 2024-06 订单数（结构统计）误加 cancelled |
| E-0022 | easy | wrong_cancelled | 2025 全年订单数误加 cancelled |
| E-0034 | medium | enum_hallucination | products.status 用 'active'（应为 on_sale） |
| E-0038 | medium | enum_hallucination | status='active' + 缺 MAX/GROUP BY |
| E-0047 | medium | wrong_cancelled | 年度订单量误加 cancelled |
| E-0048 | medium | wrong_cancelled | 各月订单量误加 cancelled |
| E-0049 | medium | wrong_cancelled | 季度订单量误加 cancelled |
| E-0050 | medium | wrong_cancelled | 工作日/周末订单量误加 cancelled |
| E-0051 | medium | wrong_cancelled | 地区订单量分布误加 cancelled |
| E-0053 | medium | wrong_cancelled | 区域订单量 Top5 误加 cancelled |
| E-0054 | medium | wrong_amount_field | 「平均售价」用 unit_price（应为 products.price） |
| E-0056 | hard | wrong_avg_granularity | 用户平均累计消费用订单均值（应两阶段） |
| E-0057 | hard | wrong_cancelled | 用户订单档位用 cancelled 过滤 + LEFT JOIN 误计无订单用户 |
| E-0066 | hard | wrong_date_group | 季度用 strftime('%Y-Q%Q')（SQLite 无 %Q） |
| E-0072 | hard | wrong_cancelled | 月均订单量误加 cancelled |
| E-0073 | hard | wrong_daily_avg | 日均分母 /90（应 /COUNT(DISTINCT 日期)） |
| E-0075 | hard | wrong_cancelled | 上下半年订单量比误加 cancelled |
| E-0076 | hard | wrong_cancelled | 地区订单占比分子分母误加 cancelled |
| E-0077 | hard | wrong_amount_field | 商品销售金额用 total_amount（应为 subtotal） |
| E-0081 | hard | enum_hallucination | region 用 '广东省' |
| E-0082 | hard | wrong_output_shape | 占比题只输出 1 列（缺 c.name 列，gold 2 列） |
| E-0083 | hard | wrong_output_shape | 同 E-0082（gold 2 列 vs pred 1 列） |
| E-0086 | extra_hard | wrong_avg_granularity | 用户均值两阶段 + 订单数 COUNT 未去重（fan-out） |
| E-0090 | extra_hard | wrong_output_shape | 缺 total_cnt 列（gold 4 列 vs pred 3 列） |
| E-0095 | extra_hard | wrong_context_filter | 遗漏 HAVING SUM>30000 前置过滤（题面未说明，v1.1 已补题面） |
| E-0097 | extra_hard | wrong_amount_field | 商品销售金额用 total_amount（应为 subtotal） |
| E-0098 | extra_hard | ranking_tie_risk | ROW_NUMBER 并列无 tiebreaker，结果非确定 |

## 3. 与 Task 14.3 修复的对应

| 修复项 | 覆盖 Bad Case |
|---|---|
| E-0086 Gold 修复（fan-out） | E-0086（新 Gold 46 行，金额/订单数/SKU 与真实一致） |
| E-0095 题面补 30000 | E-0095（题面/Gold 对齐，Gold 不变） |
| E-0098 Gold 加 tiebreaker | E-0098（ORDER BY sold DESC, p.id） |
| Prompt V1.3 口径统一 | wrong_amount_field / wrong_cancelled 类 |
| Prompt V1.3 枚举分表 | enum_hallucination 类 |

*本归因基于 Baseline Pred SQL 与 Gold SQL 事后对比；v1.0 历史归因保留在 bad_case_analysis_v1.md，未覆盖。*