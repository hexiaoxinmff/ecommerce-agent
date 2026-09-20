# Bad Case 归一化说明

> ## ⚠️ 重要：本目录 ≠ 正式 Bad Case
>
> **本目录包含历史失败样本沉淀，不等同于 Clean Baseline 的正式 10 条 Bad Case。正式 Clean Baseline Bad Case 以 `reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` §7 为准。**
>
> **为什么会有这个区别**：本目录是**跨多轮评测运行的历史累积**（Task 13 / 14 / 17~21 等），
> 包含了不同配置、不同 Prompt 版本、不同 Few-shot 版本下产生的失败样本，
> 也包含因 **API Key 未配置等环境原因**导致的假失败。
> 而 Clean Baseline v1.1 的正式 Bad Case 是**单一冻结配置**下、经 Gold Hash 门禁与
> Leakage 检查后的 **10 条**（`EX=false`）。
>
> **答辩/报告引用规则**：
> - 引用**正式 Bad Case 数量与清单** → 一律用 `reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` §7（10 条）；
> - 引用**失败类型分布/归因** → 可用本目录做背景分析，但**必须注明是历史累积样本，不是正式基线**；
> - **禁止**用本目录的文件数（188 个 JSON）冒充正式 Bad Case 数量。
>
> **本目录不做清理**：历史样本一律保留，便于追溯与复盘。

本目录沉淀评测运行中发现与复测的失败案例，供 Task 13/14 用于 Prompt、Schema Linking、Few-shot、Repair 优化。

## 文件规范

一条 Bad Case 一个 JSON 文件，命名：`{case_id}.json`（示例见 `B-0001.example.json`）。

```json
{
  "case_id": "B-0001",
  "eval_id": "E-0023",
  "question": "原问题",
  "gold_sql": "标准答案 SQL",
  "pred_sql": "Agent 实际生成 SQL（失败真身，不可省略）",
  "failure_stage": "sql_generation",
  "error_type": "missing_join",
  "trace": "fail 链路摘要（可回放 Trace）",
  "repair_count": 0,
  "notes": "失败原因与下一步建议"
}
```

## 枚举字段

### failure_stage（错误发生环节，必须枚举）

```text
schema_linking | fewshot_retrieval | sql_generation | sql_validation | sql_execution | result_analysis
```

### error_type（允许扩展但每类必须有定义，纳入 docs/evaluation-dataset-spec.md 附录）

常见值示例：

```text
missing_join          缺 JOIN / JOIN 条件错误
wrong_caliber         口径错误（未排除 cancelled、金额字段误用）
column_hallucination  列名幻觉
aggregation_error     聚合层级/顺序错误
condition_missing     条件遗漏（时间、地区、状态）
empty_result          结果非空预期却为空
timeout / unsafe / unparseable
```

## 统计

每次评测后按 failure_stage × error_type 归因，优先修复占比较高的类别。