# Task 39-L — Local LLM E2E Benchmark

> **Local LLM result ≠ Mimo production result**
>
> 本报告描述的是**本地大模型工程基准**（engineering benchmark），
> 不是 Mimo 生产基准。本地 EX / 本地延迟**不得**当作生产指标引用。

- 生成时间：2026-09-20
- 产物：`reports/task39_local_llm_e2e.md` / `reports/task39_local_llm_e2e.json`
- 原始逐题证据：`reports/task39_local_llm_e2e.json` → `results[]` / `per_item[]`
- 状态：**LOCAL_BENCHMARK_COMPLETE**

---

## 1. Objective

建立一条与生产链路**完全隔离**的本地大模型测试线路，在 Mimo provider 不可用
（Task 39 实测 HTTP 402）期间，验证下面这条流水线端到端可跑：

```
自然语言问题 → Schema Link → SQL Generate → SQL Safety → SQL Execute → Repair → Result
```

并测量 EX / Exec / SQL Execution Accuracy / mean E2E / P50 / P95 /
provider latency / agent non-LLM latency。

**目标与边界（本任务书 §二）**：Mimo provider 不修改、Mimo API Key 不使用、
Task 39 Real E2E 不覆盖、生产基线不改变。

---

## 2. Local Provider Discovery

只做 localhost 可用性 + `/v1/models` + 模型清单，**未调用 Chat Completion**。

| 探测端点 | 结果 |
|---|---|
| `http://127.0.0.1:11434/v1/models` | **200** |
| `http://localhost:11434/v1/models` | 200 |
| `http://127.0.0.1:1234/v1/models` | connection refused（无 LM Studio） |
| `http://127.0.0.1:8000/v1/models` | connection refused（无 vLLM） |
| `http://localhost:1234/v1/models` | connection refused |
| `http://localhost:8000/v1/models` | connection refused |

- **Local Provider**：Ollama 0.34.1
- **Local Endpoint**：`http://127.0.0.1:11434/v1`（原生服务）
- **API-compatible**：YES（`/v1/models` 正常返回 OpenAI 结构）

### 关键发现：运行中的服务只挂了一个 embedding 模型

`C:\Users\29593\AppData\Local\Ollama\server.log` 记录了服务真实配置：

```
OLLAMA_HOST:http://127.0.0.1:11434   OLLAMA_MODELS:F:\ollama\models
total blobs: 4                        version 0.34.1
```

`F:\ollama\models` 里只有 `nomic-embed-text:latest`（`capabilities: ["embedding"]`）
—— **一个 embedding 模型无法驱动 Text2SQL 流水线**。

但同一台机器上另有模型库（`F:\Ollama_old\models`，10 个 manifest、28 个 blob，
逐 manifest 校验权重**全部完整**），包含 `qwen2.5:7b-instruct`、`qwen7b-opt:latest`、
`qwen3.5:9b` 等 chat 模型。**模型已安装，只是运行中的服务没指向那个库。**

### 处理方式（未下载、未安装任何东西）

起了一个**独立 Ollama 实例**，指向已有模型库，**完全不触碰原生 11434 服务**：

```
OLLAMA_HOST=127.0.0.1:11435
OLLAMA_MODELS=F:/Ollama_old/models
OLLAMA_NOPRUNE=1        # 关闭 prune，避免动到用户已有 blob
```

- 下载模型：**0**
- 安装软件：**0**
- 修改原生服务配置：**无**

---

## 3. Runtime Configuration

| 项 | 值 |
|---|---|
| Local Provider | `Ollama 0.34.1` |
| Local Endpoint | `http://127.0.0.1:11435/v1` |
| Model | `qwen7b-opt:latest`（7.6B, Q4_K_M, caps: completion,tools） |
| API-compatible | YES |
| API Key | 不需要（`api_key_required: false`），本任务未使用任何 Key |
| GPU | NVIDIA RTX 4050 Laptop 6.0 GiB（可用 5.0 GiB） |
| 服务端上下文 `num_ctx` | **4096**（Ollama 按显存推导的默认值；主跑即此设置，见 §5.4） |
| 适配器 | `backend/app/llm/local_provider.py`（**benchmark-only**） |
| 注入方式 | `AgentComponents` 组件注入，**绕过 `get_llm_provider()`** |
| 运行入口 | `scripts/task39_local_benchmark.py`（独立 wrapper） |

**模型选择规则**（任务书 §五）：按 provider 自身返回顺序取**第一个**「已安装 +
可调用 + OpenAI-compatible」的模型，**不按强弱排名**。候选清单见 §5。

