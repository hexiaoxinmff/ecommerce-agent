"""Task 36 — Provider 错误分类回归测试（全部 mock，不真实调用 Mimo）。

覆盖范围（任务书 §六）：
- 402 / 401 / 403 / 429 / 500 / 502 / 503 / timeout / network error
- 每类验证：exception class、http_status、message、retry behavior

核心断言（任务书 §四 / §十二 Gate B）：
    402 必须与 5xx **明确区分** ——
    402 -> LLMInsufficientBalanceError，且 **不得** 是 LLMServiceUnavailableError。

回归保护（任务书 §五 / §十二 Gate C）：
    401/403/429/5xx/timeout/network 的既有行为**逐项不变**。
"""

from __future__ import annotations

import httpx2
import openai
import pytest

from app.core import config
from app.llm.mimo import MimoProvider
from app.llm.provider import (
    LLMAuthenticationError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)

MESSAGES = [{"role": "user", "content": "你好"}]

_REQUEST = httpx2.Request("POST", "https://mimo.test/v1/chat/completions")


def _status_error(status_code: int, body: str | None = None) -> openai.APIStatusError:
    return openai.APIStatusError(
        f"status {status_code}",
        response=httpx2.Response(status_code, request=_REQUEST),
        body=body,
    )


@pytest.fixture()
def provider(monkeypatch) -> MimoProvider:
    """配置齐全的 MimoProvider（不发起真实网络请求）。"""
    monkeypatch.setattr(config, "MIMO_API_KEY", "test-key")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://mimo.test/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setattr(config, "MIMO_TIMEOUT", 30.0)
    return MimoProvider()


def _fake_call(monkeypatch, output=None, error=None) -> None:
    def fake(self, messages, temperature):
        if error is not None:
            raise error
        return output

    monkeypatch.setattr(MimoProvider, "_call_model", fake)


# ---------------------------------------------------------------------------
# §1 异常类身份：402 与 5xx 严格分离
# ---------------------------------------------------------------------------


def test_402_maps_to_insufficient_balance_error(provider, monkeypatch) -> None:
    """402 -> LLMInsufficientBalanceError（任务书 §四）。"""
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError):
        provider.generate(MESSAGES)


def test_402_is_not_service_unavailable(provider, monkeypatch) -> None:
    """402 **不得** 归入 LLMServiceUnavailableError（Gate B 核心断言）。"""
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)
    assert not isinstance(excinfo.value, LLMServiceUnavailableError), (
        "402 被错误地归入 5xx 语义：LLMInsufficientBalanceError 必须不是 "
        "LLMServiceUnavailableError 的子类"
    )


def test_5xx_is_not_insufficient_balance(provider, monkeypatch) -> None:
    """反向断言：5xx 不得被判为余额不足。"""
    _fake_call(monkeypatch, error=_status_error(500))
    with pytest.raises(LLMServiceUnavailableError) as excinfo:
        provider.generate(MESSAGES)
    assert not isinstance(excinfo.value, LLMInsufficientBalanceError)


def test_402_and_5xx_are_disjoint_classes(provider, monkeypatch) -> None:
    """402 与 5xx 的异常类必须互不包含（无继承关系）。"""
    assert not issubclass(LLMInsufficientBalanceError, LLMServiceUnavailableError)
    assert not issubclass(LLMServiceUnavailableError, LLMInsufficientBalanceError)


def test_both_share_llm_error_base() -> None:
    """两者仍属同一异常体系（不另起炉灶）。"""
    assert issubclass(LLMInsufficientBalanceError, LLMError)
    assert issubclass(LLMServiceUnavailableError, LLMError)


