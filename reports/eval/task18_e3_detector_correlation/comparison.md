# Task 18：E3 Fan-out Detector 关联性验证 — OFF vs ON 对比

> 说明：OFF/ON 为独立生成样本（Mimo 随机性），比较的是『alarm 样本与失败率的关联』，非严格 paired causal effect。
> OFF = Clean Baseline 100 条（未调用 Detector 的官方样本）；ON = 全新 100 条（相同 Agent，离线补算 telemetry，Detector 只读不干预）。

## OFF（total=100）

| 组 | count | exec_fail% | EX_fail% | mismatch% | timeout% | provider |
|---|---:|---:|---:|---:|---:|---:|
| alarm | 1 | 0.0 | 100.0 | 100.0 | 0.0 | 0 |
| no_alarm | 99 | 1.01 | 9.09 | 8.08 | 0.0 | 0 |

- alarm 样本：['E-0086']
- EX✓ 中被 alarm（噪声）：[]

## ON（total=100）

| 组 | count | exec_fail% | EX_fail% | mismatch% | timeout% | provider |
|---|---:|---:|---:|---:|---:|---:|
| alarm | 1 | 0.0 | 100.0 | 100.0 | 0.0 | 0 |
| no_alarm | 99 | 1.01 | 8.08 | 7.07 | 1.01 | 1 |

- alarm 样本：['E-0086']
- EX✓ 中被 alarm（噪声）：[]

## 已知 Bad Case 覆盖

| 题 | OFF alarm | ON alarm | OFF ex | ON ex | OFF err | ON err |
|---|---|---|---|---|---|---|
| E-0086 | True | True | False | False | result_mismatch | result_mismatch |
| E-0057 | False | False | False | False | result_mismatch | result_mismatch |
| E-0077 | False | False | False | False | result_mismatch | result_mismatch |
| E-0082 | False | False | False | False | result_mismatch | result_mismatch |
| E-0083 | False | False | False | False | result_mismatch | result_mismatch |
| E-0090 | False | False | False | False | result_mismatch | result_mismatch |
| E-0095 | False | False | False | False | result_mismatch | result_mismatch |
| E-0096 | False | False | False | False | result_mismatch | result_mismatch |
| E-0099 | False | False | False | True | SQL 执行失败: no such column: r.region | None |
| E-0100 | False | False | False | True | result_mismatch | None |

> 注：E-0099 / E-0100 在 ON 中变为 EX✓，但其 **alarm=False（未注入 hint）**，变化来自独立样本随机性，不受 Detector/干预影响。

## E-0086 单独报告

| 项目 | OFF | ON |
|---|---|---|
| Detector alarm | True | True |
| EX 结果 | False | False |
| error_type | result_mismatch | result_mismatch |

样本量过小时不做显著性推断；给出相对风险（仅分母足够时参考）。

> **RR 值使用声明（审计修正）**：comparison.json 中的 `rel_risk_ex_fail_off=11.0` 与
> `rel_risk_ex_fail_on=12.375` 因 alarm 样本 n=1，**仅保留为算术诊断量（arithmetic diagnostics）**，
> **不得用于统计推断**（无置信区间、usable_for_inference=false）。
> 完整语义见 comparison.json 的 `rel_risk_limits` 字段。