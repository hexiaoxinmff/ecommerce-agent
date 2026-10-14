"""本地 LLM Provider 适配器（benchmark-only，Task 39-L）。

定位
----
本模块是 **engineering benchmark 专用** 的本地 provider：

    自然语言问题 -> Schema Link -> SQL Generate -> SQL Safety
                 -> SQL Execute -> (Repair) -> Result

它 **不是** 生产 provider，也 **不接入生产工厂**：

- ``get_llm_provider()`` 不变（仍只认 mimo）；
- ``mimo.py`` 不变；
- 生产 Prompt / Few-shot / Benchmark / DB 不变。

上层用法（仅 benchmark wrapper 使用）::

    from app.llm.local_provider import LocalProvider

    provider = LocalProvider()              # 从 LOCAL_LLM_* 环境变量读取
    components = AgentComponents(...)       # 显式注入，绕过 get_llm_provider()

约束
----
- **不使用 openai SDK**：本项目的既定铁律是 openai SDK 只允许出现在
  ``app/llm/mimo.py``。本模块用标准库 ``urllib`` 直连 OpenAI-compatible
  ``/chat/completions``。
- **只读环境变量**：API Key 若本地服务要求，只从 ``LOCAL_LLM_API_KEY``
  读取，绝不写死、绝不落盘、绝不进报告。
- **绕过代理**：本地回环地址不应走 HTTP_PROXY，否则会被代理拦截
  （实测出现 ``upstream connect failed``）。

错误映射（与 ``provider.py`` 的既有异常族完全一致）
--------------------------------------------------
- 连接失败 / DNS           -> LLMNetworkError
- 超时                     -> LLMTimeoutError
- HTTP 401 / 403           -> LLMAuthenticationError
- HTTP 402                 -> LLMInsufficientBalanceError
- HTTP 429                 -> LLMRateLimitError
- HTTP >= 500              -> LLMServiceUnavailableError
- 其他 4xx / 响应结构非法  -> LLMServiceUnavailableError

所有可分类异常都带上 ``http_status``，便于 benchmark 统计 provider 失败。
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from app.llm.provider import (
    LLMAuthenticationError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)

Message = dict[str, str]

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_TIMEOUT = 300.0

# 仅用于「第一个可调用模型」的确定性筛选：名字里含这些片段的一律视为
# embedding 模型（它们没有 completion 能力，不能驱动 Text2SQL 流水线）。
# 这是**能力筛选**，不是「按模型强弱排名」。
_EMBEDDING_NAME_HINTS = ("embed",)


def is_embedding_model(model_id: str) -> bool:
    """判断模型名是否指向 embedding 模型（无 completion 能力）。"""
    low = (model_id or "").lower()
    return any(hint in low for hint in _EMBEDDING_NAME_HINTS)


def select_first_chat_model(model_ids: list[str]) -> str | None:
    """按 provider 返回顺序取第一个非 embedding 模型（确定性，不按强弱排序）。

    选择依据只有三条：已存在（在列表里）+ 可调用（非 embedding）+
    OpenAI-compatible（由 provider 的 /v1/models 列表本身保证）。
    """
    for model_id in model_ids:
        if not is_embedding_model(model_id):
            return model_id
    return None


def _no_proxy_opener() -> urllib.request.OpenerDirector:
    """构造绕过一切代理的 opener（本地回环不应走 HTTP_PROXY）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def list_models(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout: float = 10.0,
    api_key: str = "",
) -> list[str]:
    """读取 OpenAI-compatible ``/v1/models``，返回模型 id 列表（不调用 chat）。

    Raises:
        LLMNetworkError: 服务不可达 / 连接被拒。
        LLMTimeoutError: 请求超时。
        LLMError: 上游返回非 2xx 或响应结构非法。
    """
    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(url, method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    opener = _no_proxy_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _map_status_error(exc) from exc
    except urllib.error.URLError as exc:
        raise _map_url_error(exc) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise LLMTimeoutError("local model list timeout") from exc
    except json.JSONDecodeError as exc:
        raise LLMServiceUnavailableError("local model list malformed") from exc

    data = payload.get("data")
    if not isinstance(data, list):
        raise LLMServiceUnavailableError("local model list malformed")
    ids: list[str] = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("id"):
            ids.append(str(entry["id"]))
    return ids


def _map_url_error(exc: urllib.error.URLError) -> LLMError:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return LLMTimeoutError("local model timeout")
    if isinstance(reason, socket.gaierror):
        return LLMNetworkError("local model host resolution failed")
    return LLMNetworkError("local model network error")


def _map_status_error(exc: urllib.error.HTTPError) -> LLMError:
    status = exc.code
    if status in (401, 403):
        return LLMAuthenticationError("local model auth failed", http_status=status)
    if status == 402:
        return LLMInsufficientBalanceError(
            "local model insufficient balance", http_status=status
        )
    if status == 429:
        return LLMRateLimitError("local model rate limited", http_status=status)
    if status >= 500:
        return LLMServiceUnavailableError(
            "local model service unavailable", http_status=status
        )
    return LLMServiceUnavailableError("local model request failed", http_status=status)


@dataclass
class ProviderCallStats:
    """provider 侧调用统计（用于把 E2E 延迟拆成 provider / non-LLM 两段）。"""

    calls: int = 0
    failures: int = 0
    total_ms: float = 0.0
    durations_ms: list[float] = field(default_factory=list)

    def record(self, duration_ms: float, *, ok: bool) -> None:
        self.calls += 1
        self.total_ms += duration_ms
        self.durations_ms.append(duration_ms)
        if not ok:
            self.failures += 1

    def reset(self) -> None:
        self.calls = 0
        self.failures = 0
        self.total_ms = 0.0
        self.durations_ms = []


class LocalProvider:
    """OpenAI-compatible 本地模型 provider（benchmark-only）。

    实现 ``LLMProvider`` Protocol（name / model / generate）。
    """

    name = "local"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        auto_select_model: bool = True,
    ) -> None:
        self._base_url = (
            base_url
            or os.getenv("LOCAL_LLM_BASE_URL", "").strip()
            or DEFAULT_BASE_URL
        )
        self._api_key = (
            api_key
            if api_key is not None
            else os.getenv("LOCAL_LLM_API_KEY", "").strip()
        )
        self._timeout = timeout or _env_positive_float(
            "LOCAL_LLM_TIMEOUT", DEFAULT_TIMEOUT
        )
        self._model = (model or os.getenv("LOCAL_LLM_MODEL", "").strip())
        if not self._model and auto_select_model:
            self._model = self.select_model() or ""
        self.stats = ProviderCallStats()

    # ---------- 发现 ----------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    def list_models(self) -> list[str]:
        return list_models(
            self._base_url, timeout=min(self._timeout, 15.0), api_key=self._api_key
        )

    def select_model(self) -> str | None:
        """按 provider 列表顺序取第一个非 embedding 模型。"""
        return select_first_chat_model(self.list_models())

    # ---------- 调用 ----------

    def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
    ) -> str:
        """调用本地 ``/chat/completions``，返回助手文本。

        每次调用（无论成败）都记录耗时到 ``self.stats``，
        便于把 E2E 延迟拆分为 provider / non-LLM 两段。
        """
        if not self._model:
            raise LLMServiceUnavailableError("local model is not selected")
        start = time.perf_counter()
        try:
            text = self._request(messages, temperature)
        except Exception:
            self.stats.record((time.perf_counter() - start) * 1000.0, ok=False)
            raise
        self.stats.record((time.perf_counter() - start) * 1000.0, ok=True)
        return text

    def _request(self, messages: list[Message], temperature: float) -> str:
        url = self._base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(
            {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        if self._api_key:
            request.add_header("Authorization", f"Bearer {self._api_key}")
        opener = _no_proxy_opener()
        try:
            with opener.open(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise _map_status_error(exc) from exc
        except urllib.error.URLError as exc:
            raise _map_url_error(exc) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise LLMTimeoutError("local model timeout") from exc
        except json.JSONDecodeError as exc:
            raise LLMServiceUnavailableError("local model response malformed") from exc
        return _extract_content(payload)


def _extract_content(payload: dict) -> str:
    """从 OpenAI-compatible 响应中提取助手文本。

    兼容两类返回：
    - 常规：``choices[0].message.content``；
    - thinking 模型：content 为空时回落到 ``choices[0].message.reasoning``。
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMServiceUnavailableError("local model response missing choices")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    reasoning = message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    # content 为空字符串是合法返回（模型确实没说话），按空串处理，
    # 由上层 validator 判定为输出非法，而不是伪装成 provider 故障。
    if isinstance(content, str):
        return content
    raise LLMServiceUnavailableError("local model response missing content")


def _env_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default
