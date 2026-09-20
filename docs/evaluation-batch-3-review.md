# ECO-SQL-Bench · Task 12 Batch 3 审核报告（Hard 30 条）

> 批次：E-0056 ~ E-0085（difficulty=hard，multi_turn=null，expected_behavior=answer）
> 日期：2026-09-15
> 生成器：`scripts/validate_eval_batch.py`（复用 `validate_eval_dataset.py` 冻结校验/hash 实现；Hard 目标由 draft 内置 `operator_targets` 控制）
> 数据库：`db/ecommerce.db`（database_version=dev-2026-09-14，seed=20260914，schema_version=1.0）
> 状态：**30/30 审核通过（review_status = approved）**，已正式入集（与 Easy 25 + Medium 30 合并共 85 条），待总顾问复核

---

## 1. 批次概况

| 项 | 值 |
|---|---|
| 最终正式题 | 30（E-0056~E-0085） |
| 候选池总量 | 42（30 正式候选 + 12 备选池 D-0020~D-0031） |
| 淘汰/未采用 | 12（备选池：保留备选，不入正式集，见 §7） |
| 难度 | 全部 hard |
| expected_behavior | 全部 answer |
| expected_empty | 全部 false（30 题均有真实非空结果） |
| Hard 禁止项 | nested_subquery = 0 / conditional_aggregation = 0 |

## 2. 生成与审核闭环（30/30 全部走完）

```text
按矩阵 §7.2/§7.3 设计（场景配额固定、禁止项硬边界）
  → 候选 Gold SQL（多表 JOIN / CTE / 相关子查询 / ratio / 多维分组）
  → SQL Safety Validator（check_sql_safety + SchemaCatalog）
  → SQLite 只读执行（db/ecommerce.db）
  → 结果人工核验（行数 / 聚合粒度 / 边界并列 / 比例分子分母 / 口径）
  → gold_result_hash（normalize_result_hash）
  → 完全重复 + 规范化重复检测
  → 矩阵覆盖复核（场景配额 + operator 最低目标，含 Hard 行 16 项）
  → 入集（与 E-0001~E-0055 合并，hash 校验 85/85）
```

## 3. 逐条审核表（review_status = approved）

> gold_result 为真实库只读执行结果；hash 已重跑核对一致（--verify-hashes 85/85 无漂移）。