---

## 4. Production Isolation

本任务**只新增文件，未修改任何既有文件**：

- 新增：`backend/app/llm/local_provider.py`
- 新增：`scripts/task39_local_benchmark.py`
- 新增：`backend/tests/test_task39_local_provider.py`

### 证据一：既有改动文件 mtime 全部早于本任务

工作树在任务开始前已有 8 个 tracked 改动（Task 36/37/38 未提交成果），
其 mtime **全部为 2026-09-20 19:08**，而本任务从 **19:50** 开始：

```
backend/app/api/routes/llm.py       2026-09-20 19:08:19
backend/app/llm/mimo.py             2026-09-20 19:08:19
backend/app/llm/provider.py         2026-09-20 19:08:19
backend/app/sqlexec/errors.py       2026-09-20 19:08:20
backend/app/sqlexec/executor.py     2026-09-20 19:08:20
backend/app/sqlgen/prompt.py        2026-09-20 19:08:20
backend/app/sqlrepair/validator.py  2026-09-20 19:08:21
evaluation/runner.py                2026-09-20 19:08:21
```

`git diff --stat` 前后一致：`8 files changed, 127 insertions(+), 11 deletions(-)`
（全部是 Task 36/37/38 的既有改动）。

### 证据二：注入路径不经过生产工厂

`get_llm_provider()` 在代码库里**只有 `graph.default_components()` 一处调用**；
本任务显式传入 `AgentComponents`，因此生产工厂路径完全不被触达。

### 红线核对

| 项 | 状态 |
|---|---|
| `get_llm_provider()`（Mimo） | UNCHANGED |
| `mimo.py` | UNCHANGED |
| `LINKER_MODE` | UNCHANGED |
| Candidate A | UNCHANGED |
| Task 36 | UNCHANGED |
| Task 38 / E8 | UNCHANGED |
| Prompt | UNCHANGED |
| Few-shot | UNCHANGED |
| Benchmark | UNCHANGED |
| DB | UNCHANGED |
| `scripts/run_eval.py` | UNCHANGED（冻结语义原样保留） |

> `run_eval.py` **不支持** provider 注入，因此按任务书 §十一 建立了独立 wrapper，
> 而**不是**修改 `run_eval.py`。

---

## 5. Smoke Test

### 5.1 候选清单（candidate inventory，provider 返回顺序）

| # | Model | Params | Quant | Capabilities |
|---|---|---|---|---|
| 1 | medical-expert:latest | 1.8B | Q8_0 | tools, thinking, completion |
| 2 | qwen3-vl:4b | 4.4B | Q4_K_M | completion, vision, tools, thinking |
| 3 | qwen3-embedding:0.6b | 595.78M | Q8_0 | tools, thinking, **embedding**（排除） |
| 4 | qwen3.5:9b | 9.7B | Q4_K_M | completion, vision, tools, thinking |
| 5 | qwen3.5-4b:latest | 4.2B | Q6_K | tools, thinking, completion |
| 6 | tipdm_qwen:latest | 596.05M | Q4_K_M | tools, thinking, completion |
| 7 | qwen3-0.6b:latest | 596.05M | Q4_K_M | tools, thinking, completion |
| 8 | nomic-embed-text:latest | 137M | F16 | **embedding**（排除） |
| 9 | **qwen7b-opt:latest** | **7.6B** | **Q4_K_M** | **completion, tools** |
| 10 | qwen2.5:7b-instruct | 7.6B | Q4_K_M | completion, tools |

### 5.2 可调用性筛选（provider 顺序，只看「可调用」，不比较强弱）

筛选协议：用冻结 benchmark 第 1 题（E-0001）的**真实流水线 prompt** 试跑，
模型必须完成 Schema Linking 且产出通过流水线输出契约校验的 SQL。

**筛选运行时的服务端上下文**：`num_ctx = 4096`（Ollama 按显存推导的默认值，
`server.log`: `total_vram="6.0 GiB" default_num_ctx=4096`）。**该参数是结果的一部分，见 §5.4。**

