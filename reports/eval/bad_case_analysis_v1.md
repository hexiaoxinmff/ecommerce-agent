# ECO-SQL-Bench · Bad Case 分析 v1（Baseline 28 条）

> 分析对象：Task 13 Baseline（run_id=20260915_41066）的 28 个 `result_mismatch` Bad Case（B-1008~B-1035）。
> 数据来源：`data/eval/bad_cases/*.json` + gold/pred SQL 逐字对比（`data/eval/error_taxonomy_v1.json`）。

---

## 1. Failure Type Pareto

| failure_type | count | pct | 累计 |
|---|--:|--:|--:|
| wrong_cancelled（结构统计误加取消过滤 / 含 1 条复合） | 13 | 46.4% | 46.4% |
| enum_hallucination（状态/地区枚举值幻想） | 4 | 14.3% | 60.7% |
| wrong_amount_field（subtotal vs total_amount / price vs unit_price） | 3 | 10.7% | 71.4% |
| wrong_avg_granularity（用户平均累计消费的聚合层级） | 2 | 7.1% | 78.6% |
| wrong_ratio_denominator（占比分母口径/窗口） | 2 | 7.1% | 85.7% |
| wrong_date_group（季度 strftime %Q 非法） | 1 | 3.6% | 89.3% |
| wrong_daily_avg（日均=固定天数 vs 实际天数） | 1 | 3.6% | 92.9% |
| wrong_context_filter（漏 HAVING>30000 前提） | 1 | 3.6% | 96.4% |
| wrong_join_granularity（分组键未含展示列/分区不一致） | 1 | 3.6% | 100.0% |

**前 3 类（wrong_cancelled + enum_hallucination + wrong_amount_field）解释了 71.4% 的错误** —— 全部属于「业务口径 / 枚举 / 金额字段语义」类，可归因到 **SQL Generator Prompt 的业务语义规则不足**。

---

## 2. 逐条 Root Cause（eval_id → failure_type → root_cause → candidate_fix）

| eval_id | diff | failure_type | root_cause | candidate_fix |
|---|---|--|---|---|
| E-0014 | medium | wrong_cancelled | 2024-06 订单数（结构统计）误加 cancelled | 结构统计不排除取消；销售额/销量才排除 |
| E-0022 | easy | wrong_cancelled | 2025 全年订单数误加 cancelled | 同上 |
| E-0047 | medium | wrong_cancelled | 年度订单量误加 cancelled | 同上 |
| E-0048 | medium | wrong_cancelled | 各月订单量误加 cancelled | 同上 |
| E-0049 | medium | wrong_cancelled | 季度订单量误加 cancelled | 同上 |
| E-0050 | medium | wrong_cancelled | 工作日/周末订单量误加 cancelled | 同上 |
| E-0051 | medium | wrong_cancelled | 地区订单量分布误加 cancelled | 同上 |
| E-0053 | medium | wrong_cancelled | 区域订单量 Top5 误加 cancelled | 同上 |
| E-0057 | hard | wrong_cancelled + join_dup | 用户订单档位用 cancelled 过滤 + LEFT JOIN 误计无订单用户 | 结构统计 + 用户订单数 JOIN 粒度 |
| E-0072 | hard | wrong_cancelled | 月均订单量误加 cancelled | 结构统计口径 |
| E-0075 | hard | wrong_cancelled | 上下半年订单量比误加 cancelled | 结构统计口径 |
| E-0076 | hard | wrong_cancelled | 地区订单占比分子/分母误加 cancelled | 结构统计 + 分母同口径 |
| E-0090 | extra | wrong_cancelled | 高/低金额档位统计未排 cancelled（需金额口径） | 金额口径排取消 + 结构统计总数含取消 |
| E-0034 | medium | enum_hallucination | products.status 写成 'active'（应为 on_sale） | 状态枚举提示 |
| E-0038 | medium | enum_hallucination | status='active' + 缺 MAX/GROUP BY | 状态枚举 + 全量 MAX |
| E-0002 | easy | enum_hallucination | '广东省' 而非 '广东'（enum 值幻想） | 地区枚举原值 |
| E-0081 | hard | enum_hallucination | '广东省' 而非 '广东' | 地区枚举原值 |
| E-0077 | hard | wrong_amount_field | 商品销售金额应 subtotal，用 total_amount | 金额字段语义 |
| E-0097 | extra | wrong_amount_field | 商品销售金额应 subtotal，用 total_amount | 金额字段语义 |
| E-0054 | medium | wrong_amount_field | 平均售价应 products.price，用 order_items.unit_price | price vs unit_price |
| E-0056 | hard | wrong_avg_granularity | 用户平均累计消费应两阶段，用订单均值×3 | 用户维度均值两阶段聚合 |
| E-0086 | extra | wrong_avg_granularity | 类似 E-0056（2 倍基准） | 同上 |
| E-0082 | hard | wrong_ratio_denominator | 占比分母窗口/口径（少输出 name 列） | 分子分母同口径 + 输出列齐 |
| E-0083 | hard | wrong_ratio_denominator | 分母未限「当季非取消」窗口 | 比例题窗口严格对应 |
| E-0066 | hard | wrong_date_group | strftime('%Y-Q%Q') 非法（SQLite 无 %Q） | 季度用 substr/CASE |
| E-0073 | hard | wrong_daily_avg | 日均= /90，应 /COUNT(DISTINCT 日期) | 日均分母=实际有单天数 |
| E-0095 | extra | wrong_context_filter | 漏 Gold 的 HAVING SUM>30000 前提 | 显式阈值入 SQL |
| E-0098 | extra | wrong_join_granularity | 分组键未含 name / 分区与输出一致性 | 分组含展示列 |