| ID | question 摘要 | scenario | operators | gold_result | gold_result_hash[12] | review_notes |
|---|---|---|---|---|---|---|
| E-0056 | 累计消费>用户均值3倍的用户 | user_analysis | join,where,group_by,having,aggregate,subquery,comparison_to_average,order_by | 43 行（宋嘉琪 92043.83 … 冯国栋 48260.22） | `8cf160ddd15e` | CTE 用户累计消费+HAVING 与均值3倍比较；total_amount 排除 cancelled |
| E-0057 | 用户下单档位（1-3/4-10/11+）分布 | user_analysis | subquery,case_when,group_by,aggregate | 3 行（490/1474/19） | `80dd214e24cc` | 派生表+ CASE WHEN 分层；订单数结构统计 |
| E-0058 | 在售均价>平台均价分类 | product_analysis | join,where,group_by,having,aggregate,subquery,comparison_to_average,order_by,limit | 5 行（家用电器 2741.07 …） | `1653ebb10032` | 与全平台均价比较；实际达标分类恰 5 个 |
| E-0059 | 非取消销量 Top5 商品 | product_analysis | multiple_join,join,where,group_by,aggregate,order_by,limit,top_n | 5 行（美的婴儿纸尿裤Max 130 …） | `c16a40884bc7` | 三表 JOIN 多表链；SUM(quantity) 排除 cancelled；Top-5 边界无并列 |
| E-0060 | 分类内价格>分类均价的款数≥2 | product_analysis | join,where,group_by,having,aggregate,subquery,comparison_to_average,order_by | 22 行（家用电器 15 …） | `89d8d3006779` | 相关子查询（分类内均价）作基准，HAVING 过滤 |
| E-0061 | 销售金额>分类均值分类 | category_analysis | multiple_join,join,where,group_by,aggregate,subquery,comparison_to_average,order_by | 5 行（家用电器 8290243.71 …） | `169f7fc8d5ab` | 四表 JOIN+CTE 聚合与分类均值比较；subtotal 口径 |
| E-0062 | 2025 分类销售 Top5 | category_analysis | multiple_join,join,where,date_filter,group_by,aggregate,order_by,limit,top_n | 5 行（家用电器 3279939.24 …） | `03c576689cf6` | 四表 JOIN+年度窗+Top-5；subtotal 排除 cancelled |
| E-0063 | 分类均价<平台均价一半 | category_analysis | join,group_by,having,aggregate,subquery,comparison_to_average,order_by | 13 行（洗护清洁 77.63 …） | `3abca098caae` | HAVING AVG 与均值一半比较，低价类识别 |
| E-0064 | 2025 各状态订单数+占比 | order_analysis | where,date_filter,group_by,aggregate,ratio,subquery,order_by | 5 行（completed 2434：60.65% …） | `a71d8a8ee3a7` | 状态结构统计+占比（标量子查询分母） |
| E-0065 | 2026 金额>全库均值订单数 | order_analysis | where,date_filter,aggregate,subquery,comparison_to_average | 1 行（1236） | `b87c2c9b9beb` | 与整体订单均值比较+时间窗+取消排除 |
| E-0066 | 2025 季度×状态销售额 | sales_analysis | where,date_filter,case_when,date_group,group_by,aggregate,multi_dimension_grouping,order_by | 16 行（Q1-completed 1551333.95 …） | `11c68d575327` | 季度×状态双维分组+CASE WHEN；double 维度细分 |
| E-0067 | 近90天地区×类别销售 Top8 | sales_analysis | multiple_join,join,where,date_filter,group_by,aggregate,multi_dimension_grouping,order_by,limit,top_n | 8 行（广东-电脑办公 220057.31 …） | `eaf133a7132c` | 四表 JOIN+90天窗+地区×分类多维分组+Top-8 |
| E-0068 | 客单价>全库均值地区 | sales_analysis | where,group_by,having,aggregate,subquery,comparison_to_average,order_by | 6 行（四川 3691.05 … 陕西 3350.54） | `685e40458310` | HAVING AVG 与整体均值比较；total_amount 排除 cancelled |
| E-0069 | 各年度销售额+占总比 | sales_analysis | where,date_group,group_by,aggregate,ratio,subquery,order_by | 3 行（2024 5369282.92：16.93% …） | `6772af37fe58` | 年度分组+销售额占比 ratio（子查询分母） |
| E-0070 | 2026 月销售额>100万 | sales_analysis | where,date_filter,date_group,group_by,having,aggregate,order_by | 8 行（2026-08 2206807.1 …） | `93c73502d1d3` | 月份分组+HAVING 金额阈值 |
| E-0071 | 2025 月×状态订单数 | time_analysis | where,date_filter,date_group,group_by,aggregate,multi_dimension_grouping,order_by | 60 行（2025-01-cancelled 15 …） | `94886d592158` | 月份×状态双维分组；订单结构统计 |
| E-0072 | 2025 月订单>月均的月份 | time_analysis | where,date_filter,date_group,group_by,having,aggregate,subquery | 7 行（2025-12 475 …） | `be3db8772a15` | HAVING 与月均标量子查询比较 |
| E-0073 | 近90天分类日均销售 Top5 | time_analysis | multiple_join,join,where,date_filter,group_by,aggregate,date_group,order_by,limit,top_n | 5 行（家用电器 18206.33 …） | `bc51ab9ba856` | 四表 JOIN+日均额(SUM/COUNT DISTINCT 日)+Top-5 |
| E-0074 | 2025 Q4 分类销量 Top3 | time_analysis | multiple_join,join,where,date_filter,group_by,aggregate,order_by,limit,top_n | 3 行（家用电器 404 …） | `45ca285fa3a2` | 四表 JOIN+季度窗+销量 Top-3 |
| E-0075 | 2026 下半年/上半年订单比 | time_analysis | where,date_filter,aggregate,ratio,subquery | 1 行（0.48） | `f1e450083cde` | 半年对比 ratio（双时间窗子查询） |
| E-0076 | 订单 Top5 地区及占比 | regional_analysis | group_by,aggregate,order_by,limit,top_n,ratio,subquery | 5 行（广东 1315：13.15% …） | `afee0c55d9c5` | 地区占比 ratio+Top-5 |
| E-0077 | 2025 地区销售额>地区均值 | regional_analysis | join,where,date_filter,group_by,having,aggregate,subquery,comparison_to_average,order_by | 7 行（广东 1690745.96 …） | `e451b1f8be83` | CTE 地区聚合与均值比较；subtotal 口径 |
| E-0078 | 跨区订单占比 | regional_analysis | join,where,aggregate,ratio,subquery | 1 行（28.03%） | `f2b50132c8a7` | 用户注册地区与收货地区不一致占比 |
| E-0079 | 2025 月销售额>月均月份 | ranking | where,date_filter,date_group,group_by,aggregate,subquery,comparison_to_average,order_by | 6 行（2025-12 1608091.51 …） | `252755e03150` | CTE 月销售额与月均比较（优于 Medium 的订单量 Top-N） |
| E-0080 | 近90天商品销售 Top5 | ranking | multiple_join,join,where,date_filter,group_by,aggregate,order_by,limit,top_n | 5 行（恒源祥笔记本 215080.82 …） | `9ea9497a7df6` | 三表 JOIN+90天窗+商品销售 Top-5 |
| E-0081 | 广东用户占比 | ratio | where,aggregate,ratio,subquery | 1 行（12.3%） | `fab14ecd0f64` | 单表占比：分子/分母明确（246/2000） |
| E-0082 | 休闲零食销售占总比 | ratio | multiple_join,join,where,group_by,aggregate,ratio,subquery | 1 行（0.81%） | `587371358c2b` | 类目销售占比，分子分母同口径 subtotal |
| E-0083 | 2025 Q4 家电销售占当季比 | ratio | multiple_join,join,where,date_filter,group_by,aggregate,ratio,subquery | 1 行（28.98%） | `7490d3a46660` | 季度窗内类目占比，分子分母同日窗同口径 |
| E-0084 | 2025 vs 2026 客单价对比 | comparison | where,date_filter,aggregate | 2 行（2025 3351.98 / 2026 …） | `1e2f2b036d5b` | 跨年客单价对比，AVG(total_amount) 分年度 |
| E-0085 | 男装 vs 女装销售额对比 | comparison | multiple_join,join,where,group_by,aggregate,order_by | 2 行（男装 812746.38 …） | `84f560c7fa1f` | 四表 JOIN+分类对比（comparison 场景） |

