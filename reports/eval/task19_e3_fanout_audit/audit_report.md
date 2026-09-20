# Task 19：E3 Fan-out Detector 潜在漏报人工审计

> 目标：人工审计 Task 17 中"SQL 含 orders+order_items 连接但 Detector 未报警"的候选，
> 判断是否存在真实 Fan-out 风险（FN）。本任务不做 Detector 干预、不修规则、不做 Repair。
> 范围：`reports/eval/task17_e3_fanout_validator/static_scan_report.json` 中候选集合。

---

## 1. 候选集

从 Task17 扫描结果提取：`fan_out_suspected=false` 且 SQL 文本同时含 `order_items` 与 `orders` → **20 条候选**
（E-0059/E-0061/E-0062/E-0067/E-0073/E-0074/E-0080/E-0082/E-0083/E-0085/E-0087/E-0088/E-0089/E-0093/E-0095/E-0096/E-0097/E-0098/E-0099/E-0100）。

> 注：Task17 汇报"约 15 条"，此处按同一判定逻辑提取为 20 条（含 protected/low 各条），范围一致，逐条完成审计。

## 2. 人工审计结果（按 Task17 Detector 定义逐条判定）

### 汇总

| 指标 | 值 |
|---|---:|
| 候选总数 | 20 |
| human_fanout_label = false（TN） | **20** |
| human_fanout_label = true（确认 FN） | **0** |
| uncertain | **0** |
| Detector 额外报警（E-0086，已知正例） | 1 |

### 20 条候选分类（全部 TN）

**A. item-level 聚合（安全，orders 仅作过滤/维度）**：E-0059、E-0062、E-0067、E-0074、E-0080、E-0085
（均 `SUM(oi.quantity)` / `SUM(oi.subtotal)`，无订单级字段聚合 → 无 1:N 放大）

**B. CASE 值分支为明细、条件列为维度/日期（安全）**：E-0082、E-0083、E-0100
（`SUM(CASE WHEN c.name/o.order_date ... THEN oi.subtotal)` —— 条件列是过滤键，聚合值列是明细 → **不构成 fan-out**；Task17 修复的误报点未复发）

**C. CTE/子查询先按明细预聚合，再两阶段 AVG/排名（安全）**：E-0061、E-0087、E-0088、E-0089、E-0093、E-0095、E-0096、E-0098、E-0099
（均在 CTE 内对 item 明细聚合后外部二次聚合/窗口排名；无订单级字段被明细行放大）

**D. DISTINCT 去重保护（安全）**：E-0073、E-0097、E-0100
（`COUNT(DISTINCT o.order_date)` / `COUNT(DISTINCT o.id)`）

> **D 项专项确认**：CASE 条件引用 orders 列但被聚合值为 item 列（E-0082/0083/0100 的结构），全部人工判定为**非 fan-out**；未出现"条件列被误判为聚合值"的反复误报，Task 17 修复保持有效。

## 3. 关键问题：是否存在真实 FN？

**无。**

- 20 条候选人工全部判定无 fan-out 风险；
- 未发现"Detector=false 但人工认为存在真实 1:N 订单级放大"的 SQL；
- 因此 **Potential FN = 0**。

> 附带确认：E-0086（唯一已知 Fan-out 正例）Detector 继续报警且为高严重度 → **Known Positive 命中**。
> 已知非 fan-out Bad Case（E-0057/0077/0082/0083/0090/0095/0096/0099/0100）未因存在 JOIN 而被重新标为 fan-out。

## 4. Precision / Recall

- 现有标签：Known Positive = E-0086（1 条，命中）；本批 20 条候选全部人工标为 TN。
- **不将本审计指标宣传为整个 ECO-SQL-Bench 的 Recall**。仅当给定：

| | Detector=alarm | Detector=false |
|---|---:|---:|
| 人工=正（fan-out） | TP=1（E-0086） | FN=0 |
| 人工=负（无） | FP=0 | TN=20 |

- 审计子集（E-0086 + 20 候选）：
  - `audit_subset_precision = 1.0`（1/1）
  - `audit_subset_recall = 1.0`（1/1）
  - **注意**：正例 n=1、皆为人工标签，统计功效有限；此数字不代表全集 Recall。

## 5. 已知 Bad Case 对照

| 题 | Detector | 人工评估 | 备注 |
|---|---|---|---|
| E-0086 | alarm(high) | 正例命中 | 已知 Fan-out 正例（维持） |
| E-0057 | false | 非 fan-out | CASE 边界/实体选择问题 |
| E-0077 | false | 非 fan-out | Schema Linking 缺表 |
| E-0082/E-0083 | false | 非 fan-out | 输出列契约（值已正确） |
| E-0090 | false | 非 fan-out | 过滤/结构/口径复合 |
| E-0095/E-0096 | false | 非 fan-out | 过滤基准/金额口径 |
| E-0099 | false | 非 fan-out | 别名引用 bug |
| E-0100 | false | 非 fan-out | 金额口径；COUNT DISTINCT 保护 |

## 6. 结论

**KEEP（维持当前规则）**

- 在当前 20 条潜在漏报候选上**未发现真实 FN**；
- 已知正例 E-0086 继续命中；
- CASE 条件列不漏报问题未复发；
- 无需修改 Detector（本任务未改任何规则）。

> 说明：E-0086 命中 + 零候选 FN 不等于全集 Recall 高；当前结论仅针对本批人工审计子集。

## 7. 产物

- `reports/eval/task19_e3_fanout_audit/audit_candidates.json`（20 条逐条人工标签 + 完整 Pred SQL）
- `reports/eval/task19_e3_fanout_audit/audit_report.json`
- `reports/eval/task19_e3_fanout_audit/audit_report.md`（本文件）
- `reports/eval/task19_e3_fanout_audit/experiment_config.json`
- `audit_candidates_raw.json`（初筛中间产物）