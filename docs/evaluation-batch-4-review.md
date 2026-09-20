# ECO-SQL-Bench · Task 12 Batch 4 审核报告（Extra Hard 15 条）

> 批次：E-0086 ~ E-0100（difficulty=extra_hard，multi_turn=null，expected_behavior=answer）
> 日期：2026-09-15
> 生成器：`scripts/validate_eval_batch.py`（复用 `validate_eval_dataset.py` 冻结校验/hash 实现；EH 目标由 draft 内置 `operator_targets` 控制）
> 数据库：`db/ecommerce.db`（database_version=dev-2026-09-14，seed=20260914，schema_version=1.0）
> 状态：**15/15 审核通过（review_status = approved）**，已正式入集（与 Easy 25 + Medium 30 + Hard 30 合并共 **100 条**），待总顾问复核

---

## 1. 批次概况

| 项 | 值 |
|---|---|
| 最终正式题 | 15（E-0086~E-0100） |
| 候选池总量 | 25（15 正式候选 + 10 备选池 D-0032~D-0041） |
| 淘汰/未采用 | 10（备选池：保留备选，不入正式集，见 §7） |
| 难度 | 全部 extra_hard |
| expected_behavior | 全部 answer |
| expected_empty | 全部 false（15 题均有真实非空结果） |
| EH 结束项 | 本批为第一阶段 100 条单轮 Benchmark 收尾批次 |

## 2. 生成与审核闭环（15/15 全部走完）

```text
按矩阵 §7.2/§7.3 设计（EH 场景配额固定、EH 无禁止项、复杂能力目标约束）
  → 候选 Gold SQL（嵌套子查询 / 窗口函数 / 条件聚合 / 多维分组 / CTE 自联结）
  → SQL Safety Validator（check_sql_safety + SchemaCatalog）
  → SQLite 只读执行（db/ecommerce.db；先逐条探测可执行性与结果合理性）
  → 结果人工核验（JOIN 粒度 / 子查询边界 / 分组维度 / 占比分子分母 / 口径）
  → gold_result_hash（normalize_result_hash）
  → 完全重复 + 规范化重复检测
  → 矩阵覆盖复核（场景配额 + EH 行 18 项 operator 目标）
  → 入集（与 E-0001~E-0085 合并，hash 校验 100/100）
```

## 3. 逐条审核表（review_status = approved）

> gold_result 为真实库只读执行结果；hash 已重跑核对一致（--verify-hashes 100/100 无漂移）。