| Model | 结果 | E2E | 失败原因 |
|---|---|---|---|
| medical-expert:latest | FAIL | 11.4s | `SQLGenOutputInvalidError: tables 必须是字符串数组` |
| qwen3-vl:4b | FAIL † | 116.3s | `SchemaLinkingInvalidError: LLM 输出中未找到 JSON` |
| qwen3.5:9b | FAIL | 300.0s | `LLMTimeoutError`（超出 6GB 显存承载能力） |
| qwen3.5-4b:latest | FAIL | 119.5s | `SchemaLinkingInvalidError: LLM 输出中未找到 JSON` |
| tipdm_qwen:latest | FAIL | 55.4s | `SchemaLinkingInvalidError: 字段必须使用「表名.字段名」格式: id` |
| qwen3-0.6b:latest | FAIL | 2.9s | `SchemaLinkingInvalidError: 字段必须使用「表名.字段名」格式: id` |
| **qwen7b-opt:latest** | **PASS** | 69.9s | — |

† **`qwen3-vl:4b` 在 4096 上下文下的 FAIL 是假阴性**，复核见 §5.4 / 附二。

**结论（本表口径）**：在 `num_ctx = 4096` 的服务端设置下，`qwen7b-opt:latest` 是
provider 顺序中第一个通过可调用性筛选的模型。

> 该筛选是「可调用性」判定，不是「按模型强弱排名」——顺序始终是 provider 自己的顺序。

### 5.3 3 题 Smoke Test 结果（qwen7b-opt:latest）

| 题号 | 结果 | provider calls | provider ms | non-LLM ms | E2E ms |
|---|---|---|---|---|---|
| E-0001 | EX✓ | 2 | 2371.07 | 95.08 | 2466.15 |
| E-0002 | EX✓ | 2 | 3624.26 | 19.02 | 3643.28 |
| E-0003 | EX✓ | 2 | 3371.35 | 19.67 | 3391.02 |

- 全链路验证通过：provider call ✓ / Schema Link ✓ / SQL Generate ✓ /
  SQL Safety ✓ / SQL Execute ✓ / final result ✓
- provider_failures = **0**
- mean E2E = **3166.82 ms**，P50 3391.02，P95 3643.28
- **Smoke Test: PASS** → 允许进入 100 题

### 5.4 复核修订：服务端上下文长度是筛选结果的一部分

> 本节为**交付后自查**追加。它**修订**了 §5.2 的一处表述，
> 但**不改变** §6–§12 的任何数字（100 题仍由 `qwen7b-opt:latest` 跑出）。

自查的触发点：`ollama ps` 显示 `context_length: 4096`，而 E-0001 的 schema_link
prompt 有 4635 字符。若 prompt 被截断，「thinking 系模型不行」就可能是**上下文不足
造成的假象**，而不是模型能力问题 —— 这会直接动摇「第一个可调用模型」的判定。

**实验**：把 E-0001 的**真实** schema_link prompt（4635 字符 / **1516 token**，
即 prompt 本身**未被截断**）用 `/api/chat` 以不同 `num_ctx` 重放：

| Model | num_ctx | prompt_eval | eval | 输出长度 | 输出合法 |
|---|---|---|---|---|---|
| medical-expert:latest | 4096 | 1516 | 372 | 348 | ✓ |
| medical-expert:latest | 16384 | 1516 | 311 | 245 | ✓ |
| **qwen3-vl:4b** | **4096** | 1526 | **2570** | **0** | **✗** |
| **qwen3-vl:4b** | **16384** | 1526 | 2366 | 108 | **✓** |
| qwen7b-opt:latest | 4096 | 1524 | 34 | 93 | ✓ |
| qwen7b-opt:latest | 16384 | 1524 | 34 | 93 | ✓（逐字节相同） |

**机制**：`1526 + 2570 = 4096` **恰好等于** `num_ctx`。`qwen3-vl:4b` 是 thinking 模型，
它把整个上下文窗口消耗在推理链上，留给 `content` 的预算为 0 ⇒ 返回空字符串 ⇒
流水线报 `SchemaLinkingInvalidError: LLM 输出中未找到 JSON`。
**这不是能力不足，是上下文窗口被推理链吃干。**

**复筛**（`OLLAMA_CONTEXT_LENGTH=8192`，其余不变）结果**改变**：

| Model | ctx=4096 筛选 | ctx=8192 筛选 |
|---|---|---|
| medical-expert:latest | FAIL | FAIL（同样错误，与 ctx 无关） |
| **qwen3-vl:4b** | **FAIL** | **PASS**（E2E 232.7s，SQL 41 字符，exec ✓） |
| 第一个可调用候选 | `qwen7b-opt:latest`（#9） | **`qwen3-vl:4b`（#2）** |

产物：`reports/task39_local_screen_ctx8192.json`

**修订后的表述**：

