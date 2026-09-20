# FINAL EXPERIMENT MATRIX（最终实验矩阵）

> Task 23 整理。**最终结论只引用 Clean Baseline v1.1（90.0%）**；
> 历史 E1/E2/E4~E7、Stability 等结果仅作背景，**不得与最终 Clean Baseline 混为一谈**。

| 实验 | 配置 | 结果（总体 EX） | 定位 |
|---|---:|---|---|
| **Clean Baseline（最终基线）** | ECO-SQL-Bench v1.1 + SQLGENERATOR_PROMPT_V1.3 + FEWSHOT_V3(23) + DB dev-2026-09-14 + mimo-v2.5-pro | **90.0%**（exec 99%，Pass@1 90%，prov 0 / timeout 0） | **最终回归基线（唯一正式引用）** |
| E3 Detector（离线扫描） | 100 条 Pred SQL 静态扫描（Gold-independent） | 命中 E-0086（唯一 alarm）；20 条候选人工审计 0 FN | **创新机制（检测能力），非 EX 增益** |
| E3 Hint 干预（Task20 单例） | E-0086 dry-run：alarm→hint→1 次 regen | EX✗ → EX✓（369854.65→89397.46） | **PoC / 机制验证** |
| E3 Hint 干预（Task21 OFF/ON） | OFF=90.0%（无 hint）；ON=93.0%（仅 alarm 注入） | 观测 +3pt；**其中仅 E-0086 +1pt 可归因 Hint**（E-0099/0100 未注入） | **PoC / 机制验证**（非严格单变量，机制层观测） |
| 历史 Baseline（Task13） | 早期配置 | 72% | 历史实验，已被 v1.1 卫生修复取代 |
| 历史 E1（Task14） | Prompt V1.1 + Few-shot V2 | 88% | 历史实验（含泄漏与 Gold 缺陷背景） |
| 历史 E2（Task14.1） | V1.1 + V1 Few-shot | 91% | 历史实验（旧口径） |
| 历史 Stability（Task14.1） | 三次复测 83/85/88 | 均值约 85.3 | 历史实验 |
| 历史 E4~E7（Task14.2） | 专项规则独立实验 | 85/85/81/79 | 历史实验（已证规则无效，不进入最终结论） |

> **禁止混用**：最终报告/PPT 只能引用 `Clean Baseline v1.1 = 90.0%` 作为整体 EX 基线；
> E3 结果以"机制验证 / proof of concept"呈现（见 E3_FINAL_FREEZE.md）。
> 历史 E1/E2/E4~E7/Stability 因涉及 Few-shot 泄漏、Gold 缺陷、旧口径，仅作项目历程背景。

*生成：Task 23；数据来源：reports/eval/clean_baseline_v1_1、task17~21、legacy_experiments_notice。*