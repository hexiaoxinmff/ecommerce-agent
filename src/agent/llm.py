"""LLM 客户端：封装 qwen / deepseek / doubao(豆包) / xiaomi(小米) 等 OpenAI 兼容模型。"""
from config import settings
from langchain_openai import ChatOpenAI


def get_llm(temperature: float = 0.3, timeout: float = 60.0):
    """根据 settings.LLM_PROVIDER 返回对应的 ChatOpenAI 实例。

    所有 provider 均走 OpenAI 兼容协议，仅 base_url / model / api_key 不同。
    timeout 防止单次调用长时间挂起（评测 / 重排等批量场景尤为重要）。
    """
    return ChatOpenAI(
        model=settings.LLM_CHAT_MODEL,
        api_key=settings.API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=temperature,
        request_timeout=timeout,
    )
