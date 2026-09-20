# ECO-SQL-Bench 评测报告 · run 20260916_09876

- 时间：2026-09-16T02:44:36Z
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
| Exec Rate | 99.0% |
| Overall EX | 90.0% |
| Conditional EX | 90.0% |
| Pass@1(初始) | 90.0% |
| Final EX(含Repair) | 90.0% |
| Repair Trigger Rate | 1.0% |
| Repair Success Rate | 0.0% |
| Avg Latency | 10876.08 ms |
| P50 Latency | 10488.92 ms |
| P95 Latency | 15440.79 ms |

## 按难度

| difficulty | count | exec_rate% | EX% |
|---|---:|---:|---:|
| easy | 25 | 100.0 | 100.0 |
| medium | 30 | 100.0 | 100.0 |
| hard | 30 | 100.0 | 86.67 |
| extra_hard | 15 | 93.33 | 60.0 |

## 按场景

| scenario | count | exec_rate% | EX% |
|---|---:|---:|---:|
| category_analysis | 10 | 100.0 | 100.0 |
| comparison | 3 | 100.0 | 66.67 |
| order_analysis | 12 | 100.0 | 91.67 |
| product_analysis | 15 | 100.0 | 100.0 |
| ranking | 6 | 100.0 | 100.0 |
| ratio | 4 | 75.0 | 25.0 |
| regional_analysis | 9 | 100.0 | 88.89 |
| sales_analysis | 15 | 100.0 | 100.0 |
| time_analysis | 14 | 100.0 | 85.71 |
| user_analysis | 12 | 100.0 | 83.33 |

## 按 Operator

| operator | count | EX% |
|---|---:|---:|
| aggregate | 96 | 89.58 |
| case_when | 10 | 80.0 |
| comparison_to_average | 14 | 78.57 |
| conditional_aggregation | 3 | 66.67 |
| date_filter | 39 | 84.62 |
| date_group | 15 | 93.33 |
| group_by | 66 | 86.36 |
| having | 17 | 88.24 |
| join | 37 | 83.78 |
| limit | 25 | 92.0 |
| multi_dimension_grouping | 6 | 83.33 |
| multiple_join | 18 | 72.22 |
| nested_subquery | 6 | 50.0 |
| order_by | 51 | 88.24 |
| ratio | 14 | 64.29 |
| subquery | 31 | 70.97 |
| top_n | 25 | 96.0 |
| where | 75 | 88.0 |

## 失败分布

| failure_stage | count |
|---|---:|
| none | 90 |
| result | 9 |
| sql_repair | 1 |

| error_type | count |
|---|---:|
| SQL 执行失败: no such column: r.region | 1 |
| none | 90 |
| result_mismatch | 9 |
