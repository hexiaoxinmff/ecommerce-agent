# ECO-SQL-Bench 评测集说明

> 副标题：项目自建电商 Text2SQL 评测集
> 维护：TRAE 开发 Agent（与 `docs/evaluation-matrix.md`、`docs/evaluation-dataset-spec.md` 共同权威）

## 1. 数据集基本信息

| 元数据字段 | 值 |
|---|---|
| dataset_name | ECO-SQL-Bench |
| version | **1.1**（Task 14.3 卫生修订版；v1.0 历史见 docs/evaluation-batch-4-review.md） |
| database_version | dev-2026-09-14 |
| seed | 20260914 |
| schema_version | 1.0 |
| generator_version | 1.1 |
| created_at | 2026-09-15（v1.1 修订 2026-09-16） |
| review_status | reviewed |
| 正式题数 | 100（Easy 25 / Medium 30 / Hard 30 / Extra Hard 15） |
| fewshot | FEWSHOT_V3（23 条，无 Benchmark 泄漏，Leakage Gate PASS） |
| prompt | SQLGENERATOR_PROMPT_V1.3（快照见 data/prompts/） |

> **v1.1 修订内容（Task 14.3）**：E-0086 修复金额 fan-out 膨胀；E-0095 题面补「组合销售金额高于30000元」与 Gold 对齐；E-0098 增加排名 tiebreaker（ORDER BY sold DESC, p.id）。其余 97 条 Gold/hash 不变。
> **数据库固定 seed = 20260914**：重新运行 `scripts/init_db.py` 可复现完全一致的 `db/ecommerce.db`，保证 Gold Result 不随数据库重建漂移。任何修改数据库生成逻辑/表结构的行为都必须升级 `database_version` 并重新生成全部 `gold_result_hash`。

## 2. 目录结构

```text
data/eval/
├── ecommerce_eval_v1.json       # 主 Benchmark：单轮题（占位，Task 12 填充）
├── ecommerce_multiturn_v1.json  # 多轮评测组（占位，第二阶段填充）
├── bad_cases/                   # Bad Case 沉淀目录（Task 13/14 起使用）
│   ├── B-0001.example.json      # 结构示例（占位）
│   └── README.md                # Bad Case 结构与 failure_stage 说明
└── README.md                    # 本文件
```

## 3. 规模规划（设计值，详见 docs/evaluation-matrix.md）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 阶段 1 | 100 条高质量单轮（Easy 25 / Medium 30 / Hard 30 / Extra Hard 15） | **全部完成：Batch 1-4 已入集，共 100 条（E-0001~E-0100）** |
| 阶段 2 | 约 200 条单轮 + 约 50~100 条多轮 | 规划中 |
| 最终 | 约 300 条，质量优先于数量 | 规划中 |

## 4. 版本控制规则（禁止覆盖正式集）

- 修改 question 逻辑 / Gold SQL / 数据库结构 → 升级版本（v1.1 / v2.0）；
- 单纯修正 metadata / 拼写 → 允许在原版本内记录 revision，不覆盖历史文件；
- 历史版本只读归档，不删除。

## 5. 数据校验

```bash
python scripts/validate_eval_dataset.py
```

结构校验 + 真实数据库只读执行验证（详见 `docs/evaluation-dataset-spec.md` 与脚本注释）。校验通过前，任何批次题目不得视为"可评测"状态。

## 5.1 自动化评测（Task 13 起）

```bash
python scripts/run_eval.py                  # 完整 100 条评测（串行）
python scripts/run_eval.py --limit 10      # 前 10 条
python scripts/run_eval.py --ids E-0001,E-0026,E-0056,E-0086
python scripts/run_eval.py --difficulty hard
```

- Runner 直接调用真实 Agent（`app.agent.graph.run_agent`），EX 判定复用 `evaluation/normalization.py`（spec §D1~D9 唯一权威）；
- 启动先执行 Gold Hash Gate（100 条重算比对）与 **Benchmark Leakage Gate**（`scripts/check_benchmark_leakage.py`，Few-shot 与 Gold 泄漏即停止），漂移/泄漏即整体停止；
- 报告输出到 `reports/eval/eval_{run_id}.json/.md`（meta 含 prompt/fewshot/dataset 的 sha256 可复现性字段）；失败条目沉淀到 `bad_cases/`（B-1xxx 起）；
- 全部 SQL 只读（`app.sqlexec.executor`），评测前后数据库文件 hash 校验；默认串行；
- Provider 失败按显式分类（LLM 族异常/超时），模型自身生成失败不计入 provider。

## 6. 口径约束（与 database-schema.md 一致）

- `order_items.subtotal` = 明细行金额（line-item amount）；`orders.total_amount` = 订单最终实付金额；两者不等价，差异来自折扣/运费/税费/退款等可解释业务因素。
- 「实际销售」类指标（销售额/销量/客单价等）默认排除 `cancelled`（`WHERE o.status != 'cancelled'`）；订单量、状态分布等结构统计不受此限。