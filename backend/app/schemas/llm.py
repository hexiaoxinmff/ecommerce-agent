"""LLM 连接测试接口相关 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


class LlmTestRequest(BaseModel):
    """POST /api/llm/test 请求体。

    只接受 prompt；api_key / model / base_url / provider / timeout 等字段
    一律由服务端配置决定，客户端传入会被 Pydantic 忽略。
    """

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="测试提示词，1~2000 字符",
    )

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt 不能为空")
        return value


class LlmTestResponse(BaseModel):
    """POST /api/llm/test 响应体。"""

    success: bool
    provider: str
    model: str
    content: str = ""
    error: str = ""