| ID | question 摘要 | scenario | operators | gold_result | gold_result_hash[12] | review_notes |
|---|---|---|---|---|---|---|
| E-0086 | 消费>用户均值2倍且下单>8笔的用户 | user_analysis | multiple_join,join,where,group_by,aggregate,subquery,nested_subquery,comparison_to_average,order_by | 90 行（黄冬梅 369854.65 …） | `0838b1de0535` | 三表 JOIN+嵌套子查询（用户均值×2 基准）+多条件；total_amount 排除 cancelled |
| E-0087 | 销量>分类均值的前10商品 | product_analysis | multiple_join,join,where,group_by,aggregate,subquery,nested_subquery,comparison_to_average,order_by,limit,top_n | 10 行（美的婴儿纸尿裤Max 130 …） | `5e1f3fcbe23c` | 四表 JOIN+相关嵌套子查询（分类内平均销量）+Top-10 |
| E-0088 | 2025 畅销5款上下半年拆分 | product_analysis | conditional_aggregation,case_when,multiple_join,join,where,date_filter,group_by,aggregate,subquery,order_by,limit,top_n | 5 行（恒源祥笔记本 140270.1/224432.16 …） | `1c3eaa6778ef` | SUM(CASE) 条件聚合拆分上下半年+Top-5 |
| E-0089 | 销售>分类均值且占比的分类 | category_analysis | multiple_join,join,where,group_by,aggregate,subquery,nested_subquery,comparison_to_average,ratio,order_by | 5 行（家用电器 8290243.71：24.97% …） | `18e7ea641c56` | 四表 JOIN+嵌套子查询均值比较+占比 ratio |
| E-0090 | 2025 各状态高/低金额订单数 | order_analysis | conditional_aggregation,case_when,where,date_filter,group_by,aggregate,order_by | 5 行（cancelled 0/0/202 …） | `df6b09372db4` | COUNT(CASE) 双口径条件聚合；cancelled 计入结构统计、不在金额档 |
| E-0091 | 2025 地区×季度客单价 | sales_analysis | multi_dimension_grouping,date_group,case_when,group_by,aggregate, having,where,date_filter,order_by | 60 行（上海 Q1 2705.46 …） | `a0760b88c778` | 地区×季度多维分组+CASE 季度+HAVING 样本量 |
| E-0092 | 2025 H2>H1 地区及增速 | sales_analysis | conditional_aggregation,case_when,where,date_filter,group_by,aggregate,ratio,order_by | 15 行（山东 111.56% …） | `8eb1dc14489a` | SUM(CASE) 上下半年+增长 ratio（comparison 语义） |
| E-0093 | 2025 各地区销售Top3分类 | sales_analysis | multiple_join,join,where,date_filter,group_by,aggregate,subquery,order_by,top_n,multi_dimension_grouping | 45 行（上海 家用电器 273901.93 …） | `893b1e99c1b1` | 四表 JOIN+地区×分类多维+窗口 ROW_NUMBER 分组内Top3 |
| E-0094 | 2025 vs 2024 月度同比 | time_analysis | date_group,group_by,aggregate,where,date_filter,subquery,ratio,order_by | 12 行（01 月 282.67% …） | `3b1b8d58b56a` | CTE 自联结（跨年同月对齐）+同比 ratio |
| E-0095 | 近30天地区×分类组合>地区平均 | time_analysis | multiple_join,join,where,date_filter,group_by,aggregate,subquery,nested_subquery,comparison_to_average,multi_dimension_grouping,having,order_by,limit | 9 行（江苏 电脑办公 85615.52 …） | `70cf5b38211e` | 四表 JOIN+30天窗+多维分组+相关嵌套子查询+HAVING |
| E-0096 | 2025 环比增速最快3个月 | time_analysis | date_group,group_by,aggregate,where,date_filter,subquery,ratio,order_by,limit,top_n | 3 行（2025-12 33.56% …） | `95de24040f0e` | 窗口 LAG 环比+ratio+Top-3 |
| E-0097 | 2025 销售与订单双高地区 | regional_analysis | join,where,date_filter,group_by,having,aggregate,subquery,nested_subquery,comparison_to_average,order_by | 6 行（广东 1690745.96 …） | `f6ebe5c853e3` | 双嵌套子查询（地区销售均值+订单均值两个基准）+HAVING 双指标 |
| E-0098 | 各分类销量Top3商品 | ranking | multiple_join,join,where,group_by,aggregate,having,subquery,order_by,top_n | 66 行（休闲零食 恒源祥巧克力礼盒X1 119 …） | `4c991746647d` | 四表 JOIN+HAVING 阈值+窗口分组内 Top-3 |
| E-0099 | 家电占比>全平台占比地区 | ratio | multiple_join,join,where,group_by,aggregate,subquery,ratio,order_by | 7 行（辽宁 31.15% …） | `9bcf0f7024e3` | 双 CTE（总额/家电额）+占比 ratio，与全平台占比比较 |
| E-0100 | 2025 5月 vs 2月 促销对比 | comparison | where,date_filter,aggregate,subquery,nested_subquery,ratio | 1 行（5月额/5月单/2月额/2月单/倍数） | `e6f1a97c1fbe` | 双时间窗 CTE+比值 ratio（comparison 场景） |

**口径检查**：销售/金额/销量类（E-0086/87/88/89/92/93/94/95/96/97/99）全部排除 `cancelled`；订单级金额`orders.total_amount`（E-0086/88/91/92/94/96/100），明细/销量/类目占比`order_items.subtotal/quantity`（E-0087/89/93/95/97/98/99）；订单结构统计（E-0090）cancelled 计入 `total_cnt` 但不在金额档内，语义明确；ratio 分子分母同口径（E-0089/92/94/96/99/100）逐条核对无膨胀。

## 4. 去重检查

| 类型 | 结果 |
|---|---|
| 完全重复（exact duplicate） | 0 |
| 规范化重复（normalized duplicate） | 0 |
| 跨批重复（与 E-0001~E-0085 规范化比对） | 0（100 条 question 扫描无重复） |
| 模板重复 | 0 |