- ⚠️ **「第一个可调用模型」在没有指定服务端上下文长度时不是一个良定义的量。**
  §5.2 的表在 `num_ctx = 4096` 口径下成立；换成 8192，第一个可调用候选变成
  provider 顺序第 2 位的 `qwen3-vl:4b`。
- ⚠️ **thinking 模型「无法驱动本流水线」的说法不准确**。准确的说法是：
  thinking 模型在**上下文预算不足时**会把窗口耗尽在推理链上而返回空 content；
  给足上下文后它们可以产出合法输出。
- ✅ **§6–§12 的 100 题结果不受影响**：那批数据由 `qwen7b-opt:latest` 跑出，
  该模型在 4096 与 16384 下输出**逐字节相同**（见上表），不存在 ctx 混淆。
- ✅ **筛选步骤本身仍然必要**：即使在 8192 下，`medical-expert:latest` 依然 FAIL，
  说明「模型存在 ≠ 模型可用」这条教训成立，只是失败原因需要分开归类
  （能力型失败 vs 上下文型失败）。

### 5.5 第二模型 Smoke（qwen3-vl:4b @ ctx=8192）

为验证上述修订不是纸上推演，用 `qwen3-vl:4b` 跑了同样的 3 题 smoke：

| 题号 | 结果 | provider calls | provider ms | non-LLM ms | E2E ms |
|---|---|---|---|---|---|
| E-0001 | **timeout** | 1 | 300021.04 | 14.38 | 300035.42 |
| E-0002 | EX✓ | 2 | 116232.63 | 32.74 | 116265.37 |
| E-0003 | EX✓ | 2 | 85749.19 | 26.06 | 85775.25 |

- n 3 / success 2 / failed 1 / **provider_failures 1**（E-0001 撞 300s 墙钟）
- EX 66.67%，conditional EX 100.0%
- mean E2E **167358.68 ms**，**Local 8s Target: FAIL**
- **mean non-LLM 24.39 ms**（P50 26.06 / P95 32.74）

产物：`reports/task39_local_llm_e2e_smoke_qwen3vl.json`

**两个独立结论**：

1. **「通过筛选」≠「跑得完全量」**：`qwen3-vl:4b` 通过了单题筛选，但单次调用约 116 s
   （`qwen7b-opt` 约 3.2 s，差 ~36 倍），在较难的 E-0001 上直接撞 300 s 超时。
   若用它跑 100 题，墙钟时间将不可接受 —— 这反过来印证了选择 `qwen7b-opt` 作为
   基准模型的**工程合理性**（注意：这是事后工程判断，**不是**按模型强弱排名）。
2. ⭐ **Agent 自身开销被第二个模型独立复现**：`mean_non_llm` = 24.39 ms
   （vs 主跑的 26.53 ms）。两个模型、两个数量级的 provider 延迟，Agent 非 LLM 开销
   都稳定在 **~25 ms** —— 这是 §9 结论的**交叉验证**，比单模型证据强得多。


---

## 6. Frozen Benchmark

只有 smoke 通过后才执行全量。

| 闸门 | 结果 |
|---|---|
| Benchmark Leakage Gate | PASS（Few-shot 与 Benchmark 无泄漏） |
| Gold Hash Gate | PASS（E-0001~E-0100 重算 100/100 一致） |
| 执行规模 | 100 / 100 题，串行 |
| 数据库未被修改 | PASS（评测前后 sha256 一致） |
| 测量受损题数 | 0（`measurement_compromised_items = 0`） |
| 总墙钟时间 | 571.0 s |

> 评测入口为独立 wrapper `scripts/task39_local_benchmark.py`，复用
> `evaluation.runner.eval_single_item` 与 `EvalConfig`，**未修改 `run_eval.py`**。

---

## 7. Execution Accuracy

| 指标 | Local（qwen7b-opt:latest） |
|---|---|
| n | 100 |
| success（Exec 成功） | 62 |
| failed | 38 |
| provider_failures | **0** |
| valid_model_runs | 100 |
| timeouts | 0 |
| **EX** | **41.0%** |
| **Exec** | **62.0%** |
| **SQL Execution Accuracy** | **41.0%** |
| Conditional EX | 41.0% |
| repair_count（总） | 3（触发 3 题） |

### 按难度

| 难度 | n | EX | Exec |
|---|---|---|---|
| easy | 25 | 22 | 25 |
| medium | 30 | 12 | 20 |
| hard | 30 | 7 | 14 |
| extra_hard | 15 | 0 | 3 |

### 失败分布

| failure_stage | 数量 |
|---|---|
| （无失败，EX✓） | 41 |
| sql_generation | 36 |
| result | 21 |
| sql_repair | 2 |

