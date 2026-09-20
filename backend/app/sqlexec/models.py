"""SQL Executor 数据结构（Pydantic）。

row_count 语义：**实际返回给调用方的行数**（≤ MAX_RESULT_ROWS）。
truncated=true 表示数据库实际结果超过上限被截断，row_count 不会为了
精确总数而二次执行 SQL。
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SQLExecutionRequest(BaseModel):
    """POST /api/sql/execute 请求体（只接收 SQL，不接收自然语言问题）。"""

    sql: str = Field(..., min_length=1, max_length=10000)

    @field_validator("sql")
    @classmethod
    def reject_blank_sql(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sql 不能为空")
        return value


class SQLExecutionResult(BaseModel):
    """SQL 执行结果。"""

    columns: list[str]
    rows: list[list[Any]]  # None 保持 null；不做任何格式化
    row_count: int  # 实际返回行数
    truncated: bool  # 数据库实际结果是否超过上限被截断
    execution_time_ms: float


class SQLExecutionResponse(BaseModel):
    """POST /api/sql/execute 响应体。"""

    success: bool
    result: SQLExecutionResult | None = None
    error: str = ""