**口径检查**：销售/金额/销量类（E-0056/59/61/62/66/67/69/70/73/74/77/80/82/83/85）全部排除 `cancelled`；订单级金额用 `orders.total_amount`（E-0056/65/66/68/69/70/79/84），明细/销量/类目占比用 `order_items.subtotal/quantity`（E-0059/61/62/67/73/74/77/80/82/83/85），字段选择均与题目语义严格一致；订单数/状态分布类（E-0057/64/71/75/76）为结构统计不排除取消；ratio 分子分母口径逐条人工核对（E-0064/69/75/76/78/81/82/83），未发生 JOIN 膨胀。

## 4. 去重检查

| 类型 | 结果 |
|---|---|
| 完全重复（exact duplicate） | 0 |
| 规范化重复（normalized duplicate） | 0 |
| 跨批重复（与 E-0001~E-0055 规范化比对） | 0（85 条 question 扫描无重复） |
| 模板重复 | 0 |

**跨批模板核查**：
- E-0059（销量 Top5 商品）vs Medium E-0034（在售价格 Top5 商品）：聚合维度不同（销量 vs 价格），三表多 JOIN，非换皮；
- E-0073（近90天分类日均额 vs E-0048 月订单 Top5）：指标（日均销售额 vs 订单量）、结构（COUNT DISTINCT 日期除法 vs 简单 Top）均不同；
- E-0079（月销售额>月均）vs E-0048（月订单 Top5）：比较型 vs Top-N，结构完全不同；设计期已主动排除"2025 销售额 Top5 月"这一与 E-0048 同构的初始候选；
- E-0077（2025 地区销售额>均值）vs E-0052（销售额>200万地区）：一个 comparison_to_average 结构、一个固定阈值 HAVING，逻辑不同；
- E-0080（近90天商品销售 Top5）vs E-0073（近90天分类日均 Top5）：维度（商品 vs 分类）、指标（总销售 vs 日均）不同；
- E-0041 等 Batch 2 状态均值题与 E-0064 状态占比分布：聚合（AVG vs COUNT+pct）不同。

