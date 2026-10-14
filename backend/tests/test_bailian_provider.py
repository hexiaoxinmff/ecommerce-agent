"""Task 42 — BailianProvider 单元测试（全部 mock，不真实调用百炼）。

覆盖范围（任务书 §十 A–K）：
    A. 配置：model / base URL / enable_thinking / timeout / API key
    B. Client 复用：连续两次 _get_client() 返回同一实例
    C. Request 参数：model / messages / temperature / extra_body /
       无 max_tokens / SDK max_retries=0
    D. generate：正常 response 返回 choices[0].message.content
    E. 402 -> LLMInsufficientBalanceError，且 **不是** LLMServiceUnavailableError
    F. 5xx -> LLMServiceUnavailableError
    G. 429 -> LLMRateLimitError
    H. 401 / 403 -> LLMAuthenticationError
    I. 网络错误 -> LLMNetworkError（并保持 Provider 层有限重试语义）
    J. Secret 隔离：str / repr 不含 fake key，也不泄漏 response body
    K. Factory：bailian -> BailianProvider，mimo -> MimoProvider，未知仍报错

附加的架构护栏（任务书 §一 / §九 / §十五）：
    - 上层模块不得出现 provider 名分支（AST 判据，不是字符串 grep）
    - 上层模块不得直接 import app.llm.bailian
    - app.llm.provider 对 bailian 保持 lazy import

§十一 真实 API 冒烟：**默认一律 SKIPPED**。只有显式设置
RUN_REAL_LLM_SMOKE=1 **且** 本机已配置 DASHSCOPE_API_KEY 时才执行。
（Task 70 起生效：此前"`.env` 里有 key 就自动联网"的语义已废弃，
 判定表见 `tests/real_llm_smoke_gate.py`。）
任何测试都不要求把真实 Key 写进源码或聊天消息。
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.core import config
from app.llm.bailian import BailianProvider
from app.llm.mimo import MimoProvider
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMProviderNotConfiguredError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    get_llm_provider,
)
from tests.real_llm_smoke_gate import evaluate as _real_llm_smoke_gate

FAKE_KEY = "test-secret"
DEFAULT_MODEL = "qwen3.7-flash-2026-07-15"
DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

MESSAGES = [{"role": "user", "content": "只返回 SELECT 1;"}]

_REQUEST = httpx2.Request(
    "POST", "https://dashscope.test/compatible-mode/v1/chat/completions"
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
LLM_ROOT = APP_ROOT / "llm"


def _status_error(status_code: int, body: str | None = None) -> openai.APIStatusError:
    return openai.APIStatusError(
        f"status {status_code}",
        response=httpx2.Response(status_code, request=_REQUEST),
        body=body,
    )


@pytest.fixture()
def provider(monkeypatch) -> BailianProvider:
    """配置齐全的 BailianProvider（不发起真实网络请求）。"""
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(config, "BAILIAN_BASE_URL", DEFAULT_BASE)
    monkeypatch.setattr(config, "BAILIAN_MODEL", DEFAULT_MODEL)
    monkeypatch.setattr(config, "BAILIAN_TIMEOUT", 30.0)
    return BailianProvider()


def _fake_call(monkeypatch, output=None, error=None) -> None:
    def fake(self, messages, temperature):
        if error is not None:
            raise error
        return output

    monkeypatch.setattr(BailianProvider, "_call_model", fake)


def _count_calls(monkeypatch, error) -> list[int]:
    """统计 _call_model 的实际调用次数。"""
    calls: list[int] = []

    def fake(self, messages, temperature):
        calls.append(1)
        raise error

    monkeypatch.setattr(BailianProvider, "_call_model", fake)
    return calls


def _recording_client(content: str | None = "SELECT 1;"):
    """返回 (假 client, 已记录 kwargs 的 list)，用于检查真实请求参数。"""
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client, calls


# ===========================================================================
# A. 配置
# ===========================================================================


def test_provider_reads_all_config(provider) -> None:
    """Provider 必须从 config 读取 model / base_url / timeout / key。"""
    assert provider._api_key == FAKE_KEY
    assert provider._base_url == DEFAULT_BASE
    assert provider._model == DEFAULT_MODEL
    assert provider._timeout == 30.0


def test_provider_has_no_thinking_attribute(provider) -> None:
    """thinking 不得有任何实例级开关（物理锁死，不是配置）。"""
    assert not hasattr(provider, "_enable_thinking")
    assert not hasattr(provider, "enable_thinking")


def test_config_has_no_thinking_switch() -> None:
    """配置层不得存在 BAILIAN_ENABLE_THINKING（不留死配置 / 不留旋钮）。"""
    assert not hasattr(config, "BAILIAN_ENABLE_THINKING")
    assert not hasattr(config, "_env_bool")


def test_provider_name_and_model_exposed(provider) -> None:
    """LLMProvider Protocol 要求的 name / model 两个成员。"""
    assert provider.name == "bailian"
    assert provider.model == DEFAULT_MODEL


def test_provider_satisfies_protocol_shape(provider) -> None:
    """结构上满足 LLMProvider：generate(messages, *, temperature=0.0)。

    注：LLMProvider 是 typing.Protocol 但未加 runtime_checkable，
    因此用签名检查代替 isinstance 检查。
    """
    assert isinstance(provider.name, str)
    assert isinstance(provider.model, str)
    assert callable(provider.generate)

    sig = inspect.signature(provider.generate)
    assert list(sig.parameters) == ["messages", "temperature"]
    temp = sig.parameters["temperature"]
    assert temp.kind is inspect.Parameter.KEYWORD_ONLY
    assert temp.default == 0.0


_DEFAULT_PROBE = """
import json
from app.core import config
print(json.dumps({
    "model": config.BAILIAN_MODEL,
    "base_url": config.BAILIAN_BASE_URL,
    "timeout": config.BAILIAN_TIMEOUT,
    "api_key": config.DASHSCOPE_API_KEY,
    "has_thinking_switch": hasattr(config, "BAILIAN_ENABLE_THINKING"),
    "has_env_bool": hasattr(config, "_env_bool"),
}))
"""


def test_config_defaults_when_env_empty() -> None:
    """显式置空时，配置必须回退到「低消费默认值」。

    用子进程 + 空值环境变量，既能验证回退分支，又不受本机 .env 影响
    （load_dotenv(override=False) 下真实环境变量优先）。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["BAILIAN_MODEL"] = ""
    env["BAILIAN_API_BASE"] = ""
    env["BAILIAN_TIMEOUT"] = ""
    env["DASHSCOPE_API_KEY"] = ""

    result = subprocess.run(
        [sys.executable, "-c", _DEFAULT_PROBE],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["model"] == DEFAULT_MODEL
    assert data["base_url"] == DEFAULT_BASE
    assert data["timeout"] == 30.0
    assert data["api_key"] == ""
    assert data["has_thinking_switch"] is False
    assert data["has_env_bool"] is False


# ---------------------------------------------------------------------------
# thinking 物理锁死：环境变量无论怎么写都无法打开
# ---------------------------------------------------------------------------

_THINKING_LOCK_PROBE = """
import json
from app.llm.bailian import BailianProvider

captured = {}


class _Completions:
    def create(self, **kwargs):
        captured.update(kwargs)
        msg = type("Msg", (), {"content": "SELECT 1;"})()
        choice = type("Choice", (), {"message": msg})()
        return type("Resp", (), {"choices": [choice]})()


def _fake_client():
    return type(
        "Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()}
    )()


provider = BailianProvider()
provider._get_client = _fake_client
provider.generate([{"role": "user", "content": "x"}])

print(json.dumps({
    "extra_body": captured.get("extra_body"),
    "params": sorted(captured),
}))
"""


@pytest.mark.parametrize("raw", ["true", "1", "yes"])
def test_thinking_cannot_be_enabled_by_env(raw) -> None:
    """即使环境变量尝试打开 thinking，请求仍必须是 enable_thinking=False。

    必须在子进程里做：config 在 import 时读取环境变量，
    同进程内改环境变量证明不了「配置层根本不存在这个开关」。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["BAILIAN_ENABLE_THINKING"] = raw
    env["DASHSCOPE_API_KEY"] = FAKE_KEY

    result = subprocess.run(
        [sys.executable, "-c", _THINKING_LOCK_PROBE],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr

    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["extra_body"] == {"enable_thinking": False}, (
        f"BAILIAN_ENABLE_THINKING={raw} 竟然影响到了请求"
    )
    assert data["params"] == ["extra_body", "messages", "model", "temperature"]


def test_thinking_is_literal_false_in_source() -> None:
    """AST 判据：_call_model 里 enable_thinking 的值必须是字面量 False。

    这比「运行一次看结果」更强 —— 它直接排除「值来自某个变量/配置」的可能。
    """
    tree = ast.parse(
        (BACKEND_ROOT / "app" / "llm" / "bailian.py").read_text(encoding="utf-8")
    )

    values: list[object] = []
    for node in ast.walk(tree):
        # extra_body={"enable_thinking": <value>}
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "enable_thinking":
                if isinstance(value, ast.Constant):
                    values.append(value.value)
                else:
                    values.append(f"<non-literal {type(value).__name__}>")

    assert values == [False], f"enable_thinking 的值不是字面量 False: {values}"


def test_no_thinking_config_reference_anywhere_in_app() -> None:
    """全 app/ 不得再出现 BAILIAN_ENABLE_THINKING 或 _env_bool 引用。"""
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                "BAILIAN_ENABLE_THINKING",
                "_env_bool",
            ):
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
            if isinstance(node, ast.Constant) and node.value == "BAILIAN_ENABLE_THINKING":
                # 环境变量名字符串也不该再被读取
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert not offenders, f"仍存在 thinking 开关引用: {offenders}"


def test_api_key_only_from_dashscope(monkeypatch) -> None:
    """Key 唯一来源是 DASHSCOPE_API_KEY；不存在 BAILIAN_API_KEY 这条读取路径。"""
    assert not hasattr(config, "BAILIAN_API_KEY")

    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "k-from-dashscope")
    assert BailianProvider()._api_key == "k-from-dashscope"

    # 即便环境里塞了 BAILIAN_API_KEY，也不应被读取
    monkeypatch.setenv("BAILIAN_API_KEY", "should-be-ignored")
    assert BailianProvider()._api_key == "k-from-dashscope"


def test_missing_api_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "")
    monkeypatch.setattr(config, "BAILIAN_MODEL", DEFAULT_MODEL)
    with pytest.raises(LLMApiKeyNotConfiguredError):
        BailianProvider().generate(MESSAGES)


def test_missing_model_raises(monkeypatch) -> None:
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(config, "BAILIAN_MODEL", "")
    with pytest.raises(LLMProviderNotConfiguredError):
        BailianProvider().generate(MESSAGES)


# ===========================================================================
# B. Client 复用
# ===========================================================================


def test_client_is_reused(provider) -> None:
    """连续两次 _get_client() 必须得到同一个实例。"""
    first = provider._get_client()
    second = provider._get_client()
    assert first is second
    assert isinstance(first, openai.OpenAI)


def test_client_is_lazy(provider) -> None:
    """构造 Provider 时不得创建 client（惰性）。"""
    assert provider._client is None
    provider._get_client()
    assert provider._client is not None


def test_client_bound_to_configured_base_url(provider) -> None:
    assert str(provider._get_client().base_url).rstrip("/") == DEFAULT_BASE


def test_instances_do_not_share_client(provider) -> None:
    assert BailianProvider()._get_client() is not BailianProvider()._get_client()


def test_sdk_max_retries_is_zero(provider) -> None:
    """SDK 层不做自动重试。"""
    assert provider._get_client().max_retries == 0


# ===========================================================================
# C. Request 参数
# ===========================================================================


def test_request_parameters_are_exact(provider, monkeypatch) -> None:
    """请求参数必须精确为 model / messages / temperature / extra_body 四项。

    用集合相等断言，同时覆盖「不出现 max_tokens」「不引入额外 reasoning 参数」。
    """
    client, calls = _recording_client()
    monkeypatch.setattr(provider, "_get_client", lambda: client)

    out = provider.generate(MESSAGES, temperature=0.0)

    assert out == "SELECT 1;"
    assert len(calls) == 1
    kwargs = calls[0]

    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["messages"] == MESSAGES
    assert kwargs["temperature"] == 0.0
    assert kwargs["extra_body"] == {"enable_thinking": False}
    assert set(kwargs) == {"model", "messages", "temperature", "extra_body"}


def test_request_has_no_max_tokens(provider, monkeypatch) -> None:
    """不扩大输出预算：请求里不得出现 max_tokens / thinking_budget。"""
    client, calls = _recording_client()
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    provider.generate(MESSAGES)

    kwargs = calls[0]
    assert "max_tokens" not in kwargs
    assert "max_output_tokens" not in kwargs
    assert "thinking_budget" not in kwargs
    assert "reasoning" not in kwargs


def test_extra_body_always_disables_thinking(provider, monkeypatch) -> None:
    """§六：extra_body 恒为 {"enable_thinking": False}（物理锁死，非默认值）。"""
    client, calls = _recording_client()
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    provider.generate(MESSAGES)

    extra_body = calls[0]["extra_body"]
    assert extra_body == {"enable_thinking": False}
    assert extra_body["enable_thinking"] is False
    # 只有一个键：不得夹带 thinking_budget / reasoning 之类
    assert set(extra_body) == {"enable_thinking"}


def test_temperature_is_passed_through(provider, monkeypatch) -> None:
    client, calls = _recording_client()
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    provider.generate(MESSAGES, temperature=0.7)
    assert calls[0]["temperature"] == 0.7


def test_temperature_defaults_to_zero(provider, monkeypatch) -> None:
    client, calls = _recording_client()
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    provider.generate(MESSAGES)
    assert calls[0]["temperature"] == 0.0


# ===========================================================================
# D. generate
# ===========================================================================


def test_generate_returns_content(provider, monkeypatch) -> None:
    client, _ = _recording_client("SELECT 1;")
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    assert provider.generate(MESSAGES) == "SELECT 1;"


def test_generate_normalises_none_content(provider, monkeypatch) -> None:
    """content 为 None 时返回空串（与 MimoProvider 一致），不返回 None。"""
    client, _ = _recording_client(None)
    monkeypatch.setattr(provider, "_get_client", lambda: client)
    assert provider.generate(MESSAGES) == ""


# ===========================================================================
# E. 402 —— 必须与 5xx 严格分离
# ===========================================================================


def test_402_maps_to_insufficient_balance(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)
    assert type(excinfo.value) is LLMInsufficientBalanceError
    assert excinfo.value.http_status == 402


def test_402_is_not_service_unavailable(provider, monkeypatch) -> None:
    """Gate：402 **不得** 是 LLMServiceUnavailableError。"""
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)
    assert not isinstance(excinfo.value, LLMServiceUnavailableError)


def test_5xx_is_not_insufficient_balance(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(500))
    with pytest.raises(LLMServiceUnavailableError) as excinfo:
        provider.generate(MESSAGES)
    assert not isinstance(excinfo.value, LLMInsufficientBalanceError)


def test_402_and_5xx_are_disjoint_classes() -> None:
    assert not issubclass(LLMInsufficientBalanceError, LLMServiceUnavailableError)
    assert not issubclass(LLMServiceUnavailableError, LLMInsufficientBalanceError)
    assert issubclass(LLMInsufficientBalanceError, LLMError)
    assert issubclass(LLMServiceUnavailableError, LLMError)


def test_402_message_mentions_balance(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=_status_error(402))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)
    message = str(excinfo.value).lower()
    assert "balance" in message
    assert "unavailable" not in message


# ===========================================================================
# F / G / H. 状态码映射表（精确 type 相等）
# ===========================================================================


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
def test_status_mapping_is_exact(provider, monkeypatch, status, expected_cls) -> None:
    _fake_call(monkeypatch, error=_status_error(status))
    with pytest.raises(LLMError) as excinfo:
        provider.generate(MESSAGES)
    assert type(excinfo.value) is expected_cls
    assert excinfo.value.http_status == status


@pytest.mark.parametrize("status", [400, 404, 418, 422])
def test_other_4xx_falls_back_to_controlled_error(
    provider, monkeypatch, status
) -> None:
    """其他 4xx -> 受控兜底（固定文案 + http_status），不透传上游体。"""
    _fake_call(monkeypatch, error=_status_error(status, body=f'{{"k":"{FAKE_KEY}"}}'))
    with pytest.raises(LLMServiceUnavailableError) as excinfo:
        provider.generate(MESSAGES)
    assert excinfo.value.http_status == status
    assert FAKE_KEY not in str(excinfo.value)


def test_401_403_are_authentication_errors(provider, monkeypatch) -> None:
    for status in (401, 403):
        _fake_call(monkeypatch, error=_status_error(status))
        with pytest.raises(LLMAuthenticationError):
            provider.generate(MESSAGES)


# ===========================================================================
# H+. 403 + AllocationQuota.* -> LLMQuotaError（Phase 4 错误分类修正）
# ===========================================================================


def test_403_free_tier_only_maps_to_quota_error(provider, monkeypatch) -> None:
    """403 + AllocationQuota.FreeTierOnly：配额耗尽，绝不能误报认证失败。"""
    body = (
        '{"error":{"code":"AllocationQuota.FreeTierOnly",'
        '"message":"Free tier quota exhausted"}}'
    )
    _fake_call(monkeypatch, error=_status_error(403, body=body))
    with pytest.raises(LLMQuotaError) as excinfo:
        provider.generate(MESSAGES)

    exc = excinfo.value
    assert type(exc) is LLMQuotaError
    assert not isinstance(exc, LLMAuthenticationError)
    assert exc.http_status == 403
    # 原始结构化错误码必须保留（不吞掉上游错误信息）
    assert exc.provider_error_code == "AllocationQuota.FreeTierOnly"
    # 文案是「配额耗尽」语义，不含 "authentication"
    assert "quota" in str(exc).lower()
    assert "authentication" not in str(exc).lower()


def test_403_other_quota_family_code_maps_to_quota_error(provider, monkeypatch) -> None:
    """403 + AllocationQuota.* 族内其他码：同样归为配额类。"""
    body = '{"code":"AllocationQuota.PurchasedQuotaExhausted"}'
    _fake_call(monkeypatch, error=_status_error(403, body=body))
    with pytest.raises(LLMQuotaError) as excinfo:
        provider.generate(MESSAGES)
    assert excinfo.value.provider_error_code == "AllocationQuota.PurchasedQuotaExhausted"


def test_403_endpoint_access_denied_stays_authentication(provider, monkeypatch) -> None:
    """403 + Endpoint.AccessDenied（endpoint 不可用）：保持既有认证分类不变。"""
    body = '{"error":{"code":"Endpoint.AccessDenied"}}'
    _fake_call(monkeypatch, error=_status_error(403, body=body))
    with pytest.raises(LLMAuthenticationError) as excinfo:
        provider.generate(MESSAGES)
    assert type(excinfo.value) is LLMAuthenticationError
    assert excinfo.value.provider_error_code == "Endpoint.AccessDenied"


def test_401_with_quota_code_stays_authentication(provider, monkeypatch) -> None:
    """401 即使携带配额形态的错误码：仍是认证失败（配额改判仅限 403）。"""
    body = '{"error":{"code":"AllocationQuota.FreeTierOnly"}}'
    _fake_call(monkeypatch, error=_status_error(401, body=body))
    with pytest.raises(LLMAuthenticationError) as excinfo:
        provider.generate(MESSAGES)
    assert type(excinfo.value) is LLMAuthenticationError


def test_quota_error_does_not_leak_body_or_key(provider, monkeypatch) -> None:
    """配额异常同样必须通过 Secret 隔离约束。"""
    body = (
        '{"error":{"code":"AllocationQuota.FreeTierOnly",'
        f'"key":"Bearer {FAKE_KEY}"}}}}'
    )
    _fake_call(monkeypatch, error=_status_error(403, body=body))
    with pytest.raises(LLMQuotaError) as excinfo:
        provider.generate(MESSAGES)
    assert FAKE_KEY not in str(excinfo.value)
    assert FAKE_KEY not in repr(excinfo.value)
    assert "Bearer" not in str(excinfo.value)


# ===========================================================================
# I. 网络 / 超时
# ===========================================================================


def test_timeout_maps_to_timeout_error(provider, monkeypatch) -> None:
    _fake_call(monkeypatch, error=openai.APITimeoutError(request=_REQUEST))
    with pytest.raises(LLMTimeoutError) as excinfo:
        provider.generate(MESSAGES)
    assert excinfo.value.http_status is None


def test_network_error_maps_to_network_error(provider, monkeypatch) -> None:
    monkeypatch.setattr("app.llm.bailian.time.sleep", lambda _s: None)
    _fake_call(
        monkeypatch,
        error=openai.APIConnectionError(message="connection failed", request=_REQUEST),
    )
    with pytest.raises(LLMNetworkError):
        provider.generate(MESSAGES)


def test_network_error_retried_three_times_total(provider, monkeypatch) -> None:
    """保持与 MimoProvider 一致的网络重试：首次 + 2 次重试 = 共 3 次。"""
    monkeypatch.setattr("app.llm.bailian.time.sleep", lambda _s: None)
    calls = _count_calls(
        monkeypatch,
        openai.APIConnectionError(message="connection failed", request=_REQUEST),
    )
    with pytest.raises(LLMNetworkError):
        provider.generate(MESSAGES)
    assert len(calls) == 3


def test_timeout_is_not_retried(provider, monkeypatch) -> None:
    calls = _count_calls(monkeypatch, openai.APITimeoutError(request=_REQUEST))
    with pytest.raises(LLMTimeoutError):
        provider.generate(MESSAGES)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 502, 503])
def test_status_errors_are_never_retried(provider, monkeypatch, status) -> None:
    """状态类错误（含 402）一次失败即抛出，绝不重试。"""
    calls = _count_calls(monkeypatch, _status_error(status))
    with pytest.raises(LLMError):
        provider.generate(MESSAGES)
    assert len(calls) == 1, f"status {status} 被重试了 {len(calls)} 次，应为 1 次"


def test_network_retry_succeeds_on_second_attempt(provider, monkeypatch) -> None:
    """首次网络失败、第二次成功时，应返回结果而不是抛错。"""
    monkeypatch.setattr("app.llm.bailian.time.sleep", lambda _s: None)
    calls: list[int] = []

    def fake(self, messages, temperature):
        calls.append(1)
        if len(calls) == 1:
            raise openai.APIConnectionError(message="flaky", request=_REQUEST)
        return "SELECT 1;"

    monkeypatch.setattr(BailianProvider, "_call_model", fake)
    assert provider.generate(MESSAGES) == "SELECT 1;"
    assert len(calls) == 2


# ===========================================================================
# J. Secret 隔离
# ===========================================================================


def test_402_exception_does_not_leak_body_or_key(provider, monkeypatch) -> None:
    body = (
        '{"error":{"message":"Insufficient account balance",'
        f'"key":"Bearer {FAKE_KEY}"}}}}'
    )
    _fake_call(monkeypatch, error=_status_error(402, body=body))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)

    exc = excinfo.value
    assert FAKE_KEY not in str(exc)
    assert FAKE_KEY not in repr(exc)
    assert "Bearer" not in str(exc)
    assert body not in str(exc)
    assert body not in repr(exc)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 418, 429, 500, 502, 503])
def test_no_status_leaks_key_or_body(provider, monkeypatch, status) -> None:
    body = f'{{"error":{{"key":"Bearer {FAKE_KEY}"}}}}'
    _fake_call(monkeypatch, error=_status_error(status, body=body))
    with pytest.raises(LLMError) as excinfo:
        provider.generate(MESSAGES)
    assert FAKE_KEY not in str(excinfo.value)
    assert FAKE_KEY not in repr(excinfo.value)
    assert body not in str(excinfo.value)


def test_unexpected_exception_does_not_leak(provider, monkeypatch) -> None:
    """未预期异常（含 Secret / URL）也必须被收敛成固定文案。"""
    _fake_call(
        monkeypatch,
        error=RuntimeError(f"boom {FAKE_KEY} at https://x.test/?api_key={FAKE_KEY}"),
    )
    with pytest.raises(LLMServiceUnavailableError) as excinfo:
        provider.generate(MESSAGES)

    exc = excinfo.value
    assert FAKE_KEY not in str(exc)
    assert FAKE_KEY not in repr(exc)
    assert "https://" not in str(exc)
    assert str(exc) == "Bailian request failed"


def test_no_exception_message_contains_url_or_traceback(provider, monkeypatch) -> None:
    for status in (401, 402, 429, 500, 418):
        _fake_call(monkeypatch, error=_status_error(status))
        with pytest.raises(LLMError) as excinfo:
            provider.generate(MESSAGES)
        message = str(excinfo.value)
        assert "dashscope.test" not in message
        assert "Traceback" not in message
        assert "File \"" not in message


def test_cause_chain_is_intentional_and_not_stringified(provider, monkeypatch) -> None:
    """__cause__ 保留上游异常（仅服务端日志用），但不进入 str / repr。

    与 MimoProvider 一致：raise ... from exc。这是刻意设计 ——
    客户端只看到固定文案，日志侧才需要原始异常对象。
    """
    body = f'{{"k":"{FAKE_KEY}"}}'
    _fake_call(monkeypatch, error=_status_error(402, body=body))
    with pytest.raises(LLMInsufficientBalanceError) as excinfo:
        provider.generate(MESSAGES)

    assert isinstance(excinfo.value.__cause__, openai.APIStatusError)
    assert FAKE_KEY not in str(excinfo.value)
    assert FAKE_KEY not in repr(excinfo.value)


def test_missing_key_message_does_not_contain_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "")
    monkeypatch.setattr(config, "BAILIAN_MODEL", DEFAULT_MODEL)
    with pytest.raises(LLMApiKeyNotConfiguredError) as excinfo:
        BailianProvider().generate(MESSAGES)
    assert str(excinfo.value) == "Bailian API key is not configured"
    assert FAKE_KEY not in str(excinfo.value)


# ===========================================================================
# K. Factory
# ===========================================================================


def test_factory_returns_bailian(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "bailian")
    p = get_llm_provider()
    assert isinstance(p, BailianProvider)
    assert p.name == "bailian"
    assert p.model == config.BAILIAN_MODEL


def test_factory_returns_mimo(monkeypatch) -> None:
    """LLM_PROVIDER=mimo 行为逐项不变（不真实调用 Mimo）。"""
    monkeypatch.setattr(config, "LLM_PROVIDER", "mimo")
    p = get_llm_provider()
    assert isinstance(p, MimoProvider)
    assert p.name == "mimo"


def test_factory_provider_name_is_case_insensitive(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "Bailian")
    assert isinstance(get_llm_provider(), BailianProvider)
    monkeypatch.setattr(config, "LLM_PROVIDER", "MIMO")
    assert isinstance(get_llm_provider(), MimoProvider)


def test_factory_unknown_provider_still_raises(monkeypatch) -> None:
    """未知 provider 的错误行为保持不变。"""
    monkeypatch.setattr(config, "LLM_PROVIDER", "deepseek")
    with pytest.raises(LLMProviderNotConfiguredError):
        get_llm_provider()


def test_factory_unknown_provider_message_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "local")
    with pytest.raises(LLMProviderNotConfiguredError) as excinfo:
        get_llm_provider()
    assert str(excinfo.value) == "Unsupported LLM provider: local"


_LAZY_PROBE = """
import sys
import app.llm.provider  # noqa: F401
leaked = "app.llm.bailian" in sys.modules
assert not leaked, "app.llm.bailian 被急切导入"
print("LAZY_OK")
"""


def test_bailian_is_lazily_imported() -> None:
    """§九：工厂对 bailian 必须保持 lazy import（子进程 + 全新解释器）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", _LAZY_PROBE],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "LAZY_OK"


_ENV_FACTORY_PROBE = """
from app.llm.provider import get_llm_provider
p = get_llm_provider()
print(f"{type(p).__name__}|{p.name}|{p.model}")
"""


def test_llm_provider_env_var_selects_bailian_end_to_end() -> None:
    """真正的 env -> config -> factory 链路（不经 monkeypatch）。

    验证 LLM_PROVIDER=bailian 这个环境变量名本身有效，
    且 Provider 构造不发起任何网络请求。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["LLM_PROVIDER"] = "bailian"

    result = subprocess.run(
        [sys.executable, "-c", _ENV_FACTORY_PROBE],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    cls_name, name, model = result.stdout.strip().splitlines()[-1].split("|")
    assert cls_name == "BailianProvider"
    assert name == "bailian"
    assert model == DEFAULT_MODEL


def test_app_imports_with_bailian_provider() -> None:
    """切到 bailian 后整个 app 仍可正常 import（不因 provider 切换而崩）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["LLM_PROVIDER"] = "bailian"

    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print('APP_OK')"],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "APP_OK"


# ===========================================================================
# 架构护栏（§一 / §十五）：AST 判据，不用字符串 grep
# ===========================================================================


def _iter_app_modules() -> list[Path]:
    return [
        p
        for p in sorted(APP_ROOT.rglob("*.py"))
        if "__pycache__" not in p.parts and LLM_ROOT not in p.parents
    ]


def test_upper_layers_have_no_provider_name_branching() -> None:
    """§一：除 app/llm/ 外，不得出现 provider 名字面量比较。

    用 AST 而不是 grep：注释 / 文档字符串里的 "Mimo" 不计入，
    真正的 `if provider == "bailian"` 一定会被抓住。
    """
    offenders: list[str] = []
    for path in _iter_app_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            for operand in operands:
                if isinstance(operand, ast.Constant) and operand.value in (
                    "bailian",
                    "mimo",
                ):
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert not offenders, f"上层出现 provider 名比较: {offenders}"


def test_upper_layers_do_not_import_bailian_directly() -> None:
    """§一：上层不得绕过 LLMProvider 抽象直接依赖具体 Provider。"""
    offenders: list[str] = []
    for path in _iter_app_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in ("app.llm.bailian", "app.llm.mimo"):
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("app.llm.bailian", "app.llm.mimo"):
                        offenders.append(
                            f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}"
                        )

    assert not offenders, f"上层直接 import 具体 Provider: {offenders}"


