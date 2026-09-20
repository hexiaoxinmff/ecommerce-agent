# ECO-SQL-Bench · Baseline v1 快照

> Task 14 起点：将 Task 13 的首次完整评测正式标记为 Baseline v1（原报告未修改，仅复制固化）。

| 元数据 | 值 |
|---|---|
| dataset_version | 1.0 |
| database_version | dev-2026-09-14 |
| schema_version | 1.0 |
| seed | 20260914 |
| model | mimo / mimo-v2.5-pro |
| base_url | https://api.xiaomimimo.com/v1 |
| run_id | 20260915_41066 |
| prompt_version | SQLGENERATOR_PROMPT_V1（未修改） |
| fewshot_version | FEWSHOT_V1（18 条） |
| timestamp | 2026-09-15T11:24:26Z |
| randomness | provider API controlled randomness unavailable |

## 总体指标

| 指标 | 值 |
|---|---|
| Overall EX | **72.0%** |
| Conditional EX | 72.0% |
| Exec Rate | 100.0% |
| Pass@1（初始） | 72.0% |
| Final EX（含 Repair） | 72.0% |
| Repair Trigger Rate | 0.0% |
| Repair Success Rate | —（未触发） |
| Avg Latency | 11962.3 ms |
| P50 | 11728.63 ms |
| P95 | 19053.86 ms |
| Bad Case 数 | 28 |

## 按难度

| difficulty | count | EX% |
|---|---:|---:|
| easy | 25 | 88.0 |
| medium | 30 | 70.0 |
| hard | 30 | 63.33 |
| extra_hard | 15 | 66.67 |

## 关键结论（Baseline v1）

1. **Exec Rate = 100%**：Agent 生成的 SQL 全部通过 Safety 并成功执行，**当前 Benchmark 中不存在执行错误类 Bad Case**；
2. **全部 28 个 Bad Case 均为 `result_mismatch`**：SQL 可执行但结果与 Gold 不等价 → 问题集中在「生成阶段语义/口径理解」，而非执行/修复环节；
3. Repair 未触发（0%）：自然测试集未产生可触发 Repair 的数据库执行错误，Repair 增益无法从此轮评估，需单独专项测试；
4. 难度梯度：Easy 88% → Hard 63% 呈下降，符合复杂度预期；Extra Hard 66.67% 略高于 Hard（样本小，15 条）。

*本快照为后续所有实验（E1/E2/E3）的对比基准，禁止覆盖。*