# 旧实验结果保护与效力说明（Task 14.3）

> 日期：2026-09-16
> 目的：保留历史实验证据，同时如实标注其效力边界（不删除、不覆盖）。

## 保留的历史实验

| run_id | 实验 | 目录 | 保留 |
|---|---|---|---|
| 20260915_41066 | Baseline v1 | reports/eval/baseline_v1/ | 保留 |
| 20260915_45852 | E1 | reports/eval/e1_semantics_v1/ | 保留 |
| 20260915_48824 / 50382 | Stability run01/02 | reports/eval/stability_v1/ | 保留 |
| 20260915_51396 | E2 | reports/eval/e2_fewshot_v1/ | 保留 |
| 20260915_54475 / 56546 / 59408 / 62451 | E4~E7 | reports/eval/e{4,5,6,7}_*/ | 保留 |

## 效力说明（重要）

Task 14.3 已确认以下问题影响历史实验结论的可信度：

1. **Benchmark Leakage**：当时使用的 FEWSHOT_V2（ex_019~024）与 V1（ex_002）
   存在与 Benchmark Gold SQL 的逐字节/模板级泄漏；
   → 上述实验（E1/Stability/E2）使用的 Few-shot 含泄漏示例，
   **其 EX 分数可能被泄漏抬升，不作为最终对外实验结论**。
2. **Gold 缺陷**：E-0086（金额 fan-out 膨胀）、E-0095（题面/Gold 不一致）、
   E-0098（排名无 tiebreaker）已在 v1.1 修复；
   → 基于旧 v1.0 Gold 的历史评测结果与修复后基准不完全可比。
3. 因此本批旧结果**仅作为过程证据保留**，正式结论以
   **Clean Benchmark v1.1 + Clean Few-shot（FEWSHOT_V3）+ Clean Prompt（V1.3）**
   重新建立的 Baseline 为准（下一阶段）。

## 保留策略

- 不做任何删除 / 覆盖 / 改写；
- 若后续需要，可新增 `reports/eval/clean_baseline_v1.1/` 存放干净基准结果。