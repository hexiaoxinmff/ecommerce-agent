"""统一 LLM Provider 抽象、异常体系与工厂。

上层模块（API 路由、未来的 Text2SQL / LangGraph / Schema Linking 等）
只依赖本模块的 LLMProvider 抽象与 LLMError 异常类型，
不直接 import 任何第三方 SDK（如 openai），也不感知具体模型服务（如 Mimo）。

当前实现：
    LLMProvider（抽象）
         ↑
    ├── MimoProvider（默认实现，OpenAI-compatible）
    └── BailianProvider（阿里云百炼，OpenAI-compatible，低消费优先）

Provider 分派唯一入口是本模块的 get_llm_provider()；
上层不得出现 `if provider == "xxx"` 之类业务分支。

Task66 补充：本模块新增可选的 ``provider_error_code``（上游结构化错误码）
与 ``provider_error_code_of()`` 读取助手。它是「免费额度用尽」与
「endpoint 不可用」这两类同为 HTTP 403 的错误唯一可区分之处。
字段默认 None，因此对既有调用方零影响。
"""

from typing import Protocol

from app.core import config


class LLMProvider(Protocol):
    """统一 LLM Provider 最小接口。

    上层只通过该接口调用模型；换模型时上层代码无需重写。
    """

    name: str
    model: str

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
    ) -> str:
        """输入标准 messages（role/content），返回统一文本结果。"""
        ...


class LLMError(Exception):
    """LLM 层统一异常基类。

    约定：异常消息仅用于服务端日志定位；面向 API 客户端的文案由
    API 路由按异常类型映射为固定内容，绝不包含 Secret / URL /
    traceback / 文件路径。

    http_status：可选的「上游 HTTP 状态」。仅在能从上游响应明确判定时填写，
    供诊断与 Benchmark 记录使用；默认 None，不改变任何现有子类的行为。

    provider_error_code：可选的「上游结构化错误码」（Task66 新增）。
    典型取值 ``AllocationQuota.FreeTierOnly`` / ``Endpoint.AccessDenied``。
    它存在的唯一理由是：百炼把「免费额度用尽」与「endpoint 不可用」**都**返回
    HTTP 403，只看状态码无法区分，而这两者的处置完全相反
    （前者可切换下一个免费模型，后者不可声称额度耗尽）。

    约束：该字段只承载「已归一化、经正则白名单校验的短标识符」，
    **绝不承载响应体原文**；未识别或形态非法时一律为 None
    （此时消费方必须走保守分支，而不是猜测）。默认 None，
    因此不改变任何现有子类的行为。
    """

    def __init__(
        self,
        message: str = "",
        *,
        http_status: int | None = None,
        provider_error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.provider_error_code = provider_error_code


class LLMProviderNotConfiguredError(LLMError):
    """Provider 未正确配置（不支持的 Provider 名、缺少必要配置等）。"""


class LLMApiKeyNotConfiguredError(LLMProviderNotConfiguredError):
    """未配置 API Key。"""


class LLMAuthenticationError(LLMError):
    """上游认证失败（HTTP 401，以及未携带配额错误码的 403）。"""


class LLMQuotaError(LLMError):
    """上游配额 / 额度分配耗尽（HTTP 403 + ``AllocationQuota.*`` 错误码）。

    背景：百炼把「免费额度用尽」（``AllocationQuota.FreeTierOnly``）与
    「认证失败」都返回 HTTP 403，只看状态码会把额度问题误报成
    「认证失败」，让用户误以为 Key 无效。本类与 LLMAuthenticationError
    严格区分：前者是「配额 / 额度分配」问题（Key 本身有效），
    后者是「身份认证」问题。两者都不继承对方，http_status 与
    provider_error_code 语义同 LLMError 基类。
    """


class LLMInsufficientBalanceError(LLMError):
    """上游账户余额不足（HTTP 402）。

    与 LLMServiceUnavailableError 严格区分：402 表示「请求方账户额度问题」，
    重试不会改善；5xx 表示「上游服务端故障」，属不同故障域。
    因此本类直接继承 LLMError，而非 LLMServiceUnavailableError。
    """


class LLMRateLimitError(LLMError):
    """上游限流（HTTP 429）。"""


class LLMServiceUnavailableError(LLMError):
    """上游服务不可用（HTTP 5xx 等）。"""


class LLMTimeoutError(LLMError):
    """调用超时。"""


class LLMNetworkError(LLMError):
    """网络层错误（连接失败等）。"""


def provider_error_code_of(exc: BaseException) -> str | None:
    """安全读取异常携带的上游结构化错误码（Task66）。

    非 LLMError、或未携带该字段时返回 None —— 调用方必须把 None
    当作「不可判定」走保守分支，绝不可当作「不是额度问题」以外的任何假设。
    """
    code = getattr(exc, "provider_error_code", None)
    return code if isinstance(code, str) and code else None


def get_llm_provider() -> LLMProvider:
    """根据 LLM_PROVIDER 配置返回 Provider 实例（当前支持 mimo / bailian）。

    Task66 说明：当且仅当「bailian + 已显式配置备用模型池 + 未锁定模型」时，
    返回 ``FreeTierFallbackRouter``（它同样满足 ``LLMProvider`` Protocol，
    上层调用方式 ``provider.generate(...)`` 完全不变）。
    默认配置下（``BAILIAN_FALLBACK_MODELS`` 为空 / ``LLM_MODEL_LOCK=true``）
    返回裸 ``BailianProvider``，行为与既有单模型模式逐项一致。

    Raises:
        LLMProviderNotConfiguredError: 配置了尚未支持的 Provider。
        ModelPoolConfigError: 备用模型池配置非法（仅在校验分支触发）。
    """
    provider_name = config.LLM_PROVIDER.lower()
    if provider_name == "mimo":
        from app.llm.mimo import MimoProvider  # 延迟导入，避免模块循环依赖

        return MimoProvider()
    if provider_name == "bailian":
        from app.llm.bailian import BailianProvider  # 延迟导入，同上

        # 以下导入刻意放在函数体内：app.llm.provider 必须保持
        # 「不急切加载 bailian」的性质（既有子进程探针测试会检查）。
        from app.llm.model_pool import BailianModelPool

        pool = BailianModelPool.from_env()
        if pool.fallback_router_enabled:
            pool.validate()
            from app.llm.fallback_router import (
                FreeTierFallbackRouter,
                build_bailian_provider,
            )

            return FreeTierFallbackRouter(
                pool=pool, provider_factory=build_bailian_provider
            )
        if pool.fallbacks:
            # 锁模式 + 已配置备用池：仍是单模型语义，但模型必须固定为 primary
            # （§13/§15：正式 run 一次 = 一个固定 model）。
            pool.validate()
            return BailianProvider(model=pool.primary)
        return BailianProvider()
    raise LLMProviderNotConfiguredError(
        f"Unsupported LLM provider: {provider_name}"
    )