## 5. 矩阵覆盖复核

### 5.1 Difficulty × Scenario（对照 evaluation-matrix.md §7.2 Hard 行）

| scenario | 实际 | 目标 | 结果 |
|---|---:|---:|---|
| user_analysis | 2 | 2 | PASS |
| product_analysis | 3 | 3 | PASS |
| category_analysis | 3 | 3 | PASS |
| order_analysis | 2 | 2 | PASS |
| sales_analysis | 5 | 5 | PASS |
| time_analysis | 5 | 5 | PASS |
| regional_analysis | 3 | 3 | PASS |
| ranking | 2 | 2 | PASS |
| ratio | 3 | 3 | PASS |
| comparison | 2 | 2 | PASS |
| **合计** | **30** | **30** | **PASS** |

### 5.2 Difficulty × Operator（对照 evaluation-matrix.md §7.3 Hard 行）

| operator | 实际 | 目标（最低/范围） | 结果 |
|---|---:|---:|---|
| aggregate | 30 | ≥20 | PASS |
| where | 28 | ≥18 | PASS |
| group_by | 25 | ≥15 | PASS |
| order_by | 21 | ≥12 | PASS |
| limit | 8 | ≥8 | PASS |
| join | 16 | ≥15 | PASS |
| top_n | 7 | 4~8 | PASS |
| having | 8 | ≥8 | PASS |
| date_filter | 16 | ≥8 | PASS |
| date_group | 7 | ≥6 | PASS |
| ratio | 8 | ≥5 | PASS |
| case_when | 2 | 2~6 | PASS |
| subquery | 19 | ≥6 | PASS |
| multiple_join | 10 | ≥8 | PASS |
| comparison_to_average | 9 | 3~6 | PASS |
| multi_dimension_grouping | 3 | 3~6 | PASS |

### 5.3 Hard 禁止项（矩阵 §7.3 硬边界）

```text
nested_subquery = 0  conditional_aggregation = 0
```

### 5.4 题集整体（85 条）

- Easy 25 / Medium 30 / Hard 30 场景配额各自达标（§7.2 三行全部匹配）；
- 整体 Difficulty×Operator 覆盖随批次推进逐次收紧，Hard 批后 Easy/Medium 既有条目与 hash 无任何改动。

## 6. Hard 质量检查（是否真正 Hard）

对 30 题逐题对照 §6 分级规则与 §7 禁止"Medium 换皮"清单：

| 判定 | 数量 | 说明 |
|---|---:|---|
| 真正 Hard | **30** | 每题均含至少一项 Hard 级结构：四表 multiple_join（E-0062/67/73/74/85 等 10 题）、相关/标量子查询 comparison_to_average（E-0056/58/60/61/63/65/68/72/77/79 等 9 题）、ratio 占比（8 题）、多维分组（3 题）、跨主体 comparison（2 题）、HAVING 聚合过滤（8 题） |
| 疑似 Medium 换皮 | **0** | 设计期已淘汰的初稿：E-0059 Top-10→Top-5、E-0073 日粒度Top-N（与 E-0048 同构）、E-0079 月销售额Top5（与 E-0048 同构）、E-0056 固定阈值→均值3倍比较；每题均引入新业务逻辑或 SQL 结构 |

