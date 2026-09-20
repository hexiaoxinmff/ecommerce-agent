# Task 36 — Provider Failure Classification + E2E Benchmark

> 完成时间：2026-09-20
> 状态：**COMPLETE**
> 前置：Phase 2F Release Baseline Freeze（baseline `35a9ad6`）

---

## 1. Objective

解决当前最后一个关键证据缺口：

> Candidate A 已进入 master，但**真实端到端性能仍未重新验证**；当前 Mimo provider 返回
> HTTP 402 `Insufficient account balance`，而现有代码把该错误归入
> `LLMServiceUnavailableError`，导致**失败原因不可区分**。

本任务两部分：

- **A. Provider Error Classification** —— 把 HTTP 错误按真实原因区分
- **B. E2E Benchmark Harness** —— 建立固定、可重复的真实 E2E 性能测量脚本，
  provider 恢复后**无需修改代码**即可重新测量

---

## 2. Current Provider Failure Behavior（改动前审计）

完整错误链（审计详见 `reports/task36_provider_failure_audit.md`）：

```text
HTTP response (openai SDK)
        │
        ├─ openai.APITimeoutError ────────────► LLMTimeoutError
        ├─ openai.APIConnectionError ─────────► LLMNetworkError
        ├─ openai.APIStatusError ─────────────► _map_status_error(exc)
        │                                          ├─ 401/403 → LLMAuthenticationError
        │                                          ├─ 429     → LLMRateLimitError
        │                                          ├─ >=500   → LLMServiceUnavailableError
        │                                          └─ 其他    → LLMServiceUnavailableError  ← 402 落入此处
        ├─ LLMError ──────────────────────────► re-raise
        └─ Exception（未预期） ────────────────► LLMServiceUnavailableError
```

**缺陷定位**：`backend/app/llm/mimo.py`（改前）最后一行

```python
return LLMServiceUnavailableError("Mimo request failed")   # ← 402 被此处吞掉
```

402 既非 401/403、非 429、也不 ≥500，于是与「未预期异常」共用同一异常类与同一文案。

**下游传播**

| 层 | 文件 | 402 的（改前）表现 |
|---|---|---|
| API 路由 | `backend/app/api/routes/llm.py` | `503 "Mimo service unavailable"` |
| Agent 节点 | `backend/app/agent/nodes.py` | `LLMError` 分支 → `http_status=503`，`error_type="LLMServiceUnavailableError"` |
| 评测归属 | `evaluation/runner.py` | 正确计为 provider failure（这点是好的） |

**后果：客户端与运维**无法区分「上游服务故障」与「账户余额不足」。

---

## 3. Error Classification Design

新增异常，**继承既有 `LLMError` 体系**（不生造第二套）：

```python
class LLMInsufficientBalanceError(LLMError):
    """上游账户余额不足（HTTP 402）。"""
```

**关键设计决策**：直接继承 `LLMError`，**而非** `LLMServiceUnavailableError`。

原因：若继承后者，则 `isinstance(exc, LLMServiceUnavailableError)` 仍为 `True`，
§六「402 必须与 5xx 明确区分」无法通过严格断言。二者属**不同故障域**：

| | 402 余额不足 | 5xx 服务故障 |
|---|---|---|
| 故障归属 | 请求方账户额度 | 上游服务端 |
| 重试是否有意义 | 否 | 有时 |
| 客户应做什么 | 充值/换 Key | 稍后重试 |

**新增可选字段** `LLMError.http_status`（默认 `None`）：

```python
def __init__(self, message: str = "", *, http_status: int | None = None) -> None:
    super().__init__(message)
    self.http_status = http_status
```

向后兼容：所有既有子类调用方式不变；仅在能明确判定上游状态时填写。

**最终分类表**

| HTTP | 异常类 | retry | `http_status` |
|---|---|---|---|
| 401 / 403 | `LLMAuthenticationError` | 否 | 401 / 403 |
| **402** | **`LLMInsufficientBalanceError`** | **否** | **402** |
| 429 | `LLMRateLimitError` | 否 | 429 |
| 5xx (500/502/503) | `LLMServiceUnavailableError` | 否 | 500/502/503 |
| 其他 4xx | `LLMServiceUnavailableError`（保持既有兜底） | 否 | 原状态 |
| timeout | `LLMTimeoutError` | 否 | `None` |
| network | `LLMNetworkError` | **是（2 次）** | `None` |