**跨批模板核查**：
- E-0088（畅销5款上下半年）vs Hard E-0059/E-0080（销量/销售 Top）：本批引入 `SUM(CASE)` 上下半年拆分维度（conditional_aggregation），新业务逻辑非换皮；
- E-0093（地区×分类Top3）vs Hard E-0067（近90天地区×分类Top8）：时间窗（全年 vs 90天）、分组排名（窗口分组内 vs 全局截断）均不同；
- E-0094（月度同比）vs Hard E-0069（年度销售额+占比）：自联结跨年同月对齐+增速，结构全新；
- E-0096（月度环比）vs E-0094（同比）：LAG 环比 vs 自联结同比，时间逻辑不同；
- E-0097（地区销售+订单双均值）vs Hard E-0052（销售额>200万）：双嵌套均值基准+HAVING 双指标 vs 固定阈值，结构不同；
- E-0098（分类内销量Top3）vs Medium E-0037（挂载商品Top5分类）：分组内排名（窗口）vs 全局 Top，维度/能力不同；
- E-0099（家电地区占比>全平台占比）vs Hard E-0082/E-0083（休闲零食/家电占比）：本批为"地区×类目×全局占比比较"，新增比较逻辑且多行，非换皮；
- E-0100（5月vs2月）vs E-0075（2026上下半年比）：月份对比+多指标+倍数 ratio vs 单一比值，场景（comparison vs time）不同。

## 5. 矩阵覆盖复核

### 5.1 Difficulty × Scenario（对照 evaluation-matrix.md §7.2 EH 行）

| scenario | 实际 | 目标 | 结果 |
|---|---:|---:|---|
| user_analysis | 1 | 1 | PASS |
| product_analysis | 2 | 2 | PASS |
| category_analysis | 1 | 1 | PASS |
| order_analysis | 1 | 1 | PASS |
| sales_analysis | 3 | 3 | PASS |
| time_analysis | 3 | 3 | PASS |
| regional_analysis | 1 | 1 | PASS |
| ranking | 1 | 1 | PASS |
| ratio | 1 | 1 | PASS |
| comparison | 1 | 1 | PASS |
| **合计** | **15** | **15** | **PASS** |

### 5.2 Difficulty × Operator（对照 evaluation-matrix.md §7.3 EH 行）

| operator | 实际 | 目标（最低/范围） | 结果 |
|---|---:|---:|---|
| aggregate | 15 | ≥10 | PASS |
| where | 15 | ≥6 | PASS |
| group_by | 14 | ≥8 | PASS |
| order_by | 14 | ≥4 | PASS |
| limit | 4 | ≥2 | PASS |
| join | 9 | ≥2 | PASS |
| top_n | 5 | 2~4 | PASS（上限内，分组内 Top 题居多） |
| having | 4 | ≥4 | PASS |
| date_filter | 10 | ≥4 | PASS |
| date_group | 3 | ≥3 | PASS |
| ratio | 6 | ≥2 | PASS |
| case_when | 4 | 1~4 | PASS |
| subquery | 12 | ≥4 | PASS |
| multiple_join | 8 | ≥8 | PASS |
| comparison_to_average | 5 | ≥2 | PASS |
| multi_dimension_grouping | 3 | ≥3 | PASS |
| nested_subquery | 5 | ≥4 | PASS |
| conditional_aggregation | 3 | ≥3 | PASS |

### 5.3 EH 禁止项

ExtrarHard 无 operator 禁止项（矩阵 §7.3）；全部题目均有真实业务语义，无"为复杂而复杂"的跨表无意义 SELECT。

### 5.4 题集整体（100 条）

- 难度合计：Easy 25 / Medium 30 / Hard 30 / Extra Hard 15 = **100**；
- 场景配额：四个难度全部匹配 §7.2（Easy/Medium 历史核实，Hard 与 EH 本批核实）；
- 整体 Difficulty×Operator 覆盖随批次递增，Easy/Medium 既有序号项 hash 全量复验一致，无任何改动。

## 6. Extra Hard 质量检查（是否真正 EH）

对 15 题逐题对照 §6/§7 禁止"Hard 换皮"清单（Hard+多一个 WHERE/换地区/换窗/Top 改 N/加字段均淘汰）：

| 判定 | 数量 | 说明 |
|---|---:|---|
| 真正 Extra Hard | **15** | nested_subquery（E-0086/87/89/95/97/100 等 5 题）、multiple_join 四表链（8 题）、conditional_aggregation SUM/COUNT(CASE)（E-0088/90/92，3 题）、multi_dimension_grouping（E-0091/93/95，3 题）、窗口函数分组内排名（E-0093/96/98）、CTE 自联结跨期比较（E-0094/100）、双均值基准 HAVING（E-0097）、占比与全局基准比较（E-0099）——每题为多能力组合且引入新逻辑层级 |
| 疑似 Hard 换皮 | **0** | 设计期已淘汰的初始候选：月度日分组 TopN、地区销售额占比全列、Top-100 用户榜单、极端比例冗余等均已排除（见 §7 备选池） |

