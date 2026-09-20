# E3 — Fan-out Detector + Hint 干预：最终冻结摘要

> 最终可答辩 / 论文 / PPT 版本。依据 WorkBuddy 独立终审（PASS WITH RESERVATIONS）与 Task 22 冻结整理。
> 正式状态：**FROZEN**

---

## 一、核心成果

| # | 成果 | 证据 |
|---|---|---|
| 1 | **Gold-independent 静态 Fan-out 检测** | `analyze_fanout(sql)` 仅输入 Pred SQL；不读 Gold SQL/Result/Label |
| 2 | **orders×order_items 粒度风险识别** | Pattern `order_join_item_order_agg` / `count_star_ambiguous`；正确区分 item-level 聚合与 CASE 条件列 |
| 3 | **21/21 双表题结构覆盖审计** | Task 17 (20 候选 + E-0086) 人工审计：0 真实 FN（audit_subset_fn_rate=0/20） |
| 4 | **E-0086 4.137× fan-out 实证** | 累计消费额 369854.65 → 修正 89397.46（DB 直连验证） |
| 5 | **Hint 单次 regeneration 机制验证** | Task 20 单例 + Task 21 ON 组均复现：alarm→hint→1 次 regeneration→EX✓ |
| 6 | **E-0086 单例 EX✗ → EX✓** | 双 CTE（订单粒度 SUM + 明细粒度 COUNT DISTINCT）再 JOIN |

## 二、实验结果（正确口径）

```text
OFF = 90%
ON  = 93%
观察到 +3pt
```

- 3 个新增正确题中，**仅 E-0086 的 +1pt 具有直接 Hint 归因证据**（alarm=true 且注入 hint）；
- **E-0099 / E-0100 未接受 Hint 归因**（alarm=false，未注入 hint，改善来自独立样本随机性）；
- OFF/ON 非严格单变量（timeout 60s vs 90s；LangGraph+repair vs 线性脚本无 repair；延迟口径不同）。

**禁止表述**："Hint 提升 EX 3pt" / "显著提升" / "证明有效"。

## 三、实验性质

> **Proof of concept / mechanism validation**
> （Gold-independent Fan-out 风险检测 + 条件触发 Hint 的机制验证）

## 四、限制

- **alarm 样本 n=1**：不支持"整体 EX 稳定提升 / 高 Recall / 普遍有效 / 无回归"等结论；
- Detector 已知局限：**P1-1**（子查询剪枝未生效）、**P1-2**（未限定列名漏报盲区）、
  **P2-3**（SUM(DISTINCT) ≠ protection）、**P2-4**（仅覆盖 orders×order_items）——属下一版本工作；
- 单次 regeneration 边际成本约 **+8.3s**；本次摊薄约 **+0.08s/题**（alarm 1%），非大规模成本可接受性证明。

## 五、产物清单（冻结，勿修改实验数据）

| Task | 目录 | 关键产物 |
|---|---|---|
| 17 | `reports/eval/task17_e3_fanout_validator/` | fanout_detector.py、static_scan_report.json/.md、detector_rules.md、E3_CLAIMS_AND_LIMITS.md、E3_KNOWN_LIMITATIONS.md |
| 18 | `reports/eval/task18_e3_detector_correlation/` | run_off/run_on telemetry、comparison.json/.md |
| 19 | `reports/eval/task19_e3_fanout_audit/` | audit_candidates.json、audit_report.json/.md、audit_table.csv |
| 20 | `reports/eval/task20_e3_hint_intervention/` | single_case_e0086.json/.md、hint_design.md |
| 21 | `reports/eval/task21_e3_hint_intervention/` | run_off/run_on eval.json、interventions.json、comparison.json/.md |

代码冻结清单：

- `backend/app/sqlcheck/fanout_detector.py`（Detector，冻结）
- `backend/app/experiments/fanout_hint.py`（Hint 模块，冻结；Hint 文本 SHA256=`5f13e7cc...`）
- `scripts/run_eval_fanout_hint.py`（Task21 历史 Runner，冻结）
- `backend/tests/test_e3_fanout_detector.py` / `test_task18_telemetry.py` / `test_task20_hint.py`（测试，冻结）
- 评测报告：`reports/eval/clean_baseline_v1_1/`（E3 基线）与上述 5 个 Task 目录

> **归档位置声明**：E3 全部实验产物位于**主仓库**（`f:\基于 Text2SQL 的电商智能数据分析 Agent`，master 分支），
> **不在旧 worktree `master-b947f329` 中**。提交项目时不得遗漏。

---

*冻结日期：2026-09-16；状态：FROZEN；后续 E3 不再设计新实验。*