---

## 4. HTTP 402 Handling

```text
HTTP 402  →  LLMInsufficientBalanceError        ✅
HTTP 402  ✗→  LLMServiceUnavailableError         （已消除）
```

改动（`mimo.py::_map_status_error`）：

```python
if status_code == 402:
    return LLMInsufficientBalanceError(
        "Mimo insufficient account balance", http_status=status_code
    )
```

API 路由新增固定文案（**与 5xx 文案不同**）：

```python
LLMInsufficientBalanceError: (503, "Mimo insufficient account balance"),
```

评测归属同步（否则 402 会被误判为「非 provider 失败」，污染模型能力分母）：

```python
PROVIDER_ERROR_NAMES = frozenset({..., "LLMInsufficientBalanceError", ...})
```

**§五 语义保持**：401/403、429、5xx、timeout、network 行为**逐项不变**；
`max_retries=0` 保持不变；网络类错误重试策略（2 次 / 2.0s、5.0s）未扩大。

---

## 5. Regression Tests

新增 `backend/tests/test_task36_provider_errors.py` —— **38 个测试全部通过**。

覆盖矩阵：

| 维度 | 覆盖 |
|---|---|
| 状态码 | 401, 403, **402**, 429, 500, 502, 503 |
| 非状态错误 | timeout, network error |
| 断言项 | exception class（`type()` 精确相等）、`http_status`、message、retry 次数 |
| 分离性 | `test_402_is_not_service_unavailable` / `test_5xx_is_not_insufficient_balance` / `test_402_and_5xx_are_disjoint_classes` |
| 文案 | 402 含 "balance" 且不含 "unavailable"；402 文案 ≠ 5xx 文案 |
| 防泄漏 | 402 响应体含 Secret 时不外泄 |
| retry | 状态类错误（含 402）**从不重试**；402 与 5xx 重试行为一致；network 共 3 次；timeout 不重试 |
| 评测归属 | 402 计为 provider failure；非 provider 失败语义不变 |

**全量回归（Gate A）**：

```text
437 passed, 0 failed, 1 warning in 25.74s
（改动前 399 → 新增 38）
```

---

## 6. E2E Benchmark Design

新增 `scripts/task36_e2e_benchmark.py`。

**固定题集**：默认读 `data/eval/ecommerce_eval_v1.json`（**现有冻结 Benchmark，未创建新题集**）。

**固定模型**：`mimo-v2.5-pro`

**固定配置（每次运行显式记录）**

| 项 | 值 |
|---|---|
| model | `mimo-v2.5-pro` |
| temperature | `0.0` |
| timeout | `60.0 s` |
| sdk_max_retries | `0` |
| provider | `mimo` |
| endpoint_identifier | `https://api.xiaomimimo.com`（**仅 host，绝不含 key**） |
| api_key_recorded | `false` |

**每题固定输出字段**（任务书 §七 全部具备）：

```text
eval_id, start_time, end_time, total_latency_ms, provider_latency_ms,
success, exception_class, http_status, sql_success, repair_triggered
（另附 upstream_http_status, provider_calls, agent_non_llm_latency_ms,
  error_type, final_error）
```

**provider latency 采集方式**：用一个**计时装饰器**包裹 `LLMProvider.generate`，
在进程内累计单次 Agent Run 的 provider 调用次数与耗时。
这样**无需改动任何 Agent / Provider 生产代码**（满足 §十三 Candidate A 不变）。

**用法**

```bash
python scripts/task36_e2e_benchmark.py                 # 默认 5 题 smoke
python scripts/task36_e2e_benchmark.py --limit 100     # 全量
python scripts/task36_e2e_benchmark.py --dry-run       # 只预检，不发请求
python scripts/task36_e2e_benchmark.py --out reports/e2e/run.json
```

该脚本**不属于** `backend/tests`，不会被 `pytest backend/tests` 执行（不消耗 Mimo 调用）。

---

## 7. Latency Metrics

**三种 latency 严格区分**（任务书 §八）：

