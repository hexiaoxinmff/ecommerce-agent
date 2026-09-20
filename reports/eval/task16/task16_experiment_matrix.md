# Task 16：Candidate E8/E9/E10/E11 实验矩阵（单变量设计）

> 实验起始点（正式回归基线）：**Clean Baseline EX = 90.0%**
> （ECO-SQL-Bench v1.1 + SQLGENERATOR_PROMPT_V1.3 + FEWSHOT_V3 23条，valid_model_runs=100，Provider Failure=0，Timeout=0）
---
>
> 规则：每个候选**只改变一个变量**；全部与 Baseline 同 Benchmark、同 DB、同 Model、同 Runner；运行完整 100 条；
> 记录完整 sha256（dataset/prompt/fewshot/DB）；至少 2 次运行（Mimo 随机性）取趋势，不只比单次。

---

## 1. 四个候选方向

| 候选 | 单变量 | 目标 Bad Case（可修复子集） | 依据（task16_bad_case_reanalysis） |
|---|---|---|---|
| **E8** | 生成后 Output Shape/列引用**静态校验**（新增独立校验函数 + sidecar 契约，不改 Safety 主流程） | E-0082, E-0083, E-0090(列)，附带 E-0099(引用) | A1/A2 结构列契约错误 + D（引用 bug） |
| **E9** | 仅增加**输出结构示范型 Few-shot**（cand_A1 + cand_A2） | E-0082, E-0083, E-0090(列) | A1/A2 输出列契约 |
| **E10** | 仅增加**金额语义示范**（cand_B1 + cand_B2） | ——（B1/B2 若续作则目标 E-0077/0096/0100，但见下 §3 **不建议**） | B 类被否定（缺表/Gold 冲突） |
| **E11** | 仅增加**聚合粒度示范**（cand_C1 + cand_C2） | E-0086, E-0095 | C1/C2 两阶段聚合/filter 前置 |

> **E8/E9/E10/E11 不得叠加**。E9 与 E11 同时有效时，先跑 E9 再跑 E11（各自独立结论）。

---

## 2. 每方向的实验设计

### Candidate E9（推荐优先，见 recommendation §3）

**假设**：加入 2 条"输出结构"示范（label+value 多列、分项+总数列）后，模型对"占比题应输出维度列+指标列"、以及"结构统计要带总数列"的列契约遵从度提高 → E-0082/E-0083（缺 label 列）至少 1 题修复、E-0090 输出列补齐。

**变量**：Few-shot 数据集 = 正式 23 条 + `cand_A1 + cand_A2`（临时候选文件，**不修改**正式文件；通过 `FEWSHOT_DATASET_PATH` 注入）。

**成功标准**（供下轮验收）：
1. Leakage Gate PASS（候选已单独验证）；
2. Overall EX ≥ 90.0%（**不下降**）；
3. E-0082 / E-0083 / E-0090（3 题）中目标修复 ≥ 1；
4. 非目标 Bad Case 无明显新增（≤ 1 题新失败）；
5. Conditional EX 不下降；
6. 无新增 Provider/Timeout；
7. 记录 Avg/P95 延迟（观察 few-shot 载荷增加的延迟成本）。

**风险**：few-shot 检索 TopK 未命中候选（需 trace 确认 cand_A1/A2 进入 top-3）；示范过拟合（模型照抄结构但套错场景）；单个候选挤掉原有有用示例（TopK 有限）→ prompt 长度/检索干扰。

### Candidate E11（次优）

**假设**：加入"订单粒度先聚合再 JOIN 明细（防 fan-out)"+"阈值前置过滤后再算第二层平均"两条结构示范 → E-0086（金额 4.1× 放大）与 E-0095（平均基准被稀释）至少 1 题修复。

**变量**：Few-shot = 正式 23 条 + `cand_C1 + cand_C2`。

**成功标准**：同 E9（目标改为 E-0086 / E-0095，其余同）。

**风险**：E-0086 的用户维度与 cand_C1 的地区维度检索命中不确定（表/字段重合度见 §5 命中性）；两阶段结构示范可能被模型"表面模仿"但 JOIN 键错位；非目标回归。

### Candidate E8（可行但优先级 ≤ E9/E11）

