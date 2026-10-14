# Release Manifest — product_baseline_20261014

> Phase 9-16 产品化迭代基线（2026-10-14 提交备份 + 推送远端）
> 基线起点：`db8bfc2`（feat: add Alibaba Cloud Bailian provider）
> 标签：`product_baseline_20261014` → `1e2b781`
> 本文件为 **filter-repo 历史清洗后重生成**（第二版），替代清洗前的首版 manifest。

## 0. 历史清洗记录（2026-10-14）

- 清洗对象：`.workbuddy-ai/memory/2026-09-17.md`（经授权，单文件路径）。
- 引入提交：`560e3a9`（recovery: reconstruct master baseline 2026-09-20，清洗前 hash `518cd89`）。
- 工具：git-filter-repo 2.47.0，`--invert-paths`，仅此一个路径。
- 验证：`git log --all --full-history` 对该路径为空；提交数保持 22；工作树干净。

## 1. 提交清单（11 个基线迭代提交，均为清洗后新 hash）

| # | Hash | Message |
|---|------|---------|
| 1 | `0e922a0` | chore: gitignore 覆盖密钥备份与过程记忆 (20261014) |
| 2 | `eb4e0e9` | phase(9): 第九阶段_正式8000真实业务运行验收 (20261014) |
| 3 | `3006da3` | phase(10): 第十阶段_v1.1产品化运行基础 (20261014) |
| 4 | `81746c6` | phase(11): 第十一阶段_语义契约与本地链路实验(推断归类Task37-72) (20261014) |
| 5 | `d258059` | phase(12): 第十二阶段_Result_First_UI (20261014) |
| 6 | `416f9c4` | phase(13): 第十三阶段_跨数据库迁移验证 (20261014) |
| 7 | `103d87d` | phase(14): 第十四阶段_真实业务落地与Business_Pilot审计 (20261014) |
| 8 | `2beb6ca` | phase(15): 第十五阶段_P0修复与Business_Pilot回归 (20261014) |
| 9 | `f4d21ba` | phase(16): 第十六阶段_Business_Pilot试点总结 (20261014) |
| 10 | `138ff04` | chore: 未归类零散文件 (20261014) |
| 11 | `49b97b8` | phase(10): 补遗_README与前端认证测试 (20261014) |

> 清洗前首版 hash 对照：62e751a / e5f3d9f / 06ddaa3 / 6ca3397 / e56f1c4 / 70f441a / 457db8a / 66ab692 / 449084e / 3d11f14 / c390e7a（已作废，仅存档于本地 reflog 之外不留引用）。

## 2. 文件统计

| 指标 | 值 |
|---|---|
| 基线 `db8bfc2`..HEAD 变更文件总数 | 290 |
| 当前仓库跟踪文件总数 | 1051 |
| 基线迭代提交数 | 11（8 个 phase + 1 个 phase 补遗 + 2 个 chore） |

## 3. 关键文件 SHA256

| 文件 | SHA256 |
|---|---|
| `docs/database-schema.md` | `0fa00f86230f27f3e3ceae1c046fb5f1f98956cb4102df7d074ddc05e9bccc9c` |
| `backend/app/agent/graph.py` | `cb4864b2289f7003f7158bf2912049d63ac058e13cb040c839e14b776e26edf7` |
| `reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` | `6a6a137d7757bc863a310005281341a90d8f8a0eda4384cd8d5c70dba55237e0` |

## 4. 归类说明与偏离记录

1. **阶段名来源**：取自 `reports/phase*/` 目录内报告标题；`reports/phase11` 目录不存在，phase(11) 的名称依 Task 37-72 系列文件与过程记忆（语义契约/E 系列实验）推断，已在提交信息中标注「推断归类」。
2. **修改文件的归属**：59 个已跟踪修改 + 2 个删除按同一 Phase 主题归入对应阶段提交（依据：phase 报告引用 + diff 内容标注，如 graph.py/models.py diff 内明确标注 Phase 15 P0-1/P0-2）。
3. **`_delivery_build/` 产物不入库**：`Text2SQL电商智能数据分析Agent_v1.0.0.zip` 为 126MB，超过 GitHub 单文件 100MB 硬限制；该产物可由 `_delivery_build/assemble.py` 重建，完整性由 `FINAL_ZIP_SHA256_phase8_lock.txt` 锁定。构建脚本与锁定文件已入库，产物目录已加入 `.gitignore`。
4. **`.env.bak.20261014`**（含真实密钥的备份文件）已移出仓库至 `F:\backup\text2sql-env\`，并加入 `.gitignore`；`.env` 本体未做任何改动。
5. **脱敏门禁**：push 前已通过四项 check-ignore 断言、提交文件名审计、密钥值级零命中扫描（清洗后全量重跑，见执行报告）。