| 指标 | 定义 |
|---|---|
| `provider_latency_ms` | `LLMProvider.generate` 累计墙钟耗时（可含多次调用） |
| `agent_non_llm_latency_ms` | `total_latency_ms - provider_latency_ms`（钳制 ≥0） |
| `total_e2e_latency_ms` | `run_agent()` 端到端墙钟耗时 |

三者各自报告 **mean / median / P50 / P95 / min / max**。

分位数口径与项目冻结标准一致：`sorted[n*q//100]`（**非插值**）。

> 重要：`provider_latency` 与 `agent_non_llm` 的统计**只在成功的题上计算**。
> provider 全失败时它们样本数为 0（而非填 0 掩盖），总耗时仍如实统计。

---

## 8. Provider-Unavailable Behavior（Gate D，已实测）

当前余额不足，**真实运行**（`--limit 3`，输出 `reports/e2e/task36_e2e_run_20260920.json`）：

```text
[1/3] E-0001   total=  5322.45ms  provider=  5281.69ms  nonllm=   40.76ms  ok=False  exc=LLMInsufficientBalanceError  upstream_http=402
[2/3] E-0002   total=   604.76ms  provider=   595.42ms  nonllm=    9.34ms  ok=False  exc=LLMInsufficientBalanceError  upstream_http=402
[3/3] E-0003   total=   672.76ms  provider=   663.72ms  nonllm=    9.03ms  ok=False  exc=LLMInsufficientBalanceError  upstream_http=402
------------------------------------------------------------------------
mode           : UNAVAILABLE
reason         : provider returned HTTP 402 Insufficient account balance
success        : 0/3
provider calls : 3
total_e2e_latency_ms       n=3    mean=2199.99 median=672.76 p50=672.76 p95=5322.45 min=604.76 max=5322.45
------------------------------------------------------------------------
E2E measurement unavailable due to provider 402
（未对本次运行作任何性能结论）
------------------------------------------------------------------------
```

- 脚本**正常结束，退出码 0**，输出完整统计 ✅
- `success = false`、`exception_class = LLMInsufficientBalanceError`、`http_status = 402` ✅
- **402 未被当作 timeout** ✅

**运行中发现并修复的一个真实缺陷**：初版脚本把 `http_status` 取自
`AgentResult.http_status`，那是**按异常类型映射后的客户端状态（402→503）**，
会把上游 402 掩盖成 503。已改为取 Provider 层捕获的**上游真实 status**，
并同时保留 `upstream_http_status` 字段。修正后输出 `upstream_http=402`。

**Gate E（无需修改脚本即可复用）已用打桩 provider 证明**：余额恢复后同一脚本
自动走向 `MEASURED` 分支，`provider_latency_ms` 与 `provider_calls` 正常填充，
分类离开 `UNAVAILABLE`。

---

## 9. Candidate A Interaction

**Gate F —— Candidate A 生产行为不变。**

五个 Candidate A 源文件的 SHA-256 逐一比对：

| 文件 | 改前 | 改后 | 结论 |
|---|---|---|---|
| `backend/app/agent/graph.py` | `9d09cbae…` | `9d09cbae…` | **未变** |
| `backend/app/schema/metadata.py` | `6aa9b571…` | `6aa9b571…` | **未变** |
| `backend/app/llm/mimo.py` | `2eddd623…` | `c228e119…` | **仅错误分类改动** |
| `backend/app/sqlgen/safety.py` | `c9cd0724…` | `c9cd0724…` | **未变** |
| `backend/app/sqlgen/validator.py` | `1c0e9a2c…` | `1c0e9a2c…` | **未变** |

`mimo.py` 虽有变化，但四处 Candidate A 优化点**全部完好**：

- `_get_client()` 实例内复用（`self._client`）— 未动
- `max_retries=0` — 未动
- `graph.py` `_DEFAULT_GRAPH_CACHE` / `clear_default_graph_cache` — 未动
- `metadata.py` `_CATALOG_CACHE` / `get_cached` / `clear_cache` — 未动
- `safety.py` `_parse_single_readonly` / `check_sql_safety_with_tables` — 未动

改动总量：**54 insertions / 6 deletions**，全部位于错误分类路径。

---

## 10. Current Measurement Status

```text
Current Real E2E:
  NOT_MEASURED

Reason:
  Mimo HTTP 402 Insufficient account balance
```