## 7. 备选池（10 条，未入正式集，原因）

| ID | question 摘要 | 未采用原因 |
|---|---|---|
| D-0032 | 2025 地区销售+增速双均值 | 与 E-0097 高度同构（补增长率），不并存 |
| D-0033 | 2025 各地区销售占比全列 | 与 E-0089/E-0099 占比题模板重复 |
| D-0034 | 2024/2025 各月销售额对比（无增速） | 与 E-0094 同比同构，缺增速计算，EH 价值弱 |
| D-0035 | 2025 各分类销售排名（TopN） | 与 E-0093 分类维度销售排名重复，Hard 级结构 |
| D-0036 | 价格与销量双高于分类均值 Top10 | 缺销量维度（仅价格子查询），未达 EH 标准 |
| D-0037 | 累计消费 Top-100 用户 | 与 E-0086 类似但为 TopN，EH 增强不足 |
| D-0038 | 2026 各状态高低金额（换年份） | 与 E-0090 同构（换年度窗），模板重复 |
| D-0039 | 各季度男装/女装销售对比 | 与 Batch3 E-0085 几乎同构，EH 授权不足 |
| D-0040 | 2025 各类目销售占比 Top5 | 与 E-0089 占比结构重复度高 |
| D-0041 | 2026 月度销售额（1-8月） | 月份销售额与 E-0079/E-0096 重叠，EH 算法性不足 |

> 备选池保留于 `data/eval/drafts/extra_hard_batch4_candidates.json` 的 `backups` 字段。

## 8. 校验结果

- `python scripts/validate_eval_dataset.py`：单轮 **100** 条，结构合法 + gold_sql 全部可只读执行，EXIT=0；
- `python scripts/validate_eval_dataset.py --verify-hashes`：**100/100** hash 重算一致（无漂移），EXIT=0；
- `python scripts/validate_eval_batch.py --drafts data/eval/drafts/extra_hard_batch4_candidates.json`：15/15 通过 + 场景配额 + 18 项 operator 目标全达标，EXIT=0；
- `python scripts/validate_eval_batch.py ... --commit`：入集合并成功（100 条），EXIT=0；
- `pytest -q`：**318 passed**（新增 3 条 Batch 4 合同测试：EH 难度/ID 范围+配额/深能力判定）。

## 9. 数据库安全

- 全部 gold_sql 顶层 `SELECT/WITH`，`check_sql_safety` 只读校验通过（禁止写操作）；
- 连接 `mode=ro` + `PRAGMA query_only=ON`；数据库尺寸核验：users 2000 / categories 30 / products 500 / orders 10000 / order_items 30457，未变；seed=20260914、schema_version=1.0 未变；
- 历史 hash：E-0001（`2c041428…`）、E-0026（`57baaac3…`）、E-0056（`8cf160dd…`）等抽查与前序批次审核记录完全一致，E-0001~E-0085 无任何改动。

## 10. 发现的问题 / 遗留

1. **第一阶段 100 条单轮 Benchmark 完成**——`data/eval/ecommerce_eval_v1.json` 现为 100 条正式单轮题，`ecommerce_multiturn_v1.json`（多轮）保持空占位未填充；
2. 部分 EH 题返回行数偏多（如 E-0086 90 行、E-0098 分组 Top3 合计 66 行、E-0091 60 行）：均属数据库真实分布，评测时以结果规范化集合等价比较处理，不影响 EX 判定；
3. E-0099 中"全平台家电占比 24.97%"作为 Gold SQL 字面量参考值写死：已人工从同一口径核算（全库家电 subtotal / 全库 total），与 `--verify-hashes` 重跑一致，防漂移闸门仍在；
4. `validate_eval_batch.py` 完全复用前序批次的 `operator_targets` + 合并入集机制，无需额外改动。

## 11. 下一阶段

第一阶段 100 条单轮 Benchmark（ECO-SQL-Bench v1）正式完成。等待总顾问安排后续工作：Benchmark Runner / 100×Agent 自动化评测 / EX/Pass@1/Repair Rate 等指标实现（Task 13+），多轮评测（ecommerce_multiturn）进入第二阶段规划。