# Task 36 — Real Mimo E2E Benchmark

> 完成时间：2026-09-20
> 状态：**COMPLETE**
> Provider：**AVAILABLE**（新 API Key 已在本次会话提供并仅经环境变量注入）

---

## 1. Objective

补齐 Task 36 之前唯一缺失的证据：

> 使用真实 Mimo `mimo-v2.5-pro` 跑冻结的 100 题 Benchmark，测量 Candidate A
> 进入 master 后的真实端到端表现。

回答：SQL Execution Accuracy / EX / Exec / Average E2E latency / P50 / P95 /
Provider latency / Non-LLM latency，并检查任务书 **平均 E2E ≤ 8s** 门槛。

---

## 2. Runtime Configuration

| 项 | 值 |
|---|---|
| provider | `mimo` |
| model | `mimo-v2.5-pro` |
| endpoint identifier | `https://api.xiaomimimo.com` |
| temperature | `0.0` |
| timeout | `60.0 s` |
| SDK max_retries | `0` |
| API Key | **仅经环境变量 `MIMO_API_KEY` 注入单次进程，未写入任何文件** |
| api_key_recorded | `false` |
| Python | `3.12.10`（项目 `.venv`） |
| git baseline | `35a9ad6`（未变动） |

**Key 注入方式**：`export MIMO_API_KEY=<key>` 仅作用于该次 shell 进程；
`.env` **未被修改**（`git status` 无相关变更）。

---

## 3. Provider Availability

| 阶段 | 题数 | 结果 |
|---|---|---|
| Smoke 1（E-0001） | 1 | `mode=MEASURED`，`ok=True`，2 provider calls，15296.32 ms |
| Smoke 2（E-0002~0004） | 3 | `mode=MEASURED`，3/3 成功 |
| **正式全量** | **100** | **`mode=MEASURED`，100/100 成功，200 provider calls** |

```text
Provider:
  AVAILABLE

HTTP status = success     ✅
model = mimo-v2.5-pro     ✅
API key accepted          ✅
provider_failures = 0     ✅
timeouts = 0              ✅
```

> ⚠️ 附带发现：**现有 `.env` 中的旧 Key 仍返回 402**（smoke 实测
> `LLMInsufficientBalanceError / upstream_http=402`）。本次使用的是新 Key。
> **未修改 `.env`**，因此下次直接跑脚本仍会因旧 Key 而 402 —— 需使用者自行更新。

---

## 4. Benchmark Dataset

```text
data/eval/ecommerce_eval_v1.json
（= reports/eval/clean_baseline_v1_1/eval_clean_baseline_v1_1.json 所用同一冻结题集）
```

| 项 | 值 |
|---|---|
| 题数 | 100（全部，未挑题、未排除困难题） |
| Dataset SHA256 | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a`（**MATCH**） |
| DB SHA256 | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9`（**MATCH**） |
| 数据库未修改 | `PASS`（runner 自检） |
| 难度分布 | easy 25 / medium 30 / hard 30 / extra_hard 15 |

**精度评测使用冻结驱动** `scripts/run_eval.py` + `evaluation/runner.py` +
`evaluation/normalization.py`，与 clean baseline 完全同一套 EX 判定逻辑（未重新实现）。

---

## 5. Per-Query Results

完整逐题数据见 `reports/eval/task36_real_e2e/`：

| 文件 | 内容 |
|---|---|
| `eval_20260920_26671.json` | **冻结驱动权威输出**（含 EX/Exec/延迟/trace） |
| `eval_20260920_26671.md` | 冻结驱动 Markdown 摘要 |
| `task36_real_e2e_100.json` | Task 36 延迟 harness 输出（含 provider / non-LLM 拆分） |

每题字段均含：

```text
eval_id, success, exception_class, upstream_http_status,
provider_latency_ms, agent_non_llm_latency_ms, total_e2e_latency_ms,
sql_success, repair_triggered
```

**API Key 未出现在任何字段**（见 §14 扫描结果）。

---

## 6. Execution Accuracy

| 指标 | 值 |
|---|---|
| **EX** | **91.0 %** |
| **Exec Rate** | **100.0 %** |
| Conditional EX | 91.0 % |
| Pass@1（初始） | 91.0 % |
| Repair Trigger Rate | 0.0 % |
| Repair Success Rate | 0.0 % |
| Valid Model Runs | 100 / 100 |
| Provider Failures | **0** |
| Timeouts | **0** |

**91 / 100 题完全正确**；9 题结果不匹配。

---

## 7. E2E Latency