## 7. 备选池（12 条，未入正式集，原因）

| ID | question 摘要 | 未采用原因 |
|---|---|---|
| D-0020 | 2026 各月订单数 | 与 E-0071 同构（换年份） |
| D-0021 | 江苏用户占比 | 与 E-0081 同构（换地区） |
| D-0022 | 分类均价>平台均价 | 与 E-0058 高度接近（无在售条件） |
| D-0023 | 2024 分类销售 Top5 | 与 E-0062 同构（换年度） |
| D-0024 | 2025 地区订单 Top5 | 与 E-0076 同构（加年度窗） |
| D-0025 | 累计消费>6万用户 | 与 E-0056 同构（换阈值） |
| D-0026 | 男/女装商品数对比 | 弱于 E-0085（仅计数）；高仿模板 |
| D-0027 | 2025 Q1 家电占比 | 与 E-0083 同构（换季度） |
| D-0028 | 销量 Top10 分类 | 与 E-0059 同构（商品→分类维度） |
| D-0029 | 2026 状态金额+占比 | 与 E-0064 相近，可作候选但重叠 |
| D-0030 | 近90天订单 Top5 天 | 与 E-0073 初始版本同构（日粒度 Top-N） |
| D-0031 | 各地区销售额前15 | 与 Easy E-0042 同结构，Hard 价值弱 |

> 备选池保留于 `data/eval/drafts/hard_batch3_candidates.json` 的 `backups` 字段。

## 8. 校验结果

- `python scripts/validate_eval_dataset.py`：单轮 **85** 条（Easy 25 + Medium 30 + Hard 30），结构合法 + gold_sql 全部可只读执行，EXIT=0；
- `python scripts/validate_eval_dataset.py --verify-hashes`：**85/85** hash 重算一致（无漂移），EXIT=0；
- `python scripts/validate_eval_batch.py --drafts data/eval/drafts/hard_batch3_candidates.json`：30/30 通过 + 场景配额 + 16 项 operator 目标全达标，EXIT=0；
- `python scripts/validate_eval_batch.py ... --commit`：入集合并成功（85 条），EXIT=0；
- `pytest -q`：**315 passed**（新增 4 条 Batch 3 合同测试：Hard 禁止项 / ID 范围 / 场景配额 / 非"Medium 换皮"复杂能力判定）。

## 9. 数据库安全

- 全部 gold_sql 顶层 `SELECT/WITH`，`check_sql_safety` 只读校验通过（禁止写操作）；
- 连接 `mode=ro` + `PRAGMA query_only=ON`；数据库尺寸核验：users 2000 / categories 30 / products 500 / orders 10000 / order_items 30457，未变；seed=20260914、schema_version=1.0 未变；
- 历史 hash：E-0001（`2c041428…116e8`）等 25 条 Easy 与 30 条 Medium 全部与 Batch 1/2 审核记录一致。

## 10. 发现的问题 / 遗留

1. 85 条对 §7.4 题集级最低覆盖仍有缺口（Extra Hard 未生成，属规划内分批缺口）；
2. case_when=2 处于目标下界（2~6），Hard 内 CASE WHEN 场景覆盖偏紧——下批 Extra Hard 可再补充，当前不影响达标；
3. E-0057 的用户档位边界（≤3/≤10/>10）与 E-0039/E-0064 的状态枚举无重叠，语义独立；
4. E-0075（0.48：2026 下半年至今订单数仅上半年 0.48 倍）是数据事实（下半年数据截至 2026-09-12 未完整），notes 已注明业务解释；
5. `validate_eval_batch.py` 完全复用 Batch 2 的 `operator_targets` + 合并入集机制，无需额外改动。

## 11. 下一阶段

Task 12 Batch 4：E-0086 ~ E-0100（Extra Hard 15 条），复用本批 5 步闭环；启用嵌套子查询 / 条件聚合 / 复杂时间逻辑与多维组合。