| error_type | 数量 |
|---|---|
| SQLGenSchemaMismatchError | 26 |
| result_mismatch | 21 |
| SchemaLinkingInvalidError | 10 |
| 未定义的表别名（repair 后仍失败） | 1 |
| SQL 语法错误（repair 后仍失败） | 1 |

**读法**：本地 7.6B 模型的主要瓶颈是**结构化输出契约**（`sql_generation` 36 题，
其中 26 题是 SQL 引用了 Schema Linking 未提供的表）与**语义正确性**
（`result_mismatch` 21 题）。**provider 层面 0 失败** —— 说明流水线本身是健康的，
差的是模型能力。

---

## 8. E2E Latency

| 指标 | E2E（ms） |
|---|---|
| mean | **5695.12** |
| P50 | **5153.82** |
| P95 | **11551.92** |
| min | 1822.72 |
| max | 21336.10 |

分位数口径与冻结基线一致：`sorted[n*q//100]`（非插值）。

---

## 9. Provider Latency

| 指标 | provider latency（ms） | agent non-LLM latency（ms） |
|---|---|---|
| mean | **5668.59** | **26.53** |
| P50 | 5134.42 | 23.68 |
| P95 | 11510.38 | 47.13 |
| min | 1813.70 | 9.02 |
| max | 21264.23 | 92.83 |
| provider calls（总） | 193 | — |

**延迟拆解结论**：`provider latency >> agent non-LLM latency`
（5668.59 ms vs 26.53 ms，provider 占 E2E 的 **99.53%**）。

> **在本地运行环境中，E2E 延迟主要由本地模型推理贡献**，Agent pipeline 自身开销
> 约为每请求 **26.5 ms**（P95 47.1 ms）。
>
> ⭐ **交叉验证（§5.5）**：第二个模型 `qwen3-vl:4b` 的 provider 延迟是
> `qwen7b-opt` 的 ~36 倍，其 `mean_non_llm` 仍为 **24.39 ms**。
> 两个模型、两个数量级的推理耗时，Agent 非 LLM 开销都稳定在 **~25 ms** ——
> 该结论因此不是单模型偶然。
>
> ⚠️ 该结论**只适用于本次本地运行环境**，不得外推到 Mimo 生产链路。

---

## 10. Failure Analysis

- **provider_failures = 0**：没有任何一题因 LLM 层异常（网络/认证/限流/5xx/超时）
  而失败。193 次 provider 调用全部正常返回。
- **主力失败在生成阶段**：36 题在 `sql_generation` 终止，其中
  - 26 题 `SQLGenSchemaMismatchError` —— 模型生成的 SQL 引用了 Schema Linking
    未提供的表（`schema_link` 是本项目的承重墙，link 漏表则该题必然失败）；
  - 10 题 `SchemaLinkingInvalidError` —— 模型连 Schema Linking 的 JSON 契约
    都没满足（这些题只消耗了 1 次 provider 调用即终止）。
    > 这批失败**不是**上下文耗尽：`qwen7b-opt` 是非 thinking 模型，`eval_count` 仅
    > 34 token（见 §5.4），窗口远未用满。它是**能力型失败**，与 §5.4 中
    > `qwen3-vl:4b` 在 4096 下的**上下文型失败**是两类不同机制。
- **21 题结果不等价**（`result_mismatch`）：SQL 能执行，但结果与 Gold 不一致。
- **Repair 路径**：仅 3 题触发（E-0084 / E-0091 / E-0099），**0 题修复成功**。
  其中 E-0091 触发本项目的 SQL Scope 静态校验（`未定义的别名 o: o.id`），
  E-0099 出现 `near "SELECT": syntax error` —— 说明小模型的 Repair 输出质量同样不足。
- **难度单调性**：easy 88% EX → medium 40% → hard 23.3% → extra_hard 0%，
  符合「模型能力不足」的预期形态，而不是流水线缺陷形态。

---

## 11. Local Eight-Second Measurement

| 项 | 值 |
|---|---|
| 判据 | `mean_e2e_ms <= 8000` |
| mean E2E | 5695.12 ms |
| **Local 8s Target** | **PASS** |

⚠️ 这是**本地模型**的测量结果，**不是生产门禁**。
注意 P95 = 11551.92 ms 已超出 8 秒，均值达标不代表尾部达标。

**Mimo 正式生产门禁依然：NOT_MEASURED。**

---

## 12. Comparison with Mimo

### Local LLM