**本任务在 provider 仍为 402 的情况下，不作任何性能结论。** 未声明：

```text
❌ E2E latency improved
❌ ≤8s achieved
❌ Candidate A reduced E2E by X%
```

**历史证据保留但不得替代新 benchmark**（§十一）：

```text
local deterministic (Task 29 / 35):
  29.074 → 1.955 ms   (−93.3%)

historical provider-backed client reuse:
  ~836 ms/call
```

> 这两项**不能**替代新的真实 E2E benchmark。三层证据（本地确定性 / 历史 provider 支撑 /
> 当前 E2E）**不得混用**。

---

## 11. Known Limitations

| # | 限制 |
|---|---|
| L1 | **真实 E2E 仍未测量** —— provider 402。脚本已就绪，余额恢复后**直接运行即可**，无需改代码。 |
| L2 | `http_status` 在 API 响应层被映射为客户端状态（402 → 503）。上游真实 402 通过异常的 `http_status` 字段与 benchmark 的 `upstream_http_status` 字段保留；**API 对外状态码语义未改**（避免破坏既有契约）。 |
| L3 | provider latency 通过**进程内计时装饰器**采集，非 Agent 原生埋点。它对生产的唯一影响是 monkeypatch；不改生产代码。若未来 Agent 原生暴露 LLM 耗时，应改用原生数据。 |
| L4 | `agent_non_llm_latency_ms` 是**差值**，包含图调度、SQL 解析、DB 执行等全部非 LLM 开销，非单一分量。 |
| L5 | benchmark 默认 `--limit 5`（smoke）。全量 100 题需显式 `--limit 100`，会消耗 100+ 次真实 provider 调用。 |
| L6 | 单次运行未做多轮重复；P95 在 n=5 时等于 max（n 小时分位数解释力弱）。 |
| L7 | 脚本未含 provider 侧并发/限流控制；串行执行。 |

---

## 12. Production Readiness

| 项 | 状态 |
|---|---|
| Provider 错误分类 | **PRODUCTION READY**（已接入 `mimo.py` / API 路由 / 评测归属） |
| HTTP 402 区分 | **DISTINCT**（已生效） |
| 既有非 402 行为 | **UNCHANGED** |
| E2E Benchmark | **READY**（脚本可执行、可复用；当前因 provider 402 输出 `UNAVAILABLE`） |
| Candidate A 生产代码 | **UNCHANGED** |

`Production: UPDATED` —— 仅错误分类路径更新；Agent / Schema Linking / SQL 生成 /
执行 / Candidate A 优化均未变。

---

## 13. Frozen Baseline

| 资产 | SHA256 | 结论 |
|---|---|---|
| Prompt V1.3 | `2af938be9866a62a97fdc3f1b0c7dc43b0785a7ff75ad420109b1d18ed39dc4c` | **MATCH** |
| Few-shot FEWSHOT_V3 | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` | **MATCH** |
| Dataset | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` | **MATCH** |
| DB | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9` | **MATCH** |
| Clean Baseline | `39404fedef84b338cc7b48ed2972db98c7c574cd8cfca196ca02f7843e42f66e` | **MATCH** |

**Overall: MATCH** —— Prompt / Few-shot / Dataset / Gold / DB / Candidate A 全部未变。

Git baseline 未动：`master = HEAD = 35a9ad6`，`release_baseline_20260920 → 35a9ad6`。

---

## 交付物

| 文件 | 说明 |
|---|---|
| `backend/app/llm/provider.py` | 新增 `LLMInsufficientBalanceError` + `LLMError.http_status` |
| `backend/app/llm/mimo.py` | 402 独立分类；各分支写入 `http_status` |
| `backend/app/api/routes/llm.py` | 402 独立客户端文案 |
| `evaluation/runner.py` | 402 计入 provider failure |
| `backend/tests/test_task36_provider_errors.py` | 38 个回归测试（新增） |
| `scripts/task36_e2e_benchmark.py` | E2E benchmark harness（新增） |
| `reports/task36_provider_failure_audit.md` | 改动前审计（只读） |
| `reports/task36_provider_and_e2e_benchmark.md` / `.json` | 本报告 |
| `reports/e2e/task36_e2e_run_20260920.json` | 真实运行记录（UNAVAILABLE） |
