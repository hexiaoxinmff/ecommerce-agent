"""Task 39-L — 本地 LLM Provider 适配器测试。

覆盖（任务书 §十八）：
- endpoint（默认值 / 环境变量 / 显式参数优先级）
- model selection（embedding 过滤 + 按 provider 顺序取第一个可调用模型）
- request format（POST /chat/completions、JSON body、Content-Type、无鉴权头）
- response parsing（content / reasoning 回落 / 缺失 choices）
- provider latency measurement（成功与失败都记账）
- unavailable handling（连接被拒 / 超时 / 401 / 402 / 429 / 5xx 映射）
- 不影响 Mimo provider（``get_llm_provider()`` 行为逐项不变）

全部离线：用本地 ``http.server`` 桩服务，不依赖 Ollama、不访问外网。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core import config
from app.llm.local_provider import (
    DEFAULT_BASE_URL,
    LocalProvider,
    _extract_content,
    is_embedding_model,
    list_models,
    select_first_chat_model,
)
from app.llm.mimo import MimoProvider
from app.llm.provider import (
    LLMAuthenticationError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMProviderNotConfiguredError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    get_llm_provider,
)

MESSAGES = [{"role": "user", "content": "你好"}]


# ---------------- 桩服务 ----------------

class _Stub:
    """可编程的 OpenAI-compatible 桩服务。"""

    def __init__(self) -> None:
        self.status = 200
        self.payload: dict = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        self.raw_body = ""
        self.delay = 0.0
        self.requests: list[dict] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}/v1"

    def start(self) -> None:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # 静音
                return

            def _reply(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8") if length else ""
                stub.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": json.loads(body) if body else None,
                    }
                )
                if stub.delay:
                    time.sleep(stub.delay)
                if stub.raw_body:
                    data = stub.raw_body.encode("utf-8")
                else:
                    data = json.dumps(stub.payload).encode("utf-8")
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                self._reply()

            def do_POST(self) -> None:  # noqa: N802
                self._reply()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


@pytest.fixture()
def stub():
    s = _Stub()
    s.start()
    yield s
    s.stop()


def _closed_port() -> int:
    """拿一个确定没人监听的端口。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------- endpoint ----------------

def test_default_endpoint(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    provider = LocalProvider(model="m")
    assert provider.base_url == DEFAULT_BASE_URL == "http://127.0.0.1:11434/v1"
    assert provider.name == "local"
    assert provider.model == "m"


def test_endpoint_from_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11435/v1")
    assert LocalProvider(model="m").base_url == "http://127.0.0.1:11435/v1"


def test_explicit_endpoint_beats_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11435/v1")
    provider = LocalProvider(base_url="http://127.0.0.1:9999/v1", model="m")
    assert provider.base_url == "http://127.0.0.1:9999/v1"


def test_timeout_default_and_env(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_TIMEOUT", raising=False)
    assert LocalProvider(model="m")._timeout == 300.0
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT", "12.5")
    assert LocalProvider(model="m")._timeout == 12.5
    # 非法值回退默认
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT", "abc")
    assert LocalProvider(model="m")._timeout == 300.0


# ---------------- model selection ----------------

@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("nomic-embed-text:latest", True),
        ("qwen3-embedding:0.6b", True),
        ("qwen2.5:7b-instruct", False),
        ("medical-expert:latest", False),
        ("qwen3.5:9b", False),
    ],
)
def test_is_embedding_model(model_id, expected):
    assert is_embedding_model(model_id) is expected


def test_name_heuristic_is_not_authoritative():
    """名称启发式只是第一道粗筛，**不是**权威判据。

    ``bge-m3`` 是 embedding 模型但名字里没有 "embed"，本函数会漏判。
    OpenAI-compatible ``/v1/models`` 不暴露 capabilities，所以名称之外
    无法通用判定；真正权威的判据是 Task 39-L 的**实测筛选**
    （用真实流水线 prompt 试跑，产出不了契约输出即不可调用）。
    这条测试把该局限固定下来，防止有人误以为启发式是完备的。
    """
    assert is_embedding_model("bge-m3:latest") is False


