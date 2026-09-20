# Task 36 — Provider Failure Audit (Pre-Change, No Code Modified)

> 审计时间：2026-09-20 14:2x
> 状态：**只读审计**。本文件记录改动前的真实行为。

---

## 1. 完整错误链

```text
HTTP response (openai SDK)
        │
        ├─ openai.APITimeoutError ────────────► LLMTimeoutError("Mimo request timeout")
        ├─ openai.APIConnectionError ─────────► LLMNetworkError("Mimo network error")
        ├─ openai.APIStatusError ─────────────► _map_status_error(exc)
        │                                          ├─ 401/403  → LLMAuthenticationError("Mimo authentication failed")
        │                                          ├─ 429      → LLMRateLimitError("Mimo rate limited")
        │                                          ├─ >=500    → LLMServiceUnavailableError("Mimo service unavailable")
        │                                          └─ 其他     → LLMServiceUnavailableError("Mimo request failed")
        ├─ LLMError ──────────────────────────► re-raise（穿透）
        └─ Exception（未预期） ────────────────► LLMServiceUnavailableError("Mimo request failed")
```

**关键缺陷定位**：`backend/app/llm/mimo.py:144`

```python
return LLMServiceUnavailableError("Mimo request failed")   # ← 402 落入此处
```

402 **既不是** 401/403、**也不是** 429、**也不 >= 500**，因此被最后的 catch-all 吞掉，
与「未预期异常」共用同一异常类 + 同一文案。

---

## 2. 下游传播

### 2.1 API 路由 `backend/app/api/routes/llm.py`

```python
_LLM_FAILURES = {
    LLMApiKeyNotConfiguredError: (503, "Mimo API key is not configured"),
    LLMProviderNotConfiguredError: (503, "LLM provider is not configured"),
    LLMAuthenticationError: (502, "Mimo authentication failed"),
    LLMRateLimitError: (503, "Mimo rate limited"),
    LLMServiceUnavailableError: (503, "Mimo service unavailable"),
    LLMTimeoutError: (503, "Mimo request timeout"),
    LLMNetworkError: (503, "Mimo network error"),
}
```

`_map_failure()` 沿 `type(exc).__mro__` 查找 → 402 命中 `LLMServiceUnavailableError` → **HTTP 503 "Mimo service unavailable"**。

**后果：客户端无法区分「上游服务挂了」与「我方账户没钱」。**

### 2.2 Agent 节点 `backend/app/agent/nodes.py`

```python
def _http_status_for(exc):
    if isinstance(exc, LLMAuthenticationError): return 502
    if isinstance(exc, LLMError):               return 503
    return None
```

402 → `LLMError` 分支 → **503**，且 `error_type = "LLMServiceUnavailableError"`。

### 2.3 评测归属 `evaluation/runner.py`

```python
PROVIDER_ERROR_NAMES = frozenset({
    "LLMError", "LLMApiKeyNotConfiguredError", "LLMAuthenticationError",
    "LLMRateLimitError", "LLMServiceUnavailableError", "LLMTimeoutError",
    "LLMNetworkError", "LLMProviderNotConfiguredError",
})
```

402 当前记作 `LLMServiceUnavailableError` → 被正确识别为 **provider failure**（这点是好的，改动后必须保持）。

---

## 3. Retry 行为（当前真实值）

| 层级 | 配置 | 说明 |
|---|---|---|
| openai SDK | `max_retries=0` | `_get_client()` 显式设置 |
| Provider 层 | 仅 `LLMNetworkError` 重试 2 次 | `_NETWORK_RETRY_DELAYS_SECONDS = (2.0, 5.0)` |
| 401/403/429/5xx/402 | **不重试**，一次失败即抛出 | — |
| timeout | **不重试** | — |

**§五 要求保持 `max_retries=0`** → 与现状一致，无需改动。

---

## 4. 现状问题清单

| # | 问题 | 影响 |
|---|---|---|
| P1 | 402 与 5xx 共用 `LLMServiceUnavailableError` | 失败原因不可区分（本任务要解决） |
| P2 | 402 与「未知异常」共用文案 `"Mimo request failed"` | 诊断困难 |
| P3 | 403 与 401 合并（`LLMAuthenticationError`） | 可接受：语义同属认证失败，且 `_map_status_error` 已保留原 status |
| P4 | 402 时无法从异常对象读取 HTTP status | benchmark 需要 `http_status=402` 字段 |

---

## 5. §四 设计决策（待实现）

- 新异常 `LLMInsufficientBalanceError`，**继承 `LLMError`**（不生造第二套体系）。
- ⚠️ **不能继承 `LLMServiceUnavailableError`** —— 否则 `isinstance(exc, LLMServiceUnavailableError)` 仍为 True，
  §六「402 必须与 5xx 明确区分」无法通过严格断言。
- 继承 `LLMError` 的直接后果：`evaluation/runner.py` 的 `PROVIDER_ERROR_NAMES` 需**加入**该类名，
  否则 402 会被误判为「非 provider 失败」从而污染模型能力分母 → 必须在本次一并处理。
- 为让 API 层能回报真实 status，在 `LLMError` 上增加**可选** `http_status: int | None = None` 构造参数
  （默认 None，不改变任何现有子类行为）。