冻结驱动口径（**all attempts**，n=100）：

| 指标 | 值 |
|---|---|
| **mean_e2e_ms** | **9720.06** |
| **median_e2e_ms** | **8734.92** |
| **P50_e2e_ms** | **8771.57** |
| **P95_e2e_ms** | **15712.12** |
| min_e2e_ms | 6323.49 |
| max_e2e_ms | 18544.01 |

Task 36 harness 口径（n=100，含冷启动首题）：

| 指标 | 值 |
|---|---|
| mean | 10288.58 |
| median | 9437.71 |
| P50 | 9443.45 |
| P95 | 13426.80 |
| min | 4563.67 |
| max | **69294.27**（首题冷启动，含进程/图编译/连接预热） |

排除冷启动首题（n=99）：mean **9692.56**、median 9431.97、P50 9431.97、P95 13420.79。

> **口径说明**：两个 harness 的差异**完全来自首题冷启动离群值**（69.3 s）。
> 冻结驱动的 `min=6323.49` 明显高于 harness 的 `min=4563.67`，说明两次运行
> 的 warm-up 处理不同。**本报告以冻结驱动口径为准**（与 clean baseline 同源可比）。

**延迟分布（n=100，harness 口径）**

| 区间 | 题数 |
|---|---|
| < 5 s | 1 |
| 5–8 s | 13 |
| 8–10 s | 49 |
| 10–12 s | 23 |
| 12–15 s | 13 |
| ≥ 15 s | 1 |

**仅 14 / 100 题落在 8 s 以内。**

---

## 8. Provider Latency

来自 Task 36 harness（provider 调用累计墙钟）：

| 指标 | 值 |
|---|---|
| mean_provider_ms | **10264.16** |
| median_provider_ms | 9415.99 |
| P50_provider_ms | 9418.43 |
| P95_provider_ms | 13385.99 |
| min_provider_ms | 4543.91 |
| max_provider_ms | 69239.76 |

| 指标 | 值 |
|---|---|
| mean_non_llm_ms | **24.43** |
| median_non_llm_ms | 21.09 |
| P50_non_llm_ms | 21.19 |
| P95_non_llm_ms | 42.22 |
| min_non_llm_ms | 16.34 |
| max_non_llm_ms | 99.85 |

**决定性拆分**：

```text
provider 占比 : 99.76 %
non-LLM 占比  :  0.24 %
```

**每题 provider 调用数**：100 题**全部为 2 次**（`schema_link` + `sql_generate`），
**0 题触发 repair** —— 与冻结驱动的 `Repair Trigger Rate: 0.0%` 一致。

`trace[schema_link]` 单节点均值 **4769.06 ms**（约占 provider 总量的 46%）。

---

## 9. Failure Analysis

**9 题失败，全部同一签名**：

```text
exec_success = True
failure_stage = result
error_type    = result_mismatch
repair_triggered = False
```

即：**SQL 均成功执行，但返回结果与 Gold 不一致** —— 属**语义错误**，非基础设施故障。

| 分类 | 题数 |
|---|---|
| provider / auth | **0** |
| provider / balance | **0** |
| rate limit | **0** |
| timeout | **0** |
| network | **0** |
| LLM output（语义错误） | **9** |
| SQL generation | 0 |
| SQL safety | 0 |
| SQL execution | 0 |
| repair | 0 |

**难度分布**：hard 4 / extra_hard 5 —— **失败全部落在 hard 与 extra_hard**，
easy 与 medium 全对。

| eval_id | 难度 | 问题 | 错误性质 | total_latency |
|---|---|---|---|---|
| E-0057 | hard | 三档用户分层计数 | CASE 边界（`BETWEEN 1 AND 3` vs `cnt<=3`） | 9093.31 ms |
| E-0077 | hard | 高于地区平均销售额的地区 | 用 `orders.total_amount` 而非 `SUM(oi.subtotal)`，且未 JOIN `order_items` | 10629.41 ms |
| E-0082 | hard | 休闲零食占比 | 分母口径不同（未限定非取消订单范围） | 15753.79 ms |
| E-0083 | hard | 家用电器 Q4 占比 | 分母未按季度过滤 | 16305.76 ms |
| E-0086 | extra_hard | 高价值用户筛选 | 统计口径与 `status != 'cancelled'` 处理差异 | 14860.31 ms |
| E-0090 | extra_hard | 高金额订单结构统计 | 取消订单结构处理不同 | 10926.76 ms |
| E-0095 | extra_hard | 地区-分类组合筛选 | 分母平均口径不同 | 15712.12 ms |
| E-0096 | extra_hard | 环比增速最快 3 个月 | 销售额取 `SUM(oi.subtotal)` vs `SUM(total_amount)` | 12127.69 ms |
| E-0098 | extra_hard | 每分类销量 Top3 | 并列排名处理不同 | 11367.00 ms |