# ---------------------------------------------------------------------------
# §2 http_status 字段
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_cls"),
    [
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (402, LLMInsufficientBalanceError),
        (429, LLMRateLimitError),
        (500, LLMServiceUnavailableError),
        (502, LLMServiceUnavailableError),
        (503, LLMServiceUnavailableError),
    ],
)
def test_http_status_recorded(provider, monkeypatch, status, expected_cls) -> None:
    """每类状态错误都必须在异常上携带真实 http_status。"""
    _fake_call(monkeypatch, error=_status_error(status))
    with pytest.raises(expected_cls) as excinfo:
        provider.generate(MESSAGES)
    assert excinfo.value.http_status == status


@pytest.mark.parametrize(
    ("status", "expected_cls"),
    [
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (402, LLMInsufficientBalanceError),
        (429, LLMRateLimitError),
        (500, LLMServiceUnavailableError),
        (502, LLMServiceUnavailableError),
        (503, LLMServiceUnavailableError),
    ],
)
def test_mapping_table_is_exact(provider, monkeypatch, status, expected_cls) -> None:
    """状态码 -> 异常类 的映射必须精确（type 相等，非 isinstance）。"""
    _fake_call(monkeypatch, error=_status_error(status))
    with pytest.raises(LLMError) as excinfo:
        provider.generate(MESSAGES)
    assert type(excinfo.value) is expected_cls


# ---------------------------------------------------------------------------
# §3 message 文案
# ---------------------------------------------------------------------------


def test_402_message_mentions_balance(provider, monkeypatch) -> None:
    """402 文案必须能表达「余额不足」，不可复用 5xx 文案。"""
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)
    message = str(excinfo.value).lower()
    assert "balance" in message
    assert "unavailable" not in message


def test_402_message_differs_from_5xx_message(provider, monkeypatch) -> None:
    """402 与 5xx 的日志文案必须不同。"""
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError) as balance_exc:
        provider.generate(MESSAGES)

    _fake_call(monkeypatch, error=_status_error(503))
    with pytest.raises(LLMServiceUnavailableError) as unavailable_exc:
        provider.generate(MESSAGES)

    assert str(balance_exc.value) != str(unavailable_exc.value)


def test_402_does_not_leak_response_body(provider, monkeypatch) -> None:
    """402 异常文本不得泄漏上游响应体内容（防 Secret 泄漏）。"""
    body = '{"error":{"message":"Insufficient account balance","key":"Bearer test-secret"}}'
    _fake_call(monkeypatch, error=_status_error(402, body=body))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)
    assert "test-secret" not in str(excinfo.value)
    assert "test-secret" not in repr(excinfo.value)


# ---------------------------------------------------------------------------
# §4 Retry 行为（必须与改动前一致：max_retries=0，仅网络错误重试）
# ---------------------------------------------------------------------------


def _count_calls(monkeypatch, error) -> list[int]:
    """统计 _call_model 的实际调用次数。"""
    calls: list[int] = []

    def fake(self, messages, temperature):
        calls.append(1)
        raise error

    monkeypatch.setattr(MimoProvider, "_call_model", fake)
    return calls


@pytest.mark.parametrize(
    ("status", "expected_cls"),
    [
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (402, LLMInsufficientBalanceError),
        (429, LLMRateLimitError),
        (500, LLMServiceUnavailableError),
        (503, LLMServiceUnavailableError),
    ],
)
def test_status_errors_are_never_retried(
    provider, monkeypatch, status, expected_cls
) -> None:
    """状态类错误（含 402）一次失败即抛出，绝不重试。"""
    calls = _count_calls(monkeypatch, _status_error(status))
    with pytest.raises(expected_cls):
        provider.generate(MESSAGES)
    assert len(calls) == 1, f"status {status} 被重试了 {len(calls)} 次，应为 1 次"


def test_402_retry_policy_matches_5xx(provider, monkeypatch) -> None:
    """402 的重试行为必须与 5xx 完全一致（都不重试）。"""
    calls_402 = _count_calls(monkeypatch, _status_error(402))
    with pytest.raises(LLMInsufficientBalanceError):
        provider.generate(MESSAGES)

    calls_503 = _count_calls(monkeypatch, _status_error(503))
    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(MESSAGES)

    assert len(calls_402) == len(calls_503) == 1


