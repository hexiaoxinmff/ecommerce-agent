# ECO-SQL-Bench 评测报告 · run 20260916_41923

- 时间：2026-09-16T11:38:43Z
- 模式：full
- 数据集：1.1 / DB dev-2026-09-14 / Schema 1.0 / seed 20260914
- 模型：mimo / mimo-v2.5-pro（base_url https://api.xiaomimimo.com/v1）
- 随机性：provider API controlled randomness unavailable

## 总体

| 指标 | 值 |
|---|---|
| Total | 100 |
| Valid Model Runs | 100 |
| Provider Failures | 0 |
| Timeouts | 0 |
| Exec Rate | 100.0% |
| Overall EX | 93.0% |
| Conditional EX | 93.0% |
| Pass@1(初始) | 93.0% |
| Final EX(含Repair) | 93.0% |
| Repair Trigger Rate | 0.0% |
| Repair Success Rate | 0.0% |
| Avg Latency | 10529.26 ms |
| P50 Latency | 9616.94 ms |
| P95 Latency | 15561.7 ms |

## 按难度

| difficulty | count | exec_rate% | EX% |
|---|---:|---:|---:|
| easy | 25 | 100.0 | 100.0 |
| medium | 30 | 100.0 | 100.0 |
| hard | 30 | 100.0 | 86.67 |
| extra_hard | 15 | 100.0 | 80.0 |

## 按场景

| scenario | count | exec_rate% | EX% |
|---|---:|---:|---:|
| category_analysis | 10 | 100.0 | 100.0 |
| comparison | 3 | 100.0 | 100.0 |
| order_analysis | 12 | 100.0 | 91.67 |
| product_analysis | 15 | 100.0 | 100.0 |
| ranking | 6 | 100.0 | 100.0 |
| ratio | 4 | 100.0 | 50.0 |
| regional_analysis | 9 | 100.0 | 88.89 |
| sales_analysis | 15 | 100.0 | 100.0 |
| time_analysis | 14 | 100.0 | 85.71 |
| user_analysis | 12 | 100.0 | 91.67 |

## 按 Operator

| operator | count | EX% |
|---|---:|---:|
| aggregate | 96 | 92.71 |
| case_when | 10 | 80.0 |
| comparison_to_average | 14 | 85.71 |
| conditional_aggregation | 3 | 66.67 |
| date_filter | 39 | 87.18 |
| date_group | 15 | 93.33 |
| group_by | 66 | 89.39 |
| having | 17 | 88.24 |
| join | 37 | 89.19 |
| limit | 25 | 92.0 |
| multi_dimension_grouping | 6 | 83.33 |
| multiple_join | 18 | 83.33 |
| nested_subquery | 6 | 83.33 |
| order_by | 51 | 92.16 |
| ratio | 14 | 78.57 |
| subquery | 31 | 80.65 |
| top_n | 25 | 96.0 |
| where | 75 | 92.0 |

## 失败分布

| failure_stage | count |
|---|---:|
| none | 93 |
| result | 7 |

| error_type | count |
|---|---:|
| none | 93 |
| result_mismatch | 7 |
