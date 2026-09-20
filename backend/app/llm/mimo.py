"""Mimo V2.5 Pro Provider（OpenAI-compatible 实现）。

OpenAI SDK 只允许出现在本 Provider 层；上层一律通过 LLMProvider 抽象调用。

错误映射（异常消息仅用于日志，客户端文案由 API 路由按类型固定映射）：
- HTTP 401 / 403 -> LLMAuthenticationError
- HTTP 402       -> LLMInsufficientBalanceError（账户余额不足，与 5xx 严格区分）
- HTTP 429       -> LLMRateLimitError
- HTTP 5xx       -> LLMServiceUnavailableError
- 超时           -> LLMTimeoutError
- 其他网络错误   -> LLMNetworkError
- 其余未分类错误 -> LLMServiceUnavailableError（固定文案，不泄漏底层信息）

可分类的异常统一携带 http_status（上游 HTTP 状态码），供诊断与 Benchmark 使用。

本阶段规则：SDK 层 max_retries=0；仅对网络类错误在 Provider 层做
一次有限重试（官方端点偶发单连接断开，见 generate() 说明），
认证/限流/超时/5xx/余额不足等错误一次失败即明确失败。不做指数退避/熔断。
"""

import time

import openai

from app.core import config
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMProviderNotConfiguredError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)

Message = dict[str, str]

# 官方端点实测存在偶发的单连接主动断开 / 间歇性不可用；
# 仅对网络类错误做有限重试（最多 2 次，间隔递增），
# 不做指数退避/熔断等复杂机制。
_NETWORK_RETRY_DELAYS_SECONDS = (2.0, 5.0)


class MimoProvider:
    """基于 OpenAI-compatible API 的 Mimo V2.5 Pro 实现。"""

    name = "mimo"

    def __init__(self) -> None:
        self._api_key = config.MIMO_API_KEY
        self._base_url = config.MIMO_BASE_URL
        self._model = config.MIMO_MODEL
        self._timeout = config.MIMO_TIMEOUT
        # 惰性创建、实例内复用：Task 29 Phase 1 实测每次调用重建客户端
        # 需 14.9 ms（最坏 403 ms），且无法复用连接池与 TLS 会话。
        self._client: openai.OpenAI | None = None

    def _get_client(self) -> openai.OpenAI:
        """返回实例级复用的 OpenAI 客户端（首次调用时创建）。"""
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=0,  # 本阶段不做自动重试
            )
        return self._client

    @property
    def model(self) -> str:
        return self._model

    def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
    ) -> str:
        """调用 Mimo 生成文本；一次调用失败即抛出对应 LLMError。

        例外：仅对网络类错误（官方端点偶发单连接断开 / 间歇性不可用，
        已在真实联调中实测确认）做有限次重试（最多 2 次，间隔递增）；
        认证/限流/超时/5xx 等错误仍然一次失败即明确失败。
        """
        if not self._api_key:
            raise LLMApiKeyNotConfiguredError("Mimo API key is not configured")
        if not self._model:
            raise LLMProviderNotConfiguredError("Mimo model is not configured")
        try:
            return self._request(messages, temperature)
        except LLMNetworkError:
            for delay in _NETWORK_RETRY_DELAYS_SECONDS:
                time.sleep(delay)
                try:
                    return self._request(messages, temperature)
                except LLMNetworkError:
                    continue
            raise

    def _request(self, messages: list[Message], temperature: float) -> str:
        """执行一次真实调用并把第三方异常映射为统一 LLMError。"""
        try:
            return self._call_model(messages, temperature)
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError("Mimo request timeout") from exc
        except openai.APIConnectionError as exc:
            raise LLMNetworkError("Mimo network error") from exc
        except openai.APIStatusError as exc:
            raise self._map_status_error(exc) from exc
        except LLMError:
            raise
        except Exception as exc:
            # 其余未预期错误：客户端只看到固定安全文案
            raise LLMServiceUnavailableError("Mimo request failed") from exc

    def _call_model(self, messages: list[Message], temperature: float) -> str:
        """执行真实 API 调用（仅本层允许使用 openai SDK）。

        兼容性说明（依据 Xiaomi MiMo 官方文档）：
        - mimo-v2.5-pro 默认开启深度思考（thinking），该模式下
          temperature/top_p 会被服务端强制为推荐默认值；
        - 本阶段要求 temperature=0 低随机性且仅做连接测试，
          因此通过官方参数关闭深度思考（thinking.type=disabled），
          响应更快、temperature 语义成立。
        """
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _map_status_error(exc: openai.APIStatusError) -> LLMError:
        """把上游 HTTP 状态错误映射为统一 LLMError。

        分类（互相独立，不可合并）：
        - 401 / 403 -> LLMAuthenticationError
        - 402       -> LLMInsufficientBalanceError（账户余额不足，重试无意义）
        - 429       -> LLMRateLimitError
        - >= 500    -> LLMServiceUnavailableError
        - 其他 4xx  -> LLMServiceUnavailableError（保持既有兜底语义）

        所有分支都把上游 status_code 写入异常的 http_status 字段，
        便于诊断与 Benchmark 记录（不泄漏下游 URL/Secret）。
        """
        status_code = exc.status_code
        if status_code in (401, 403):
            return LLMAuthenticationError(
                "Mimo authentication failed", http_status=status_code
            )
        if status_code == 402:
            return LLMInsufficientBalanceError(
                "Mimo insufficient account balance", http_status=status_code
            )
        if status_code == 429:
            return LLMRateLimitError(
                "Mimo rate limited", http_status=status_code
            )
        if status_code >= 500:
            return LLMServiceUnavailableError(
                "Mimo service unavailable", http_status=status_code
            )
        return LLMServiceUnavailableError(
            "Mimo request failed", http_status=status_code
        )