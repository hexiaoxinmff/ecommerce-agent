"""Alibaba Cloud Bailian（阿里云百炼 / Model Studio）Provider。

OpenAI SDK 只允许出现在 Provider 层（``app/llm/mimo.py`` 与本模块）；
上层（SchemaLinker / SQLGenerator / Repairer / Agent / API 路由）
一律只依赖 ``LLMProvider`` 抽象，不得出现
``if provider == "bailian"`` 之类业务分支。

定位：**低消费优先**的备选 Provider，与 ``MimoProvider`` 平行、互不依赖。
默认模型 ``qwen3.7-flash-2026-07-15``。
thinking **强制关闭且不可配置**（``extra_body={"enable_thinking": False}``
是写死的字面量，没有任何环境变量开关）—— thinking 的推理链按 output token
计费，低消费是本项目的硬约束。

API Key 唯一来源：``DASHSCOPE_API_KEY``（刻意不支持 ``BAILIAN_API_KEY``，
避免同一个 Secret 出现两条读取路径）。

错误映射（异常消息仅用于日志，客户端文案由 API 路由按类型固定映射）：
- HTTP 401            -> LLMAuthenticationError
- HTTP 403            -> LLMAuthenticationError（认证失败）
- HTTP 403 + 配额错误码 -> LLMQuotaError（AllocationQuota.*：免费额度 /
  配额分配耗尽。Key 本身有效，绝不能误报成认证失败，二者处置相反）
- HTTP 402       -> LLMInsufficientBalanceError（余额不足，与 5xx 严格区分）
- HTTP 429       -> LLMRateLimitError
- HTTP 5xx       -> LLMServiceUnavailableError
- 其他 4xx       -> LLMServiceUnavailableError（受控兜底：固定文案，不透传上游体）
- 超时           -> LLMTimeoutError
- 其他网络错误   -> LLMNetworkError
- 其余未分类错误 -> LLMServiceUnavailableError（固定文案，不泄漏底层信息）

可分类的异常统一携带 ``http_status``（上游 HTTP 状态码），供诊断与 Benchmark 使用。
Task66 起还携带 ``provider_error_code``（经白名单校验的结构化错误码，如
``AllocationQuota.FreeTierOnly``），用于区分同为 403 的「额度用尽」与
「endpoint 不可用」；异常类与文案本身不变。

重试语义：与 ``MimoProvider`` 保持一致 —— SDK 层 ``max_retries=0``；
仅对**网络类**错误在 Provider 层做有限重试（最多 2 次，间隔递增）。
认证 / 限流 / 超时 / 5xx / 余额不足等错误一次失败即明确失败。
不新增任何其他重试层，也不做指数退避或熔断。
"""

import json
import re
import time

import openai

from app.core import config
from app.llm.model_pool import ERROR_CODE_FREE_QUOTA_EXHAUSTED
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
)

Message = dict[str, str]

# 与 MimoProvider 相同的有限重试：仅网络类错误，最多 2 次，间隔递增。
# 网络层失败通常不计费，因此该重试不构成额外成本。
_NETWORK_RETRY_DELAYS_SECONDS = (2.0, 5.0)

# 允许作为 ``provider_error_code`` 透出的上游错误码形态。
# 形如 "AllocationQuota.FreeTierOnly" / "Endpoint.AccessDenied"。
# 严格限定字符集（必须以字母开头，只允许字母/数字/下划线/点）与长度：
# 任何含空格、引号、冒号、连字符的内容（例如 "Bearer sk-xxx"）都不可能通过，
# 这是「绝不透传响应体原文」的第二道闸门。
_ERROR_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,63}$")

# 配额错误码族：百炼把「免费额度 / 配额分配耗尽」也返回为 HTTP 403，
# 与认证失败仅靠状态码不可区分，必须按错误码二次分类。
# 前缀取自百炼配额类错误码命名空间；具体已确认的码
# （AllocationQuota.FreeTierOnly）与 fallback_router 分类共用
# model_pool 的唯一权威常量。
_QUOTA_CODE_PREFIX = "AllocationQuota."