```
Model:  qwen7b-opt:latest (7.6B, Q4_K_M) @ Ollama 127.0.0.1:11435
EX:     41.0%
Exec:   62.0%
Mean:   5695.12 ms
P50:    5153.82 ms
P95:    11551.92 ms
```

### Mimo

```
Current:         HTTP 402 / unavailable
Production E2E:  NOT_MEASURED
```

### 禁止的表述

- ❌ `Local EX = Mimo EX`
- ❌ `Local latency = production latency`
- ❌ 用本报告的 41.0% 或 5695 ms 替换冻结基线（EX 90.0% / mean 10876.08 ms）

**两者不可比**：模型不同（7.6B 本地量化模型 vs mimo-v2.5-pro）、
服务不同、硬件不同、并发条件不同。本报告唯一的用途是
**验证流水线在本地可跑通，并给出 Agent 自身开销的量级**。

---

## 13. Limitations

1. **模型能力是主因，不是流水线**：EX 41.0% 反映的是 7.6B 本地量化模型的能力上限，
   与冻结基线（Mimo，EX 90.0%）之间**没有任何可比性**。
2. **候选筛选是新增步骤，且筛选结论依赖服务端上下文**：任务书 §五 假定「第一个可用
   模型」即可用，实测前 6 个候选无法满足流水线输出契约，因此引入了**按 provider
   顺序的可调用性筛选**。若要求严格「只取第一个候选」，结论将退化为
   `LOCAL_PROVIDER_UNAVAILABLE`。
   ⚠️ 更重要的是：**「第一个可调用模型」在未指定 `num_ctx` 时不是良定义的量**
   （§5.4）。4096 下是 `qwen7b-opt:latest`（#9），8192 下是 `qwen3-vl:4b`（#2）。
   本报告 §6–§12 的全部数字基于 **4096 口径 + `qwen7b-opt:latest`**。
3. **「thinking 模型不可用」的说法已被修订为更精确的机制**：不是能力不足，
   而是**上下文预算不足时推理链吃光窗口、`content` 为空**（§5.4 实测
   `1526 + 2570 = 4096`）。给足上下文后 thinking 模型可以产出合法输出。
4. **「通过筛选」不等于「能跑全量」**：`qwen3-vl:4b` 通过单题筛选，但单次调用
   ~116 s，在 E-0001 上撞 300 s 超时（§5.5）。单题筛选只能证明**可调用**，
   不能证明**可承载 100 题**。
5. **模型选择受启发式限制**：`is_embedding_model()` 只按名称片段判断，
   `bge-m3` 这类不含 "embed" 的 embedding 模型会被漏判（已固化为测试
   `test_name_heuristic_is_not_authoritative`）。权威判据是实测筛选。
6. **8 秒门禁只对均值成立**：P95 = 11551.92 ms 超出 8 秒。
7. **单次运行、无重复**：本报告为单轮测量，未做跨轮重复；
   按本项目既定纪律，**延迟差异默认不归因**，除非有确定性机制解释。
8. **本地服务为隔离实例**：`127.0.0.1:11435` 是本任务临时起的独立实例
   （`OLLAMA_MODELS=F:/Ollama_old/models`），与用户原生 `11434` 服务无关。
9. **未做 token 统计（主跑）**：Agent 未暴露 token 计数，100 题报告不含 token 指标。
   §5.4 的 `prompt_eval` / `eval_count` 来自对 `/api/chat` 的旁路重放，不是主跑统计。

---

## 14. Frozen Asset Verification

| 资产 | 冻结值 | 当前值 | 判定 |
|---|---|---|---|
| Prompt `sha256(BUSINESS_RULES)` | `10583478b3a7d972…` | `10583478b3a7d972…` | **MATCH** |
| Few-shot `sha256` | `ee12fcc994c6afec…` | `ee12fcc994c6afec…` | **MATCH** |
| Benchmark dataset `sha256` | `dba277cc0be7cc28…` | `dba277cc0be7cc28…` | **MATCH** |
| DB `sha256` | — | `65e5d8b2727cfa06…` | 评测前后一致 |
| Gold Hash Gate | — | 100/100 | PASS |
| Leakage Gate | — | 无泄漏 | PASS |

冻结基线参照：`reports/eval/clean_baseline_v1_1/`（run `20260916_09876`，
EX 90.0% / Exec 99.0% / mean 10876.08 ms）—— **本任务未触碰该目录**。

### API Key 安全

扫描 `reports/task39_local*`：

