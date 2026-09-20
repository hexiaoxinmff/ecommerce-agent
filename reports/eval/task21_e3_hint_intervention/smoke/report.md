# ECO-SQL-Bench 评测报告 · run 20260916_38927

- 时间：2026-09-16T10:48:47Z
- 模式：full
- 数据集：1.1 / DB dev-2026-09-14 / Schema 1.0 / seed 20260914
- 模型：mimo / mimo-v2.5-pro（base_url https://api.xiaomimimo.com/v1）
- 随机性：provider API controlled randomness unavailable

## 总体

| 指标 | 值 |
|---|---|
| Total | 1 |
| Valid Model Runs | 1 |
| Provider Failures | 0 |
| Timeouts | 0 |
| Exec Rate | 100.0% |
| Overall EX | 100.0% |
| Conditional EX | 100.0% |
| Pass@1(初始) | 100.0% |
| Final EX(含Repair) | 100.0% |
| Repair Trigger Rate | 0.0% |
| Repair Success Rate | 0.0% |
| Avg Latency | 64601.28 ms |
| P50 Latency | 64601.28 ms |
| P95 Latency | 64601.28 ms |

## 按难度

| difficulty | count | exec_rate% | EX% |
|---|---:|---:|---:|
| extra_hard | 1 | 100.0 | 100.0 |

## 按场景

| scenario | count | exec_rate% | EX% |
|---|---:|---:|---:|
| user_analysis | 1 | 100.0 | 100.0 |

## 按 Operator

| operator | count | EX% |
|---|---:|---:|
| aggregate | 1 | 100.0 |
| comparison_to_average | 1 | 100.0 |
| group_by | 1 | 100.0 |
| join | 1 | 100.0 |
| multiple_join | 1 | 100.0 |
| nested_subquery | 1 | 100.0 |
| order_by | 1 | 100.0 |
| subquery | 1 | 100.0 |
| where | 1 | 100.0 |

## 失败分布

| failure_stage | count |
|---|---:|
| none | 1 |

| error_type | count |
|---|---:|
| none | 1 |
