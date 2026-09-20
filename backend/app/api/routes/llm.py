"""LLM 连接测试路由。

POST /api/llm/test
仅用于验证 FastAPI -> LLMProvider -> MimoProvider -> Mimo API 链路。
不是聊天接口，不涉及 Text2SQL / LangGraph / SQL 校验。

错误状态码约定（保持一致）：
- LLMApiKeyNotConfiguredError（Key 未配置）          -> 503
- LLMProviderNotConfiguredError（Provider 配置有误） -> 503
- LLMAuthenticationError（上游 401/403）             -> 502
- LLMRateLimitError（上游 429）                      -> 503
- LLMServiceUnavailableError（上游 5xx 等）          -> 503
- LLMTimeoutError（超时）                            -> 503
- LLMNetworkError（网络错误）                        -> 503
- 其他未预期异常                                     -> 503（固定文案）

客户端文案全部为固定映射，绝不回显底层异常文本（防 Secret/路径泄漏）。
"""

from fastapi import APIRouter, Response

from app.core import config
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
    LLMError,
    LLMNetworkError,
    LLMProviderNotConfiguredError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    get_llm_provider,
)
from app.schemas.llm import LlmTestRequest, LlmTestResponse

router = APIRouter(tags=["llm"])

SYSTEM_PROMPT = (
    "你是电商智能数据分析 Agent 的语言模型组件。"
    "当前仅用于验证模型连接。"
    "不要执行 SQL，不访问数据库，不假设已经连接数据库。"
    "请准确、简洁地回答用户输入。"
)

# 异常类型 -> (HTTP 状态码, 面向客户端的固定文案)
_LLM_FAILURES: dict[type[LLMError], tuple[int, str]] = {
    LLMApiKeyNotConfiguredError: (503, "Mimo API key is not configured"),
    LLMProviderNotConfiguredError: (503, "LLM provider is not configured"),
    LLMAuthenticationError: (502, "Mimo authentication failed"),
    LLMRateLimitError: (503, "Mimo rate limited"),
    LLMServiceUnavailableError: (503, "Mimo service unavailable"),
    LLMTimeoutError: (503, "Mimo request timeout"),
    LLMNetworkError: (503, "Mimo network error"),
}


def _map_failure(exc: LLMError) -> tuple[int, str]:
    """按异常类型（含继承链）映射为固定状态码与客户端文案。"""
    for cls in type(exc).__mro__:
        if cls in _LLM_FAILURES:
            return _LLM_FAILURES[cls]
    return 503, "Mimo request failed"


@router.post(
    "/llm/test",
    response_model=LlmTestResponse,
    summary="LLM 连接测试（真实调用当前 Provider）",
)
def llm_test(request: LlmTestRequest, response: Response) -> LlmTestResponse:
    """发送最小连接测试 Prompt，返回当前 Provider 的真实回复。"""
    try:
        provider = get_llm_provider()
    except LLMError as exc:
        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        return LlmTestResponse(
            success=False,
            provider=config.LLM_PROVIDER,
            model=config.MIMO_MODEL,
            error=error_message,
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.prompt},
    ]
    try:
        content = provider.generate(messages, temperature=0.0)
    except LLMError as exc:
        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        return LlmTestResponse(
            success=False,
            provider=provider.name,
            model=provider.model,
            error=error_message,
        )
    except Exception:
        # 未知异常：固定文案，不泄漏 traceback / 路径 / Secret
        response.status_code = 503
        return LlmTestResponse(
            success=False,
            provider=provider.name,
            model=provider.model,
            error="Mimo request failed",
        )

    return LlmTestResponse(
        success=True,
        provider=provider.name,
        model=provider.model,
        content=content,
    )