class BailianProvider:
    """基于 DashScope OpenAI 兼容模式的百炼实现（低消费优先）。"""

    name = "bailian"

    def __init__(self, *, model: str | None = None) -> None:
        """构造 Provider。

        model：可选覆盖。为 None 时读取 ``config.BAILIAN_MODEL``（默认行为，
        与改动前完全一致）。Task66 的 Fallback Router 需要「同一份代码按不同
        model_id 构造实例」，因此开放这一个只读覆盖点；它不引入任何新配置项，
        也不改变 thinking 锁死 / Key 唯一来源等既有不变量。
        """
        self._api_key = config.DASHSCOPE_API_KEY
        self._base_url = config.BAILIAN_BASE_URL
        self._model = model if model else config.BAILIAN_MODEL
        self._timeout = config.BAILIAN_TIMEOUT
        # 惰性创建、实例内复用（与 MimoProvider 同构）：
        # 每次调用重建客户端会白白丢掉连接池与 TLS 会话。
        self._client: openai.OpenAI | None = None

    def _get_client(self) -> openai.OpenAI:
        """返回实例级复用的 OpenAI 客户端（首次调用时创建）。"""
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=0,  # 本阶段不做 SDK 层自动重试
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
        """调用百炼生成文本；一次调用失败即抛出对应 LLMError。

        例外：仅对网络类错误做有限次重试（最多 2 次，间隔递增），
        与 MimoProvider 语义一致；认证 / 限流 / 超时 / 5xx / 余额不足
        等错误仍然一次失败即明确失败。
        """
        if not self._api_key:
            raise LLMApiKeyNotConfiguredError("Bailian API key is not configured")
        if not self._model:
            raise LLMProviderNotConfiguredError("Bailian model is not configured")
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
            raise LLMTimeoutError("Bailian request timeout") from exc
        except openai.APIConnectionError as exc:
            raise LLMNetworkError("Bailian network error") from exc
        except openai.APIStatusError as exc:
            raise self._map_status_error(exc) from exc
        except LLMError:
            raise
        except Exception as exc:
            # 其余未预期错误：客户端只看到固定安全文案
            raise LLMServiceUnavailableError("Bailian request failed") from exc

    def _call_model(self, messages: list[Message], temperature: float) -> str:
        """执行真实 API 调用（仅本层允许使用 openai SDK）。

        兼容性说明（依据阿里云百炼 OpenAI 兼容模式文档）：
        - qwen3 系列默认可能开启 thinking（深度思考）；开启时推理内容
          按 output token 计费，且会显著抬高延迟；
        - 本任务优先级为「低消费 > 稳定 > 结构化 SQL 输出 > 推理能力」，
          因此关闭 thinking。
        - 与 MimoProvider 用 ``extra_body={"thinking": {"type": "disabled"}}``
          关闭思考是同一手法（extra_body 透传非标准字段，先例已存在）。

        ⭐ ``enable_thinking`` 在此**物理锁死为 False**：值是字面量，
        不来自任何配置项，环境变量无法覆盖。刻意不提供
        ``BAILIAN_ENABLE_THINKING`` 开关 —— 低消费是本项目的硬约束，
        不该留一个能被误开的旋钮。

        也不传 max_tokens / thinking_budget / 任何额外 reasoning 参数：
        不扩大输出预算，也不引入多候选 / 重复调用。
        """
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            extra_body={"enable_thinking": False},
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _extract_error_code(exc: openai.APIStatusError) -> str | None:
        """从上游响应体中提取结构化错误码；提取不到或形态非法时返回 None。

        背景（Task66 §2）：百炼对「免费额度用尽」（``AllocationQuota.FreeTierOnly``）
        与「endpoint 不可用」（``Endpoint.AccessDenied``）**都**返回 HTTP 403。
        只看状态码无法区分，而两者处置相反，因此必须把 code 单独带出来。

        只读取 OpenAI 兼容模式约定的两个位置：
          - ``body["error"]["code"]``
          - ``body["code"]``
        body 可能是 dict，也可能是 JSON 字符串（取决于 SDK/响应形态）。

        安全约束：返回值必须通过 ``_ERROR_CODE_RE`` 白名单校验，
        否则一律 None —— 宁可让消费方走保守分支，也不透传响应体原文。
        """
        body = getattr(exc, "body", None)
        payload: object = None
        if isinstance(body, dict):
            payload = body
        elif isinstance(body, str):
            try:
                payload = json.loads(body)
            except (ValueError, TypeError):
                return None
        if not isinstance(payload, dict):
            return None

        code: object = None
        error_field = payload.get("error")
        if isinstance(error_field, dict):
            code = error_field.get("code")
        if not isinstance(code, str):
            code = payload.get("code")
        if not isinstance(code, str):
            return None

        code = code.strip()
        return code if _ERROR_CODE_RE.match(code) else None

    @staticmethod
    def _map_status_error(exc: openai.APIStatusError) -> LLMError:
        """把上游 HTTP 状态错误映射为统一 LLMError。

        分类（互相独立，不可合并）：
        - 401           -> LLMAuthenticationError
        - 403（无配额码）-> LLMAuthenticationError
        - 403 + AllocationQuota.* -> LLMQuotaError（免费额度 / 配额分配耗尽；
          Key 本身有效，与认证失败处置相反，绝不能误报成 authentication failed）
        - 402       -> LLMInsufficientBalanceError（账户额度问题，重试无意义）
        - 429       -> LLMRateLimitError
        - >= 500    -> LLMServiceUnavailableError
        - 其他 4xx  -> LLMServiceUnavailableError（受控兜底，与 Mimo 同构）

        所有分支只写入固定文案 + http_status，绝不透传上游响应体 /
        Authorization / URL / traceback。

        Task66 补充：所有分支额外附带 ``provider_error_code``
        （经白名单校验的结构化错误码，取不到则为 None）。
        Phase 4 修正：403 且错误码属于配额族（``AllocationQuota.*``，含
        ``AllocationQuota.FreeTierOnly``）时改判 ``LLMQuotaError``，
        原始错误码仍随异常携带（不吞掉上游结构化信息）；其余 403
        （含 ``Endpoint.AccessDenied`` 与无错误码的 403）保持
        ``LLMAuthenticationError`` 既有语义不变。
        """
        status_code = exc.status_code
        error_code = BailianProvider._extract_error_code(exc)
        if status_code in (401, 403):
            if status_code == 403 and error_code is not None and error_code.startswith(
                _QUOTA_CODE_PREFIX
            ):
                return LLMQuotaError(
                    "Bailian provider quota exhausted (free tier allocation)",
                    http_status=status_code,
                    provider_error_code=error_code,
                )
            return LLMAuthenticationError(
                "Bailian authentication failed",
                http_status=status_code,
                provider_error_code=error_code,
            )
        if status_code == 402:
            return LLMInsufficientBalanceError(
                "Bailian insufficient account balance",
                http_status=status_code,
                provider_error_code=error_code,
            )
        if status_code == 429:
            return LLMRateLimitError(
                "Bailian rate limited",
                http_status=status_code,
                provider_error_code=error_code,
            )
        if status_code >= 500:
            return LLMServiceUnavailableError(
                "Bailian service unavailable",
                http_status=status_code,
                provider_error_code=error_code,
            )
        return LLMServiceUnavailableError(
            "Bailian request failed",
            http_status=status_code,
            provider_error_code=error_code,
        )
