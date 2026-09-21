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
    """

    def __init__(self, message: str = "", *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class LLMProviderNotConfiguredError(LLMError):
    """Provider 未正确配置（不支持的 Provider 名、缺少必要配置等）。"""


class LLMApiKeyNotConfiguredError(LLMProviderNotConfiguredError):
    """未配置 API Key。"""


class LLMAuthenticationError(LLMError):
    """上游认证失败（HTTP 401 / 403）。"""


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


def get_llm_provider() -> LLMProvider:
    """根据 LLM_PROVIDER 配置返回 Provider 实例（当前支持 mimo / bailian）。

    Raises:
        LLMProviderNotConfiguredError: 配置了尚未支持的 Provider。
    """
    provider_name = config.LLM_PROVIDER.lower()
    if provider_name == "mimo":
        from app.llm.mimo import MimoProvider  # 延迟导入，避免模块循环依赖

        return MimoProvider()
    if provider_name == "bailian":
        from app.llm.bailian import BailianProvider  # 延迟导入，同上

        return BailianProvider()
    raise LLMProviderNotConfiguredError(
        f"Unsupported LLM provider: {provider_name}"
    )