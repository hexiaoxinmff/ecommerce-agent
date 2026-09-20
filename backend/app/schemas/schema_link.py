"""Schema Linking 接口相关 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


class SchemaLinkRequest(BaseModel):
    """POST /api/schema/link 请求体。"""

    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="用户自然语言问题，1~500 字符",
    )

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question 不能为空")
        return value


class SchemaLinkResult(BaseModel):
    """Schema Linking 结果：用户问题 -> 相关表/字段/理由/置信度。"""

    question: str
    tables: list[str]
    columns: list[str]  # 一律使用「表名.字段名」格式
    reasons: list[str]
    confidence: float = Field(..., ge=0.0, le=1.0)


class SchemaLinkResponse(BaseModel):
    """POST /api/schema/link 响应体。"""

    success: bool
    result: SchemaLinkResult | None = None
    error: str = ""