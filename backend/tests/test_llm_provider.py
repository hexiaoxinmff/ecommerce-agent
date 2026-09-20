"""LLM Provider 单元测试（全部 mock，不真实调用 Mimo）。

覆盖：
- 正常响应：generate() 返回统一文本；
- Key 缺失：明确配置错误；
- 401 / 429 / 5xx / timeout / network 错误映射；
- Secret 防泄露：底层异常携带 "Bearer test-secret" 时不外泄；
- 工厂：默认 mimo，未知 Provider 明确报错。
"""

import httpx2
import openai
import pytest

from app.core import config
from app.llm.mimo import MimoProvider
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
    LLMNetworkError,
    LLMProviderNotConfiguredError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    get_llm_provider,
)

MESSAGES = [{"role": "user", "content": "你好"}]

_REQUEST = httpx2.Request("POST", "https://mimo.test/v1/chat/completions")


def _status_error(status_code: int) -> openai.APIStatusError:
    return openai.APIStatusError(
        f"status {status_code}",
        response=httpx2.Response(status_code, request=_REQUEST),
        body=None,
    )


@pytest.fixture()
def provider(monkeypatch) -> MimoProvider:
    """配置齐全的 MimoProvider（不发起真实网络请求）。"""
    monkeypatch.setattr(config, "MIMO_API_KEY", "test-key")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://mimo.test/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setattr(config, "MIMO_TIMEOUT", 30.0)
    return MimoProvider()


def _fake_call(monkeypatch, output=None, error=None):
    def fake(self, messages, temperature):
        if error is not None:
            raise error
        return output

    monkeypatch.setattr(MimoProvider, "_call_model", fake)


def test_generate_returns_content(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, output="这是一个测试模型响应。")
    assert provider.generate(MESSAGES, temperature=0.0) == "这是一个测试模型响应。"


def test_missing_api_key_raises_config_error(monkeypatch) -> None:
    monkeypatch.setattr(config, "MIMO_API_KEY", "")
    with pytest.raises(LLMApiKeyNotConfiguredError):
        MimoProvider().generate(MESSAGES)


def test_missing_model_raises_config_error(monkeypatch) -> None:
    monkeypatch.setattr(config, "MIMO_API_KEY", "test-key")
    monkeypatch.setattr(config, "MIMO_MODEL", "")
    with pytest.raises(LLMProviderNotConfiguredError):
        MimoProvider().generate(MESSAGES)


def test_401_maps_to_authentication_error(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(401))
    with pytest.raises(LLMAuthenticationError):
        provider.generate(MESSAGES)


def test_403_maps_to_authentication_error(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(403))
    with pytest.raises(LLMAuthenticationError):
        provider.generate(MESSAGES)


def test_429_maps_to_rate_limit_error(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(429))
    with pytest.raises(LLMRateLimitError):
        provider.generate(MESSAGES)


def test_5xx_maps_to_service_unavailable(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(500))
    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(MESSAGES)


def test_timeout_maps_to_timeout_error(provider, monkeypatch) -> None:
    _fake_call(
        monkeypatch, error=openai.APITimeoutError(request=_REQUEST)
    )
    with pytest.raises(LLMTimeoutError):
        provider.generate(MESSAGES)


def test_connection_error_maps_to_network_error(provider, monkeypatch) -> None:
    _fake_call(
        monkeypatch,
        error=openai.APIConnectionError(
            message="connection failed", request=_REQUEST
        ),
    )
    with pytest.raises(LLMNetworkError):
        provider.generate(MESSAGES)


def test_unknown_error_maps_to_service_unavailable(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=RuntimeError("unexpected boom"))
    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(MESSAGES)


def test_secret_not_leaked_from_underlying_error(provider, monkeypatch) -> None:
    """底层异常携带 Secret 时，映射后的异常文本绝不能包含 Secret。"""
    _fake_call(
        monkeypatch,
        error=openai.APIConnectionError(
            message="connection failed, Authorization: Bearer test-secret",
            request=_REQUEST,
        ),
    )
    with pytest.raises(LLMNetworkError) as excinfo:
        provider.generate(MESSAGES)
    assert "test-secret" not in str(excinfo.value)
    assert "test-secret" not in repr(excinfo.value)


def test_factory_returns_mimo_by_default(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "mimo")
    provider = get_llm_provider()
    assert isinstance(provider, MimoProvider)
    assert provider.name == "mimo"


def test_factory_rejects_unsupported_provider(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "deepseek")
    with pytest.raises(LLMProviderNotConfiguredError):
        get_llm_provider()