---

## 3. 按 Difficulty

| difficulty | EX | bad_case 数 | 主要失败类型 |
|---|---:|---:|---|
| easy | 88.0% | 3 | enum_hallucination（E-0002）、wrong_cancelled（E-0014/22） |
| medium | 70.0% | 9 | wrong_cancelled（5）+ enum_hallucination（2）+ wrong_amount_field（1） |
| hard | 63.33% | 11 | wrong_cancelled（3）+ wrong_amount_field（2）+ ratio/avg/date 各 1~2 |
| extra_hard | 66.67% | 5 | wrong_avg_granularity（2）+ amount/context/join 各 1 |

**hard 最需优化**（EX 63.33 最低，11 个 bad cases 最大）；easy 的错误集中在枚举幻想（简单题更依赖值精确记忆）。

---

## 4. 按 Operator（重点，Baseline EX%）

| operator | EX% | 说明 |
|---|---:|---|
| subquery | 58.06% | 低：半数集中在用户均值两阶段（E-0056/86） |
| case_when | 50.0% | 低：季度 CASE（E-0049 结构对但口径错）、分层 CASE（E-0057） |
| nested_subquery | 50.0% | 与 subquery 同源问题 |
| date_group | 60.0% | 季度分组 %Q 非法（E-0066） |
| date_filter | 61.54% | 与结构统计/窗口相关 |
| ratio | 64.29% | 分母口径（E-0082/83） |
| comparison_to_average | 64.29% | 聚合粒度（E-0056/86） |
| having | 64.71% | 前提过滤（E-0095） |

> 这些 operator 的 EX 全部低于总体 72%，与 §11 Pareto 一致：**问题本质是口径/枚举/字段语义，而非 SQL 结构生成能力**。

---

## 5. 优化方向结论

1. **E1（必做）**：SQL Generator Prompt 增强业务口径规则——重点：
   - 结构统计（订单数/状态分布/各地区订单量等）不排除 cancelled；
   - 销售额/销量/客单价才排除 cancelled；
   - 金额字段：订单实付=total_amount、明细金额=subtotal、商品售价=price、成交价=unit_price、数量=quantity；
   - 枚举精确值：on_sale/off_sale、active/inactive、15 个省级地区全名；
   - 用户维度均值 = 两阶段聚合（先按用户 GROUP BY 再 AVG）；
   - 日均分母 = COUNT(DISTINCT 日期)。
2. **E2（依据 E1 结果决定）**：Few-shot 是否缺 用户两阶段聚合 / 季度 CASE / 占比窗口示例（当前 18 条）。
3. **E3（暂缓）**：schema_mislink / wrong_table / wrong_column 在本批 28 条中为 0，Schema Linking 不是本轮主要瓶颈。

*本分析基于 Baseline 一次运行；Mimo 有随机性，优化效果以 E1 完整 100 条回归为准。*