def test_select_first_chat_model_skips_embeddings_in_order():
    listing = [
        "nomic-embed-text:latest",
        "qwen3-embedding:0.6b",
        "medical-expert:latest",
        "qwen2.5:7b-instruct",
    ]
    # 保持 provider 顺序，不做任何强弱排序
    assert select_first_chat_model(listing) == "medical-expert:latest"


def test_select_first_chat_model_none_when_only_embeddings():
    assert select_first_chat_model(["nomic-embed-text:latest"]) is None
    assert select_first_chat_model([]) is None


def test_auto_select_uses_provider_listing(stub):
    stub.payload = {
        "object": "list",
        "data": [
            {"id": "nomic-embed-text:latest"},
            {"id": "qwen2.5:7b-instruct"},
        ],
    }
    provider = LocalProvider(base_url=stub.base_url)
    assert provider.model == "qwen2.5:7b-instruct"
    assert stub.requests[0]["path"] == "/v1/models"
    assert stub.requests[0]["method"] == "GET"


def test_auto_select_raises_when_no_chat_model(stub):
    stub.payload = {"object": "list", "data": [{"id": "nomic-embed-text:latest"}]}
    provider = LocalProvider(base_url=stub.base_url)
    assert provider.model == ""
    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(MESSAGES)


# ---------------- /v1/models 解析 ----------------

def test_list_models_parses_ids(stub):
    stub.payload = {"object": "list", "data": [{"id": "a"}, {"id": "b"}, {"nope": 1}]}
    assert list_models(stub.base_url) == ["a", "b"]


def test_list_models_rejects_malformed_payload(stub):
    stub.payload = {"object": "list"}
    with pytest.raises(LLMServiceUnavailableError):
        list_models(stub.base_url)


# ---------------- request format ----------------

def test_request_format(stub):
    provider = LocalProvider(base_url=stub.base_url, model="qwen2.5:7b-instruct")
    assert provider.generate(MESSAGES, temperature=0.0) == "ok"
    assert len(stub.requests) == 1
    request = stub.requests[0]
    assert request["method"] == "POST"
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["content-type"] == "application/json"
    # 无 Key 时不得携带鉴权头
    assert "authorization" not in request["headers"]
    assert request["body"] == {
        "model": "qwen2.5:7b-instruct",
        "messages": MESSAGES,
        "temperature": 0.0,
        "stream": False,
    }


def test_request_carries_key_only_when_configured(stub, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "env-key")
    provider = LocalProvider(base_url=stub.base_url, model="m")
    provider.generate(MESSAGES)
    assert stub.requests[0]["headers"]["authorization"] == "Bearer env-key"

    # 显式传入空串 = 不使用 Key
    provider2 = LocalProvider(base_url=stub.base_url, model="m", api_key="")
    provider2.generate(MESSAGES)
    assert "authorization" not in stub.requests[1]["headers"]


# ---------------- response parsing ----------------

def test_extract_content_plain():
    payload = {"choices": [{"message": {"content": "hello"}}]}
    assert _extract_content(payload) == "hello"


def test_extract_content_falls_back_to_reasoning():
    payload = {"choices": [{"message": {"content": "", "reasoning": "thinking..."}}]}
    assert _extract_content(payload) == "thinking..."


def test_extract_content_empty_string_is_not_an_error():
    # 模型确实没说话 -> 返回空串，交由上层 validator 判非法，不伪装成 provider 故障
    payload = {"choices": [{"message": {"content": ""}}]}
    assert _extract_content(payload) == ""


def test_extract_content_missing_choices_raises():
    with pytest.raises(LLMServiceUnavailableError):
        _extract_content({"choices": []})


def test_generate_parses_reasoning_fallback(stub):
    stub.payload = {"choices": [{"message": {"content": "", "reasoning": "r"}}]}
    provider = LocalProvider(base_url=stub.base_url, model="m")
    assert provider.generate(MESSAGES) == "r"


def test_generate_rejects_malformed_json_body(stub):
    stub.raw_body = "not-json"
    provider = LocalProvider(base_url=stub.base_url, model="m")
    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(MESSAGES)