| 项 | 结果 |
|---|---|
| 扫描模式 | `sk-` / `Authorization:` / `Bearer …` |
| 命中 | **0 处凭据** |
| 命中说明 | ① 布尔字段 `"api_key_required": false`；② **本表自身的模式字面量**被自己的扫描命中（本项目已记录的自指陷阱，见 `MEMORY.md §6`） |
| **API Key Leakage** | **NONE** |

本地服务不需要 Key；适配器仅从环境变量 `LOCAL_LLM_API_KEY` 读取，本次未使用。

### 测试

| 项 | 结果 |
|---|---|
| 新增测试文件 | `backend/tests/test_task39_local_provider.py` |
| 新增用例 | 42 |
| 全量套件 | **532 passed** |
| 不含新增文件的基线 | 490 passed |

覆盖：endpoint / model selection / request format / response parsing /
provider latency measurement / unavailable handling / 不影响 Mimo provider。

---

## 15. Final Decision

### Task 36 HTTP 402

```
Task36 402:  NOT_APPLICABLE_TO_LOCAL_PROVIDER
```

本地模型**无法**验证真实 Mimo HTTP 402。**没有**为了模拟 402 而修改本地适配器；
402 的验证继续由 Task 36 的 mock/unit tests 负责
（本任务新增的 `test_402_is_not_service_unavailable` 只验证本地适配器自身的
状态码映射与 Task 36 口径一致，不冒充生产验证）。

### 判断

```
LOCAL_BENCHMARK_COMPLETE
```

依据：本地 provider 可用、smoke 通过、100 题全量跑完、无 provider 失败、
冻结资产全部 MATCH、测试全绿。

### 交付后复核（附二）对最终判断的影响

```
Context-length audit:  COMPLETE
```

审计**修订了 §5.2 的一处表述**（「第一个可调用模型」依赖服务端 `num_ctx`），
但**不改变**本节判断：

| 项 | 是否受影响 |
|---|---|
| `LOCAL_BENCHMARK_COMPLETE` | **不受影响** |
| §7 EX 41.0% / Exec 62.0% | **不受影响**（`qwen7b-opt` 对 ctx 不敏感） |
| §8–§9 延迟指标 | **不受影响**，且被第二模型交叉验证 |
| §5.2 「第一个可调用模型」 | **已修订**：须标注 `num_ctx=4096` 口径 |
| 生产红线 | **不受影响**（审计只读 + 新增脚本） |

### 最终输出

```
Task 39-L COMPLETE

Local Provider:
  Ollama 0.34.1 @ http://127.0.0.1:11435/v1

Local Model:
  qwen7b-opt:latest (7.6B, Q4_K_M)
  [selected at server num_ctx = 4096; at 8192 the first callable
   candidate would be qwen3-vl:4b — see §5.4]

Smoke Test:
  PASS

Benchmark:
  100 / 100

EX:
  41.0%

Exec:
  62.0%

Mean E2E:
  5695.12 ms

P50:
  5153.82 ms

P95:
  11551.92 ms

Local 8s Target:
  PASS

Mimo Production E2E:
  NOT_MEASURED

Mimo:
  HTTP 402 / unavailable

Candidate A:
  UNCHANGED

Production Mimo:
  UNCHANGED

Frozen Assets:
  MATCH

Context-length audit:
  COMPLETE (revised §5.2; 100-item numbers unaffected)

Tests:
  532 passed

API Key Leakage:
  NONE

Status:
  STOPPED
```

---

## 附：本地实例运维说明

本任务临时起的独立实例（`127.0.0.1:11435`）**不修改**用户原生服务。
**任务结束时该实例已停止**（`11435` 已释放；原生 `11434` 仍正常返回 200）。

如需复现（**筛选阶段建议加 `OLLAMA_CONTEXT_LENGTH=8192`，理由见附二**）：

```bash
OLLAMA_HOST=127.0.0.1:11435 \
OLLAMA_MODELS="F:/Ollama_old/models" \
OLLAMA_NOPRUNE=1 \
OLLAMA_CONTEXT_LENGTH=8192 \
"C:/Users/29593/AppData/Local/Programs/Ollama/ollama.exe" serve
```

复现候选筛选：

```bash
.venv/Scripts/python.exe scripts/task39_local_model_screen.py \
  --base-url http://127.0.0.1:11435/v1
```

复现评测：

```bash
.venv/Scripts/python.exe scripts/task39_local_benchmark.py \
  --base-url http://127.0.0.1:11435/v1 \
  --model qwen7b-opt:latest \
  --write-report
```

---

