"""Few-shot 检索接口相关 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator

from app.fewshot.models import FewShotResult


class FewShotRetrieveRequest(BaseModel):
    """POST /api/fewshot/retrieve 请求体。"""

    question: str = Field(..., min_length=1, max_length=500)
    tables: list[str] = []
    columns: list[str] = []
    scenario: str | None = None
    top_k: int = Field(default=3, ge=1, le=50)  # top_k=0 / 超大值 -> 422 明确处理

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question 不能为空")
        return value

    @field_validator("columns")
    @classmethod
    def columns_use_table_dot_column(cls, value: list[str]) -> list[str]:
        for column in value:
            if not isinstance(column, str) or "." not in column:
                raise ValueError(f"columns 必须使用「表名.字段名」格式: {column}")
        return value


class FewShotRetrieveResponse(BaseModel):
    """POST /api/fewshot/retrieve 响应体。"""

    success: bool
    result: FewShotResult | None = None
    error: str = ""