# ---------------- provider latency measurement ----------------

def test_latency_recorded_on_success(stub):
    provider = LocalProvider(base_url=stub.base_url, model="m")
    assert provider.stats.calls == 0
    provider.generate(MESSAGES)
    provider.generate(MESSAGES)
    assert provider.stats.calls == 2
    assert provider.stats.failures == 0
    assert len(provider.stats.durations_ms) == 2
    assert provider.stats.total_ms > 0
    assert all(d > 0 for d in provider.stats.durations_ms)


def test_latency_recorded_on_failure(stub):
    stub.status = 500
    provider = LocalProvider(base_url=stub.base_url, model="m")
    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(MESSAGES)
    assert provider.stats.calls == 1
    assert provider.stats.failures == 1


def test_stats_reset(stub):
    provider = LocalProvider(base_url=stub.base_url, model="m")
    provider.generate(MESSAGES)
    provider.stats.reset()
    assert provider.stats.calls == 0
    assert provider.stats.total_ms == 0.0
    assert provider.stats.durations_ms == []


# ---------------- unavailable handling ----------------

def test_connection_refused_maps_to_network_error():
    provider = LocalProvider(base_url=f"http://127.0.0.1:{_closed_port()}/v1", model="m")
    with pytest.raises(LLMNetworkError):
        provider.generate(MESSAGES)


def test_list_models_connection_refused():
    with pytest.raises(LLMNetworkError):
        list_models(f"http://127.0.0.1:{_closed_port()}/v1")


def test_timeout_maps_to_timeout_error(stub):
    stub.delay = 1.5
    provider = LocalProvider(base_url=stub.base_url, model="m", timeout=0.3)
    with pytest.raises(LLMTimeoutError):
        provider.generate(MESSAGES)


@pytest.mark.parametrize(
    "status,expected,http_status",
    [
        (401, LLMAuthenticationError, 401),
        (403, LLMAuthenticationError, 403),
        (402, LLMInsufficientBalanceError, 402),
        (429, LLMRateLimitError, 429),
        (500, LLMServiceUnavailableError, 500),
        (503, LLMServiceUnavailableError, 503),
        (400, LLMServiceUnavailableError, 400),
    ],
)
def test_http_status_mapping(stub, status, expected, http_status):
    stub.status = status
    provider = LocalProvider(base_url=stub.base_url, model="m")
    with pytest.raises(expected) as exc_info:
        provider.generate(MESSAGES)
    assert exc_info.value.http_status == http_status


def test_402_is_not_service_unavailable(stub):
    """与 Task 36 的口径一致：402 必须与 5xx 严格区分。"""
    stub.status = 402
    provider = LocalProvider(base_url=stub.base_url, model="m")
    with pytest.raises(LLMInsufficientBalanceError) as exc_info:
        provider.generate(MESSAGES)
    assert not isinstance(exc_info.value, LLMServiceUnavailableError)


# ---------------- 不影响 Mimo provider ----------------

def test_get_llm_provider_still_mimo_only(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mimo")
    assert isinstance(get_llm_provider(), MimoProvider)


def test_local_provider_not_registered_in_factory(monkeypatch):
    """本地 adapter 绝不能接入生产工厂。"""
    monkeypatch.setattr(config, "LLM_PROVIDER", "local")
    with pytest.raises(LLMProviderNotConfiguredError):
        get_llm_provider()


def test_importing_local_provider_does_not_change_factory(monkeypatch):
    import importlib

    import app.llm.provider as provider_module

    monkeypatch.setattr(config, "LLM_PROVIDER", "mimo")
    before = type(get_llm_provider()).__name__
    importlib.reload(importlib.import_module("app.llm.local_provider"))
    assert provider_module.get_llm_provider is not None
    assert type(get_llm_provider()).__name__ == before == "MimoProvider"


def test_local_provider_satisfies_provider_protocol():
    provider = LocalProvider(model="m")
    assert isinstance(provider.name, str)
    assert isinstance(provider.model, str)
    assert callable(provider.generate)