## 附二：服务端上下文长度审计（交付后自查）

### 为什么做这个审计

本项目的既定纪律要求「多题同翻 ≠ 多题都归因于你」——**先判该变量在这题上是否
可能生效，再谈归因**。同样的纪律适用于筛选：在把「6 个候选全部 FAIL」记为
「模型能力不足」之前，必须先排除**服务端上下文长度**这个混淆变量。

触发点：`ollama ps` 报 `context_length: 4096`，而 E-0001 的 schema_link prompt
是 **4635 字符**。二者量级接近，prompt 有可能被截断。

### 审计协议

1. 用 `StubProvider` 在 `generate()` 内抛异常的方式**截获 E-0001 的真实
   schema_link prompt**（不伪造、不简化）。
2. 对每个候选模型，以 `options.num_ctx = 4096` 与 `16384` 分别向 `/api/chat`
   重放**同一条** prompt，记录 `prompt_eval_count` / `eval_count` / 输出长度 /
   是否合法 JSON。

### 结果

**结论 A — prompt 未被截断**：`prompt_eval_count = 1516`，远小于 4096。
4635 个字符（中文为主）只占 1516 token。**「prompt 太长被截断」这条假设被否定。**

**结论 B — thinking 模型会耗尽窗口**：

```
qwen3-vl:4b  num_ctx=4096   prompt_eval=1526  eval=2570  len=0    合法=否
                            └─ 1526 + 2570 = 4096 ─┘  ← 恰好用满
qwen3-vl:4b  num_ctx=16384  prompt_eval=1526  eval=2366  len=108  合法=是
```

推理链（reasoning）与正式输出（content）**共享同一个 `num_ctx` 预算**。
预算被推理链吃光后，`content` 为空字符串 —— 流水线看到的正是
`SchemaLinkingInvalidError: LLM 输出中未找到 JSON`。

**结论 C — 对照模型不受影响**：`qwen7b-opt:latest`（非 thinking）在 4096 与
16384 下输出**逐字节相同**（`eval=34`）。因此主跑的 100 题**不存在 ctx 混淆**。

**结论 D — 复筛结果改变**：`OLLAMA_CONTEXT_LENGTH=8192` 下，
`qwen3-vl:4b` 由 FAIL 变 **PASS**，成为 provider 顺序中第一个可调用候选；
`medical-expert:latest` 仍 FAIL（与 ctx 无关的**能力型**失败）。

### 由此修订的三条表述

| 原表述 | 修订后 |
|---|---|
| `qwen7b-opt:latest` 是「第一个可调用模型」 | 在 **`num_ctx=4096`** 口径下成立；8192 下是 `qwen3-vl:4b`。**该量在未指定 ctx 时不良定义** |
| thinking 系模型「无法驱动本流水线」 | 准确说法是：**上下文预算不足时**推理链吃光窗口导致 `content` 为空；给足上下文后可以工作 |
| 6 个候选 FAIL 都归因于模型能力 | 拆成两类：**能力型**（medical-expert / tipdm_qwen / qwen3-0.6b / qwen3.5-4b 的格式契约失败、qwen3.5:9b 的显存超时）与**上下文型**（`qwen3-vl:4b` @ 4096） |

### 未受影响的部分

- §6–§12 的 100 题数字（EX 41.0% / Exec 62.0% / mean 5695.12 ms …）**全部不变**，
  因为它们由 `qwen7b-opt:latest` 跑出，而该模型对 ctx 不敏感。
- §15 的最终判断 `LOCAL_BENCHMARK_COMPLETE` **不变**。
- 生产红线**依然全部 UNCHANGED**（本次审计只读 + 新增脚本，未改任何既有文件）。

### 审计产物

| 文件 | 内容 |
|---|---|
| `reports/task39_local_screen_ctx8192.json` | ctx=8192 复筛结果 |
| `reports/task39_local_llm_e2e_smoke_qwen3vl.json` | `qwen3-vl:4b` 3 题 smoke（含 `mean_non_llm = 24.39 ms` 交叉验证） |
| `scripts/task39_local_model_screen.py` | 可复用筛选脚本（**docstring 明确要求 `OLLAMA_CONTEXT_LENGTH ≥ 8192`**） |

### 可复用的教训

⭐ **本地模型筛选必须先固定服务端上下文长度。** 否则 thinking 模型会因
「推理链耗尽窗口」被误判为「能力不足」，而这类假阴性会直接污染
「第一个可调用模型」的判定。**筛选脚本必须把 `num_ctx` 作为显式前提记录在案。**