> 9 题中至少 3 题的**主因是 `total_amount` vs `SUM(oi.subtotal)` 的金额口径选择**
> （E-0077 / E-0096，及 E-0082 分母口径）。这是**模型语义选择**问题，
> **不属于本任务改动范围**（未修改 Prompt / Few-shot / SQL 生成）。

---

## 10. 402 Error Classification Regression

**本次运行未发生任何 402**（`provider_failures = 0`），因此：

```text
402 Classification:
  NOT_OBSERVED
```

但在 smoke 阶段用**旧 `.env` Key** 触发了一次真实 402，**回归验证成立**：

```text
exception_class     = LLMInsufficientBalanceError    ✅
upstream_http_status = 402                            ✅
```

**未出现**：

```text
❌ LLMServiceUnavailableError
❌ upstream_http_status = 503
```

Task 36 的核心回归在真实 HTTP 402 上得到确认。

---

## 11. Baseline Comparison

| 指标 | 冻结 Baseline | 本次运行 | Observed difference |
|---|---|---|---|
| EX | 90.0 % | **91.0 %** | **+1.0 pp** |
| Exec | 99.0 % | **100.0 %** | **+1.0 pp** |
| Avg E2E | 10876.08 ms | **9720.06 ms** | **−1156.02 ms（−10.63 %）** |
| P50 | 10488.92 ms | **8771.57 ms** | **−1717.35 ms（−16.37 %）** |
| P95 | 15440.79 ms | **15712.12 ms** | **+271.33 ms（+1.76 %）** |

历史冻结指标（题面已给定）：

```text
Baseline:
EX = 90.0%
Exec = 99.0%
Avg E2E = 10876.08 ms
```

> ⚠️ **纪律**：两次运行的 provider、运行环境、时刻、题目执行顺序/热状态均不同
> （基线 run `20260916_09876` vs 本次 `20260920_26671`）。因此上表**只报告
> Observed difference**，**不把差值归因于 Candidate A**。
> **未写** `Candidate A improved E2E by X%` —— 无严格配对实验依据。

---

## 12. 8-Second Target

```text
mean_e2e_ms = 9720.06 ms
8s (8000 ms) target:
  FAIL
```

| 口径 | mean | 判定 |
|---|---|---|
| 冻结驱动（all attempts, n=100） | 9720.06 ms | **FAIL** |
| Task 36 harness（n=100，含冷启动） | 10288.58 ms | **FAIL** |
| Task 36 harness（排除冷启动, n=99） | 9692.56 ms | **FAIL** |

**三种口径均 FAIL。** 即使剔除冷启动离群值，均值仍为 9.69 s，高于 8 s 门槛约 21 %。

**all-attempts vs successful-only**：本次 100 题**全部为 valid model run 且 exec 成功**，
两组样本完全重合（n=100），故 **all-attempts latency == successful-only latency = 9720.06 ms**。
无失败题被当作 0 ms 计入。

**根因**：provider 时延占 99.76 %，而 8 s 门槛的达成**只能靠降低 LLM 时延**，
不是靠消除本地开销。

---

## 13. Candidate A Interpretation

本次数据对 Candidate A 给出**明确但有限的**结论：

**Candidate A 消除的是「每请求重复构造」的本地开销** —— 图编译、SchemaCatalog
的 12 条 SQLite 连接、OpenAI 客户端重建、重复 sqlglot 解析。

实测该部分总计：

```text
mean_non_llm_ms = 24.43 ms   （占总 E2E 的 0.24 %）
```

即便把这块**全部归零**，mean E2E 也只能从 9720.06 ms 降到约 **9695.63 ms**
（−24.43 ms，**−0.25 %**），**仍然远高于 8 s 门槛**。

因此：

- ✅ Candidate A **确实有效**：本地确定性开销已从 29.074 ms 压到 1.955 ms（Task 29/35，本地口径）。
- ❌ Candidate A **不可能**把 E2E 带进 8 s：它对总时延的**理论最大贡献约 0.25 %**。
- ⚠️ 本次观察到的 −10.63 % 平均延迟差异**不能归因于 Candidate A**（无配对实验，
  且 provider 侧波动量级远大于 24 ms）。

