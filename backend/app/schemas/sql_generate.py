"""SQL Generation 接口相关 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


class SQLGenerationRequest(BaseModel):
    """POST /api/sql/generate 请求体。"""

    question: str = Field(..., min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question 不能为空")
        return value


class SQLGenerationResult(BaseModel):
    """SQL 生成结果。"""

    question: str  # 必须保留用户原始问题
    sql: str
    tables: list[str]
    columns: list[str]
    fewshot_examples: list[str]
    explanation: str


class SQLGenerationResponse(BaseModel):
    """POST /api/sql/generate 响应体。"""

    success: bool
    result: SQLGenerationResult | None = None
    error: str = ""