def test_timeout_is_not_retried(provider, monkeypatch) -> None:
    """超时不重试（保持既有行为）。"""
    calls = _count_calls(monkeypatch, openai.APITimeoutError(request=_REQUEST))
    with pytest.raises(LLMTimeoutError):
        provider.generate(MESSAGES)
    assert len(calls) == 1


def test_timeout_has_no_http_status(provider, monkeypatch) -> None:
    """超时非 HTTP 状态错误，http_status 应为 None。"""
    _fake_call(monkeypatch, error=openai.APITimeoutError(request=_REQUEST))
    with pytest.raises(LLMTimeoutError) as excinfo:
        provider.generate(MESSAGES)
    assert excinfo.value.http_status is None


def test_network_error_is_retried_three_times_total(provider, monkeypatch) -> None:
    """网络错误保持既有重试：首次 + 2 次重试 = 共 3 次。

    为避免真实 sleep，打桩 time.sleep。
    """
    monkeypatch.setattr("app.llm.mimo.time.sleep", lambda _s: None)
    calls = _count_calls(
        monkeypatch,
        openai.APIConnectionError(message="connection failed", request=_REQUEST),
    )
    with pytest.raises(LLMNetworkError):
        provider.generate(MESSAGES)
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# §5 端到端：API 路由分类文案
# ---------------------------------------------------------------------------


def test_api_maps_402_to_distinct_message(monkeypatch) -> None:
    """API 层：402 与 5xx 的客户端文案/状态映射必须不同。"""
    from app.api.routes.llm import _map_failure

    balance = _map_failure(LLMInsufficientBalanceError("x", http_status=402))
    unavailable = _map_failure(LLMServiceUnavailableError("y", http_status=503))

    assert balance != unavailable
    assert "balance" in balance[1].lower()
    assert "unavailable" not in balance[1].lower()


def test_api_map_failure_still_handles_all_classes() -> None:
    """既有映射逐项不变（Gate C）。"""
    from app.api.routes.llm import _map_failure

    assert _map_failure(LLMAuthenticationError("a")) == (502, "Mimo authentication failed")
    assert _map_failure(LLMRateLimitError("b")) == (503, "Mimo rate limited")
    assert _map_failure(LLMServiceUnavailableError("c")) == (503, "Mimo service unavailable")
    assert _map_failure(LLMTimeoutError("d")) == (503, "Mimo request timeout")
    assert _map_failure(LLMNetworkError("e")) == (503, "Mimo network error")


def test_api_map_failure_unknown_falls_back_to_503() -> None:
    """未知 LLMError 子类仍回落 503 固定文案。"""
    from app.api.routes.llm import _map_failure

    class _Custom(LLMError):
        pass

    assert _map_failure(_Custom("z")) == (503, "Mimo request failed")


# ---------------------------------------------------------------------------
# §6 评测归属：402 必须仍被计为 provider failure
# ---------------------------------------------------------------------------


def test_402_counted_as_provider_failure() -> None:
    """402 必须归入 provider failure，不得污染模型能力分母。"""
    from evaluation.runner import classify_provider_failure

    is_provider, tag = classify_provider_failure("LLMInsufficientBalanceError", "")
    assert is_provider is True
    assert tag == "LLMInsufficientBalanceError"


def test_provider_error_names_contains_402_class() -> None:
    from evaluation.runner import PROVIDER_ERROR_NAMES

    assert "LLMInsufficientBalanceError" in PROVIDER_ERROR_NAMES
    assert "LLMServiceUnavailableError" in PROVIDER_ERROR_NAMES


def test_non_provider_failure_unchanged() -> None:
    """非 provider 失败仍不归入 provider（保持既有语义）。"""
    from evaluation.runner import classify_provider_failure

    is_provider, tag = classify_provider_failure("SQLGenerationError", "bad sql")
    assert is_provider is False
    assert tag == ""
