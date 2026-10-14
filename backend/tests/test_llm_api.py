"""POST /api/llm/test API 测试（全部 mock，不真实调用 Mimo）。

覆盖：
- 正常：200，success=true，content 非空；
- 空 / 空白 / 超长 prompt：422；
- Key 未配置：503；Provider 抛 timeout：503；认证失败：502；
- Secret 防泄露：底层异常携带 "Bearer test-secret" 时响应中不出现；
- 客户端传入 api_key / model 等额外字段被忽略。
"""

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient

from app.api.routes import llm as llm_route
from app.core import config
from app.llm.mimo import MimoProvider
from app.llm.provider import (
    LLMAuthenticationError,
    LLMQuotaError,
    LLMTimeoutError,
)

_REQUEST = httpx2.Request("POST", "https://mimo.test/v1/chat/completions")


class _FakeProvider:
    """模拟 Provider：可配置固定内容或固定异常。"""

    name = "mimo"
    model = "mimo-v2.5-pro"

    def __init__(self, *, content: str = "", error: Exception | None = None):
        self._content = content
        self._error = error

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        if self._error is not None:
            raise self._error
        return self._content


def _mock_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(llm_route, "get_llm_provider", lambda: provider)


def test_llm_test_success(client: TestClient, monkeypatch) -> None:
    _mock_provider(
        monkeypatch,
        _FakeProvider(content="这是一个测试模型响应。"),
    )
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["provider"] == "mimo"
    assert data["model"] == "mimo-v2.5-pro"
    assert data["content"] == "这是一个测试模型响应。"
    assert data["error"] == ""


def test_empty_prompt_rejected(client: TestClient) -> None:
    assert client.post("/api/llm/test", json={"prompt": ""}).status_code == 422


def test_whitespace_prompt_rejected(client: TestClient) -> None:
    assert client.post("/api/llm/test", json={"prompt": "   "}).status_code == 422


def test_too_long_prompt_rejected(client: TestClient) -> None:
    response = client.post("/api/llm/test", json={"prompt": "长" * 2001})
    assert response.status_code == 422


def test_missing_prompt_field_rejected(client: TestClient) -> None:
    assert client.post("/api/llm/test", json={}).status_code == 422


def test_key_not_configured_returns_503(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "MIMO_API_KEY", "")
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 503
    data = response.json()
    assert data["success"] is False
    assert data["provider"] == "mimo"
    # model 字段始终回显服务端当前配置的模型名（未配置时为空串）
    assert data["model"] == config.MIMO_MODEL
    assert data["error"] == "Mimo API key is not configured"


def test_provider_timeout_returns_503(client: TestClient, monkeypatch) -> None:
    _mock_provider(
        monkeypatch,
        _FakeProvider(error=LLMTimeoutError("Mimo request timeout")),
    )
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 503
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "Mimo request timeout"


def test_provider_authentication_error_returns_502(
    client: TestClient, monkeypatch
) -> None:
    _mock_provider(
        monkeypatch,
        _FakeProvider(error=LLMAuthenticationError("Mimo authentication failed")),
    )
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 502
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "Mimo authentication failed"


def test_provider_quota_error_returns_quota_text_not_auth(
    client: TestClient, monkeypatch
) -> None:
    """Phase 4：AllocationQuota.FreeTierOnly 必须报「配额耗尽」而非认证失败。"""
    _mock_provider(
        monkeypatch,
        _FakeProvider(
            error=LLMQuotaError(
                "Bailian provider quota exhausted (free tier allocation)",
                http_status=403,
                provider_error_code="AllocationQuota.FreeTierOnly",
            )
        ),
    )
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 503
    data = response.json()
    assert data["success"] is False
    assert data["error"] == (
        "Provider quota / allocation exhausted (free tier) "
        "[AllocationQuota.FreeTierOnly]"
    )
    # 绝不能让用户误以为 Key 无效
    assert "authentication" not in data["error"].lower()


def test_provider_quota_error_without_code_still_quota_text(
    client: TestClient, monkeypatch
) -> None:
    """配额异常未携带错误码时：文案保持固定映射，不附加空括号。"""
    _mock_provider(monkeypatch, _FakeProvider(error=LLMQuotaError("quota")))
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 503
    assert (
        response.json()["error"]
        == "Provider quota / allocation exhausted (free tier)"
    )


def test_secret_never_leaks_through_real_provider_chain(
    client: TestClient, monkeypatch
) -> None:
    """端到端：真实 MimoProvider + 底层异常携带 Secret -> 响应不泄漏。"""
    monkeypatch.setattr(config, "MIMO_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://mimo.test/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")

    def boom(self, messages, temperature):
        raise openai.APIConnectionError(
            message="connection failed, Authorization: Bearer test-secret",
            request=_REQUEST,
        )

    monkeypatch.setattr(MimoProvider, "_call_model", boom)
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 503
    assert "test-secret" not in response.text
    data = response.json()
    assert data["error"] == "Mimo network error"


def test_unexpected_provider_exception_returns_fixed_message(
    client: TestClient, monkeypatch
) -> None:
    _mock_provider(
        monkeypatch,
        _FakeProvider(error=RuntimeError("internal boom /path/to/secret")),
    )
    response = client.post("/api/llm/test", json={"prompt": "你好"})
    assert response.status_code == 503
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "Mimo request failed"
    assert "boom" not in response.text
    assert "/path" not in response.text


def test_client_supplied_config_fields_are_ignored(
    client: TestClient, monkeypatch
) -> None:
    _mock_provider(
        monkeypatch,
        _FakeProvider(content="连接正常"),
    )
    response = client.post(
        "/api/llm/test",
        json={
            "prompt": "你好",
            "api_key": "client-secret",
            "model": "evil-model",
            "base_url": "https://evil.test",
            "provider": "evil",
            "timeout": 1,
        },
    )
    assert response.status_code == 200
    assert "client-secret" not in response.text
    assert "evil" not in response.text
    assert response.json()["model"] == "mimo-v2.5-pro"