**要达成 8 s，必须作用于 provider 时延**（约 9.7 s 中的 9.7 s），
可选方向（**均未实施，仅作为结论陈述**）：模型/推理档位选择、流式首字节、
提示压缩、调用合并（当前每题 2 次调用）、provider 侧缓存。
这些**超出本任务范围**，且不得在无配对实验的情况下宣称收益。

---

## 14. Limitations

| # | 限制 |
|---|---|
| L1 | **8 s 门槛 FAIL**（9720.06 ms）。这是实测结论，未做任何美化。 |
| L2 | 基线对比是**跨运行对比**，provider 与运行环境不同 → 只报 Observed difference，不归因。 |
| L3 | 两次运行的 warm-up 处理不同（首题 69.3 s 冷启动出现在 harness，未出现在冻结驱动），导致 mean 口径存在约 570 ms 差异；**以冻结驱动为准**。 |
| L4 | 单次运行，无多轮重复；P95 受单次波动影响。 |
| L5 | `repair_trigger_rate = 0.0 %`，本次未产生任何 repair 样本，无法评估 repair 路径性能。 |
| L6 | provider 时延占 99.76 %，其波动主要来自上游推理负载，**非本地可控**。 |
| L7 | 9 题失败全为语义错误（`result_mismatch`），归因于模型 SQL 语义选择；本任务**未**修改 Prompt/Few-shot/生成逻辑，故未尝试修正。 |
| L8 | **旧 `.env` Key 仍为 402**；本次仅经环境变量注入新 Key，`.env` 未改。后续复现需自行更新 Key。 |
| L9 | Task 36 harness 的 `repair_triggered` 恒为 `False`（读取的字段与 AgentResult 实际暴露不一致），**以冻结驱动的 `Repair Trigger Rate` 为准**（亦为 0.0 %）。 |

---

## 15. Frozen Assets

| 资产 | SHA256 | 结论 |
|---|---|---|
| Prompt V1.3 | `2af938be9866a62a97fdc3f1b0c7dc43b0785a7ff75ad420109b1d18ed39dc4c` | **MATCH** |
| Few-shot FEWSHOT_V3 | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` | **MATCH** |
| Dataset | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` | **MATCH** |
| DB | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9` | **MATCH** |
| Clean Baseline | `39404fedef84b338cc7b48ed2972db98c7c574cd8cfca196ca02f7843e42f66e` | **MATCH** |

**Candidate A 五源**（与 Task 36 结束时逐字节一致）：

| 文件 | SHA256 |
|---|---|
| `backend/app/agent/graph.py` | `9d09cbae3de49521cef242e106e967b8065aa368c9a6dcc0183b16503d14a25b` |
| `backend/app/schema/metadata.py` | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` |
| `backend/app/llm/mimo.py` | `c228e119b3525bbca8e90e647cff97ff14f0e6763316894375841509d2ac7e09` |
| `backend/app/sqlgen/safety.py` | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` |
| `backend/app/sqlgen/validator.py` | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` |

**Overall: MATCH**

### API Key 安全检查

```text
本次新增全部产物 + 全仓库 git 内容：全文扫描 "sk-<长串>" → 0 命中
.env：未修改
git status：无 Key 相关变更
```

**API Key Leakage: NONE**

### 三者严格分开

| 证据层 | 数值 | 说明 |
|---|---|---|
| Historical（Task 29） | client reuse ≈ 836 ms/call | 历史 provider 支撑 |
| Local deterministic（Task 29/35） | 29.074 ms → 1.955 ms | 本地确定性 |
| **This Task real E2E** | **mean 9720.06 ms / P50 8771.57 / P95 15712.12** | **本次真实 Mimo 运行** |

**三者未合并成任何单一百分比。**

---

## 交付物

| 文件 | 说明 |
|---|---|
| `reports/task36_real_e2e_result.md` / `.json` | 本报告 |
| `reports/eval/task36_real_e2e/eval_20260920_26671.json` | 冻结驱动权威结果（EX/Exec/延迟/trace） |
| `reports/eval/task36_real_e2e/eval_20260920_26671.md` | 冻结驱动摘要 |
| `reports/eval/task36_real_e2e/task36_real_e2e_100.json` | Task 36 延迟 harness 结果（provider/non-LLM 拆分） |
| `data/eval/bad_cases/` | 9 个 bad case 沉淀（冻结驱动产出） |

**未新增任何优化算法；未修改 Prompt / Few-shot / Benchmark / Gold / DB / Candidate A /
Schema Linker / SQL Generate / Safety / Execute / Repair。**