def test_mimo_module_is_untouched_by_design() -> None:
    """§十五：mimo.py 不得为「复用」而被改动。

    这里只做静态护栏：MimoProvider 的关键不变量仍在。
    （字节级「未改动」由 Task 42 的 SHA256 隔离报告给出。）
    """
    assert MimoProvider.name == "mimo"
    assert hasattr(MimoProvider, "_map_status_error")
    assert MimoProvider.__module__ == "app.llm.mimo"


# ===========================================================================
# §十一 真实 API 冒烟
#
# Task 70 起改为**显式 Opt-in**：默认一律 SKIP；
# 只有 RUN_REAL_LLM_SMOKE=1 **且** DASHSCOPE_API_KEY 存在时才可能真实联网。
#
# 旧判据 `skipif(not os.getenv("DASHSCOPE_API_KEY"))` 已废弃 ——
# 生产 .env 里一直配着该 key，于是"有 key"等价于"跑全量测试就自动联网"，
# 只能靠人工 `DASHSCOPE_API_KEY="" ... --deselect ...` 绕开。
# 判定表与两条不可动摇的规则见 `tests/real_llm_smoke_gate.py`。
# ===========================================================================

_REAL_SMOKE_ENABLED, _REAL_SMOKE_REASON = _real_llm_smoke_gate()


@pytest.mark.skipif(
    not _REAL_SMOKE_ENABLED,
    reason=_REAL_SMOKE_REASON,
)
def test_real_bailian_smoke() -> None:
    """一次极小真实调用：要求模型只返回 SELECT 1;。

    只记录 success / latency / provider / model；
    绝不记录 API Key / Authorization / 完整 request / 完整 response body。
    """
    real = BailianProvider()
    started = time.perf_counter()
    content = real.generate(
        [
            {
                "role": "user",
                "content": "只输出一条 SQL，不要任何解释：SELECT 1;",
            }
        ],
        temperature=0.0,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0

    assert content.strip(), "真实冒烟返回了空 content"
    assert real.model == config.BAILIAN_MODEL
    assert real.name == "bailian"

    print(
        f"\n[real-smoke] success=True provider={real.name} "
        f"model={real.model} latency_ms={latency_ms:.1f}"
    )
