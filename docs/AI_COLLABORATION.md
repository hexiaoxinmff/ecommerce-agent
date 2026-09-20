# AI 协作过程记录（AI Collaboration）

> 本项目从需求、设计、实现到评测、验收的全过程伴随大量 **AI 协作**。本文档真实记录协作工具、角色分工、流程与关键案例，作为项目 AI 协作方法论的交付物。
> 安全声明：本文档**不包含任何 API Key / Secret**；密钥仅存在于本机 `.env`（已被 `.gitignore` 排除）。

---

## 1. 使用工具

| 工具 | 在本项目中的角色 |
|---|---|
| **ChatGPT** | 总体架构设计、实验设计、需求验收、Prompt 设计 |
| **TRAE**（主开发 Agent，文档中亦记录为 TRAE + DeepSeek-V4-Pro） | 主开发实现、测试编写与执行、实验运行、文档撰写 |
| **WorkBuddy** | 独立审计、反例检查、实验复核、冻结前终审 |
| **Mimo V2.5 Pro**（`mimo-v2.5-pro`，OpenAI-compatible API） | **Runtime SQL Generation**（Schema Linking / SQL 生成 / Repair 的实际推理模型） |

> Mimo 既是运行时推理模型，也曾在开发期作为评审辅助工具参与讨论；本文档中“Mimo”特别指代 Runtime SQL Generation 角色。

## 2. 角色分工

```text
ChatGPT
→ 总体架构 / 实验设计 / 验收 / 提示词

TRAE
→ 主开发 Agent / 实现 / 测试 / 实验执行

WorkBuddy
→ 独立审计 / 反例检查 / 实验复核

Mimo（mimo-v2.5-pro）
→ Runtime SQL Generation（运行期实际生成 SQL 的模型）
```

> 分工原则：**不信任单一 AI 输出**。关键结论（实验指标、数据一致性、冻结边界）必须经过独立审计复核后才能进入正式文档。

## 3. AI 协作流程

```text
需求
 ↓
方案（ChatGPT 主导：总体架构 / 实验设计 / 提示词）
 ↓
TRAE 实现
 ↓
测试（TRAE 编写并运行 pytest）
 ↓
WorkBuddy 独立审计（反例检查 / 实验复核）
 ↓
修正
 ↓
实验（TRAE 执行 Benchmark / 专项实验）
 ↓
冻结（复审计通过后 FROZEN，禁止修改）
```

- 每个阶段产物落地为文档 / 数据（`docs/`、`reports/eval/`），保证过程可追溯；
- 实验数据冻结后任何最终文档只能**引用**冻结结果，不得改写（本项目 E3 即按此规则 FROZEN）。

## 4. 重要案例

### 4.1 E3 Detector（Gold-independent Fan-out 检测）

- **需求**：不依赖 Gold SQL / 结果 / 标签，仅输入 Pred SQL 做 fan-out 风险静态检测。
- **协作**：ChatGPT 侧设计“检测能力应由独立模块承担”的边界 → TRAE 实现 `backend/app/sqlcheck/fanout_detector.py`（acquired frozen）→ WorkBuddy 复核规则定义与误报/漏报口径。
- **结果**：21/21 双表题结构覆盖审计 0 真实漏报；E-0086 唯一 alarm。详见 `reports/eval/E3_FINAL_FREEZE.md`、`reports/eval/task17_e3_fanout_validator/`。

### 4.2 Task 19 漏报审计

- **需求**：验证 Detector 是否漏报（审计闭环）。
- **协作**：TRAE 生成 20 条候选 + E-0086 审计材料 → **WorkBuddy 独立审计** 标注真实 FN → 审计结果：`audit_subset_fn_rate=0/20`。
- **产物**：`reports/eval/task19_e3_fanout_audit/audit_report.md` 等。
- **意义**：审计由独立方执行，避免“实现方自证正确”的偏差。

### 4.3 WorkBuddy 独立终审（Task 22 冻结）

- **协作**：E3 冻结前由 WorkBuddy 对全部实验数据做 hash 级复核：Task 17~21 产物、DB / Prompt / Few-shot 快照、代码冻结清单逐项比对 → 结论 **PASS WITH RESERVATIONS**。
- **保留项**：`alarm n=1`（结论强度受限）、Detector 已知局限（P1-1 子查询剪枝未生效、P1-2 未限定列名漏报盲区）、OFF/ON 非严格单变量。
- **结果**：E3 正式 FROZEN（`reports/eval/E3_FINAL_FREEZE.md`），后续只引用不修改。

### 4.4 E-0086 Hint 单例（Task 20 / 21）

- **需求**：验证“Detector alarm → 注入 Hint → 单次 regeneration”机制是否修复 fan-out。
- **协作**：TRAE 实现 Hint 模块（`backend/app/experiments/fanout_hint.py`，冻结）并执行单例 dry-run → Task 21 OFF/ON 100 条对照。
- **结果**：
  - OFF 90% / ON 93% 为**观测差异**；其中**仅 E-0086 的 +1pt 具有直接 Hint 归因证据**（E-0099 / E-0100 未注入 Hint）；
  - E-0086 单例：`369854.65 → 89397.46`（fan-out 消除，EX✗ 变 EX✓）；
  - `alarm n=1`，属 **proof of concept / mechanism validation**。
- **边界遵守**：最终文档**禁止**表述为“Hint 提升 EX 3 个百分点”。

## 5. 协作经验与边界

- **AI 生成内容的双重校验**：所有指标（EX / Exec Rate / Pass@1 / 延迟）来自 `evaluation/` 框架统一计算并落盘，文档只引用已冻结数字；
- **数据卫生**：Few-shot 泄漏 Gate、Gold Hash Gate、DB 前后 hash 校验由 `scripts/run_eval.py` 强制前置，防止 AI 协作中的“静默污染”；
- **防泄漏**：API Key 只存在 `.env`；日志 / 客户端 / 文档统一脱敏；
- **诚实边界**：未实现能力（Multi-turn、User Management、登录）如实标注 Out-of-Scope，不包装为已实现。

---

*编写：Task 24（2026-09-16）。基于仓库真实协作记录（PRD、FINAL_ACCEPTANCE_REPORT、E3_FINAL_FREEZE、task17~21 报告）。*