**假设**：生成后对输出列形状（+列引用）做纯静态校验 + sidecar 契约 → 缺列类错误在执行前拦截，触发 Repair/重建 → E-0082/0083/0090(列) 修复。

**变量**：新增 `check_output_shape` 函数接通（模拟：用 eval runner 的 repair 触发），契约来自独立 sidecar `contracts_e8.json`。

**成功标准**：拦截缺列 SQL（E-0082/83 的 1 列版本被拦截）→ Repair 后 EX 提升；P1 别名校验对 100 题**零误报**（不拦截任何正确 SQL）；目标修复 ≥ 1；Overall EX 不下降。

**风险**：契约失真误拦（小心）；Repair 触发率上升导致延迟上升；sidecar 契约覆盖不全。

### Candidate E10（否决为本轮实验）

**不建议进入本轮 100 条实验**，理由（reanalysis §B）：
- E-0077 根因是 **Schema Linking 缺 order_items**（模型无法引用 subtotal），few-shot 示范无法绕过硬约束；
- E-0096/E-0100 根因是 **Gold 金额口径与正式 Prompt V1.3 冲突**（模型按规则使用 subtotal 反被判错），few-shot 无法同时满足两向；
- 因此 E10 的目标集合为空；若强行加 B 候选，只会在未来"基准口径仲裁"后才能验证 — 标记 **REVISE（待基准口径确定后重启）**。

---

## 3. 实验卫生要求（所有候选共用）

1. 至少 100 条完整评测（禁止 --limit / 手工跳过 / 删除样本）；
2. 与 Clean Baseline 使用**同一** Benchmark v1.1 / DB（seed 20260914）/ Model mimo-v2.5-pro / Runner `scripts/run_eval.py`；
3. `SQLGEN_EXTRA_RULES` 不启用；不改 Prompt；不改 Benchmark；不改 DB；不改 Agent Graph/Schema Linking/Repair；
4. 记录完整指纹：dataset_sha256 / prompt_sha256（V1.3）/ fewshot_sha256（**临时候选集也有自己的 sha256**）/ db_sha256（前后校验）；
5. **每候选 ≥2 次运行**（Mimo 随机性），报告次数、均值与波动；
6. 评估指标至少：Overall EX、Conditional EX、目标 Bad Case 修复率、非目标 Bad Case 回归数、Provider/Timeout 数、Avg/P95 latency；
7. 新实验目录独立（`reports/eval/e9_output_shape_fewshot/` 等），不得覆盖 `clean_baseline_v1_1/` 与历史实验目录。

---

## 4. 不进入本轮实验的方向（记录）

- **E10（金额语义）**：REVISE（等待基准口径仲裁），理由见 §2 E10；
- **E-0077 修复**：属于 Schema Linking 覆盖（orders 未关联 order_items），移至"面向 Schema Linking 的独立实验域"，不在 E8-E11；
- **E-0096/E-0100**：属于 Benchmark Gold 口径审议（与 Prompt V1.3 冲突），**先例**:需总顾问确认是否升级 v1.1.1 或调整口径规则；不是 Few-shot/校验能修；
- **E-0057（CASE 边界）**：单例 + 已证 E7 规则无效，标记 low priority / continue_observe；
- **E-0099（Repair）**：continue_observe（1 例），仅作为 E8 P1 附带验证点。

---

## 5. 检索命中性预估（E9/E11 复用现有规则型 Retriever）

| 候选 | 目标题 | 命中预期 | 依据 |
|---|---|---|---|
| cand_A1 | E-0082/E-0083 | 高 | 关键词"销售额/占比/分类"齐备；tables/columns 高度重合 |
| cand_A2 | E-0090 | 中 | 关键词"订单/金额"符合；但 E-0090 是 status 维度 vs 候选 region 维度，表仅 orders 重合 |
| cand_C1 | E-0086 | 中低 | 维度（region vs user）不同；表 users/orders/order_items 与用户维度不完全一致 |
| cand_C2 | E-0095 | 中高 | 4 表全重合；关键词"销售额/平均"符合；但统计实体（分类 vs 地区-分类组合）不同 |

> 若命中不足，**禁止**为了命中而修改正式 Retriever；应对方案=设计候选时补充与目标题同维度的变体（本任务只做 2 条/类上限，若命中失败则记录为"下一轮候选迭代"，不改正式）。