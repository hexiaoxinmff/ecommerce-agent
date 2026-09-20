# Task 15 · ECO-SQL-Bench v1.1 正式 Clean Baseline

> 本报告是 **ECO-SQL-Bench v1.1 + SQLGENERATOR_PROMPT_V1.3 + FEWSHOT_V3 的 Clean Baseline**。
> 不做任何优化；Task 13 / 14.1 / 14.2 历史结果（Baseline 72% / E1 88% / Stability / E2 91% / E4 85% / E5 85% / E6 81% / E7 79%）
> 因 Task 14.3 已确认存在 Few-shot 泄漏、Benchmark Gold 缺陷等卫生问题，**不得作为本基线直接比较基准**。

- 时间：2026-09-16T02:44:36Z
- 模式：full / 串行 / 100 条
- Runner：`scripts/run_eval.py`（运行前已通过 Leakage Gate + Gold Hash Gate）

---

## 1. 实验配置（实验指纹）

| 组件 | 值 |
|---|---|
| Benchmark | ECO-SQL-Bench **v1.1**（100 条） |
| dataset_sha256 | `DBA277CC0BE7CC282DF67C86DD7EABFEA1337458612A86885F6DAEF0C6829F1A` |
| DB | dev-2026-09-14 / schema 1.0 / **seed 20260914** |
| db_sha256（运行前） | `65E5D8B2727CFA064174F9A08AA7D4B08209E0EDD1EBA81F3155698F1A4491D9` |
| db_sha256（运行后） | `65E5D8B2727CFA064174F9A08AA7D4B08209E0EDD1EBA81F3155698F1A4491D9`（**未变 PASS**） |
| DB 行数 | users=2000 / categories=30 / products=500 / orders=10000 / order_items=30457 |
| Prompt | **SQLGENERATOR_PROMPT_V1.3**（快照 `data/prompts/sql_generator_v1.3.txt`） |
| prompt_sha256 | `10583478b3a7d972865050501cd6e4b9062531503f1c3852cdd79cbf66f796d5` |
| SQLGEN_EXTRA_RULES | **未启用**（无 E4~E7） |
| Few-shot | **FEWSHOT_V3**（23 条，`data/fewshot/ecommerce_examples.json`） |
| fewshot_sha256 | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` |
| Leakage Gate | PASS（FEWSHOT_V3 ↔ Benchmark v1.1 无泄漏） |
| Model / Provider | mimo-v2.5-pro / mimo（base_url https://api.xiaomimimo.com/v1） |
| 执行器 | app.sqlexec.executor（只读）+ SQL Safety 校验 |
| 超时 | 60s/题 |

## 2. 前置卫生检查

| 检查 | 结果 |
|---|---|
| Benchmark Validator | PASS（100 条结构合法） |
| Gold Hash Gate | PASS（100/100 重算一致） |
| Leakage Gate | PASS |
| pytest | PASS（357 passed） |
| DB SHA256 前后一致 | PASS |

## 3. 总体结果（100 条）

| 指标 | 值 |
|---|---|
| total | 100 |
| valid_model_runs | 100 |
| **overall EX** | **90.0%** |
| **final EX** | **90.0%** |
| Conditional EX（分母=valid_model_runs） | 90.0% |
| overall_exec_rate（分母=total） | 99.0% |
| valid_run_exec_rate（分母=valid_model_runs） | 99.0% |
| Pass@1（初始） | 90.0% |
| provider_failures | **0** |
| timeout | **0** |
| model_generation_failure | 0 |
| sql_safety_error | 0 |
| sql_execution_error | 1（E-0099） |
| result_mismatch | 9 |
| Repair Trigger Rate | 1.0% |
| Repair Success Rate | 0.0% |

> 说明：`overall_exec_rate` 与 `valid_run_exec_rate` 在 `evaluation/metrics.py` `aggregate()` 中按双口径计算；本轮 valid=total=100，两值均为 99.0%。runner JSON/MD 落盘摘要仅输出单一 `exec_rate` 字段（记录项，非本任务修复范围）。

## 4. 按难度

| difficulty | count | EX% | 执行率% |
|---|---:|---:|---:|
| easy | 25 | 100.0 | 100.0 |
| medium | 30 | 100.0 | 100.0 |
| hard | 30 | 86.67 | 100.0 |
| extra_hard | 15 | 60.0 | 93.33 |

## 5. Latency

| 指标 | 值 |
|---|---|
| Avg | 10876.08 ms（总耗时 1090.5s） |
| P50 | 10488.92 ms |
| P95 | 15440.79 ms |

## 6. Failure Stage

| failure_stage | count |
|---|---:|
| none（正确） | 90 |
| result（结果不等价） | 9 |
| sql_repair | 1 |

错误类型：result_mismatch × 9；`SQL 执行失败: no such column: r.region`（E-0099，sql_repair 阶段） × 1。无 provider、无 timeout、无 sql_safety、无 schema_link/fewshot/sql_generate 级失败。

## 7. Bad Case 清单（全部 10 条，EX=false）

| # | eval_id | difficulty | stage | error_type | pred 可执行 | latency(ms) |
|---|---|---|---|---|---|---|
| 1 | E-0057 | hard | result | result_mismatch | 是 | 10139.2 |
| 2 | E-0077 | hard | result | result_mismatch | 是 | 9657.0 |
| 3 | E-0082 | hard | result | result_mismatch | 是 | 12994.9 |
| 4 | E-0083 | hard | result | result_mismatch | 是 | 15440.8 |
| 5 | E-0086 | extra_hard | result | result_mismatch | 是 | 13260.6 |
| 6 | E-0090 | extra_hard | result | result_mismatch | 是 | 9448.4 |
| 7 | E-0095 | extra_hard | result | result_mismatch | 是 | 15013.1 |
| 8 | E-0096 | extra_hard | result | result_mismatch | 是 | 13182.5 |
| 9 | E-0099 | extra_hard | sql_repair | `no such column: r.region` | 否（执行错误） | 25796.6 |
| 10 | E-0100 | extra_hard | result | result_mismatch | 是 | 15572.4 |

### 7.1 逐条详情（question / gold / pred / expected / actual / normalized comparison）

**E-0057**（hard）
- question：按用户累计下单次数将用户分为三档（1-3单、4-10单、11单及以上），各档分别有多少用户？
- gold_sql：三档分组计数（列 tier, user_count）
- pred_sql：`CASE WHEN order_count BETWEEN 1 AND 3 THEN '1-3单' ...` 子查询 COUNT
- expected：3 行（1-3单=490，4-10单=1474，11单及以上=19；合计 1983）
- actual：3 行（1-3单=490，4-10单=1474，11单及以上=**36**；合计 2000）
- normalized comparison：**结果集合不一致**（用户计数口径差异）

**E-0077**（hard）
- question：2025年各收货地区的非取消订单销售额中，高于各地区平均销售额的地区有哪些？（请给出地区名称与销售额）
- gold_sql：`SUM(total_amount)` 口径，7 行；广东 1690745.96 等
- pred_sql：`SUM(total_amount)` + 整体 AVG 比较，7 行；广东 1592437.35 等
- normalized comparison：**结果集合不一致**（各地区销售额值级不同 → 平均阈值/汇总窗口口径差异）

**E-0082**（hard）
- question：休闲零食类别在全部非取消订单明细中的销售金额占全平台商品销售总额的比例是多少？（百分比，保留两位小数）
- gold_sql：返回 2 列（`c.name`, `pct`），值 0.81
- pred_sql：返回 1 列（`percentage`），值 0.81
- normalized comparison：**列数不一致（gold=2 pred=1）**——数值一致但输出形状缺类别名列

**E-0083**（hard）
- question：2025年第四季度中，家用电器类目销售金额占该季度全部商品销售金额的比例是多少？（百分比，保留两位小数）
- gold_sql：2 列（`c.name`, `pct`），值 28.98
- pred_sql：1 列（`percentage`），值 28.98
- normalized comparison：**列数不一致（gold=2 pred=1）**

**E-0086**（extra_hard，Task 14.3 修复题）
- question：累计消费金额超过全平台用户平均累计消费2倍、且累计下单超过8笔的用户有哪些？（请给出用户名、累计金额、订单数与购买商品种数）
- gold_sql（v1.1 新 Gold，双 CTE 防 fan-out）：46 行，黄冬梅 total_spent=89397.46 / 10单 / 31 SKU ✓
- pred_sql：单 JOIN 直接 `SUM(o.total_amount)`（orders×order_items fan-out），43 行，黄冬梅 total_spent=**369854.65**（4.1x 膨胀）、曾国栋 294744.79、杨文 244084.57
- normalized comparison：**结果集合不一致**——模型在量上复现了旧版 fan-out 缺陷（Gold 已修复，模型未修复）

**E-0090**（extra_hard）
- question：2025年各订单状态下，实付金额高于5000元的高金额订单数与5000元及以下的普通订单数分别是多少？（含取消订单的结构统计）
- gold_sql：4 列（status, high_cnt, normal_cnt, **total_cnt**），且带 2025 过滤；completed high=474/normal=1960/total=2434
- pred_sql：3 列（status, high_amount_orders, normal_amount_orders），**缺 2025 时间过滤**；completed high=1167/normal=4905
- normalized comparison：**列数不一致（gold=4 pred=3）**；且 pred 未加年份过滤（数值级差异）

**E-0095**（extra_hard，Task 14.3 修复题）
- question：最近30天（2026年8月14日至9月12日）中，有哪些地区-分类组合的销售金额高于30000元、且高于该地区各组合的平均销售金额？（…取前10）
- gold_sql：9 行（含 30000 条件，与题面一致）
- pred_sql：10 行；前 3 行与 gold 相同（江苏/山东/广东 电脑办公），多出 1 行 **山东_家用电器 72746.95**（gold 该组合未达其地区平均线）
- normalized comparison：**结果集合不一致**（pred 多 1 行）

**E-0096**（extra_hard）
- question：2025年环比增速最快的3个月份是哪几个？（请给出月份、当月销售额与环比增速百分比）
- gold_sql：ranking 题（order_sensitive=true），3 行：2025-12（rev 1608091.51 / 33.56%）、2025-05（965099.06 / 14.16%）、2025-10（1327764.13 / 12.62%）
- pred_sql：3 行：2025-12（1675347.91 / 33.30%）、2025-10（1399380.30 / 14.96%）、2025-05（1014819.08 / 14.49%）
- normalized comparison：**排名题集合不一致**（销售额/增速值不同，集合与次序均不等价）

**E-0099**（extra_hard，唯一执行失败）
- question：哪些收货地区中，家用电器类目销售金额占该地区总销售金额的比例高于全平台家电占比？（请给出地区、家电销售额与占比百分比）
- gold_sql：7 行；辽宁 elec_rev=520136.76 / 31.15% 等
- pred_sql：生成 → 执行错误 `no such column: r.region`（别名 r 未定义）→ sql_repair 阶段修复失败，**无有效 pred_sql**
- expected：7 行（地区、家电销售额、占比）
- actual：无（查询执行错误）
- normalized comparison：pred 无法执行（ExecutionError）
- 归类：执行/修复阶段失败（非 provider failure，验证 Conditional EX 分类正确）

**E-0100**（extra_hard）
- question：2025年5月与2月相比：两个月的非取消订单销售额分别是多少，订单量分别是多少，5月销售额相当于2月的多少倍？
- gold_sql：may rev=965099.06 / orders=311；feb rev=775493.74 / orders=212；ratio=1.24
- pred_sql：sales_may=1014819.08 / orders=311；sales_feb=807005.41 / orders=212；ratio=1.26（订单量一致，销售额与倍率不同）
- normalized comparison：**结果集合不一致**

## 8. Task 14.3 修复验证（只验证，不修复）

| 修复项 | 验证结论 |
|---|---|
| E-0086（Gold 防 fan-out） | ✅ 生效。新 Gold 46 行、黄冬梅 89397.46 真实口径；本轮失败系**模型生成侧**仍犯 fan-out（369854.65），与 Gold 无关 |
| E-0095（题面/Gold 一致） | ✅ 生效。题面已含「组合销售金额高于30000元」；本轮失败为 pred 多 1 行，非题面不一致 |
| E-0098（ranking tie-breaker） | ✅ 生效。本轮 E-0098 **EX✓**，Gold 的 `ORDER BY sold DESC, prod_id` 强序 |
| Conditional EX 分类 | ✅ 生效。E-0099（执行/修复失败）未被计入 provider_failure；provider_failures=0，valid_model_runs=100，仅真正 provider/infrastructure 失败才从 valid_model_runs 剔除 |
| Exec Rate 双口径 | ✅ 生效。metrics.py 定义并计算 overall_exec_rate / valid_run_exec_rate（本轮均为 99.0%）；记录：落盘摘要仅写 exec_rate 单一字段 |
| Leakage | ✅ 生效。FEWSHOT_V3 ↔ Benchmark v1.1 Leakage Gate PASS |

## 9. DB / Hash / Leakage / Pytest 验证结果

| 验证项 | 结果 |
|---|---|
| Benchmark validator | PASS |
| Gold hash | PASS（100/100） |
| Leakage Gate | PASS |
| pytest | PASS（357 passed） |
| DB SHA256 运行前后 | 一致（65E5D8B2…1D9） |
| Prompt SHA256 | 已记录（10583478…96D5） |
| Few-shot SHA256 | 已记录（EE12FCC9…4CEE） |
| Dataset SHA256 | 已记录（DBA277CC…9F1A） |
| 独立目录 | `reports/eval/clean_baseline_v1_1/`（已有，历史实验未覆盖） |

## 10. 历史实验可比性说明

- 本结果定义为：**ECO-SQL-Bench v1.1 + SQLGENERATOR_PROMPT_V1.3 + FEWSHOT_V3 的 Clean Baseline = 90.0% EX**。
- Task 13/14.1/14.2 全部历史结果（Baseline 72%、E1 88%、Stability、E2 91%、E4 85%、E5 85%、E6 81%、E7 79%）**不得作为本基线直接比较基准**：它们基于泄漏 Few-shot、含缺陷 Gold（E-0086 fan-out、E-0095 题面不一致、E-0098 tie 风险）与不良 Conditional EX 分类。
- 历史结果仅作为背景参考保留于 `reports/eval/legacy_experiments_notice.md`；**不计算任何「本轮 − 历史」的提升值**。

## 11. 下一阶段建议（等待总顾问决策，本任务不执行）

1. 基于本 Clean Baseline（90.0%）的 Bad Case 集合（10 条）决定优先级，建议优先分析与修复 3 个系统性信号的方向（不归因到题）：
   - 金额口径差异（E-0077/E-0096/E-0100，销售额/增速值级差异）
   - 输出形状缺失列（E-0082/E-0083 缺类名列、E-0090 缺 total_cnt 列）
   - 聚合粒度/fan-out（E-0086）与过滤遗漏（E-0090 缺 2025 过滤）
2. 补齐 runner 落盘 `summary` 的 exec_rate 双口径输出字段（记录项）。