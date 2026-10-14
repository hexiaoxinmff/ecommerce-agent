"""查询历史 API 相关 Pydantic 模型（Task37-5 / P4）。

响应刻意不包含：
- user_id：内部隔离字段，前端场景无需要（当前登录用户只看自己的历史）；
- session_id：内部认证引用，暴露无收益且有探测风险；
- password_hash / token_hash：任何情况下禁止外露。
"""

from pydantic import BaseModel, Field


class HistoryItem(BaseModel):
    """单条查询历史（GET /api/history 列表项）。"""

    id: int
    question: str
    sql: str = ""
    success: bool
    error_message: str = ""
    result_summary: str = ""
    row_count: int | None = None
    total_time_ms: float | None = None
    created_at: str


class HistoryListResponse(BaseModel):
    """GET /api/history 响应体（created_at 倒序 + 分页）。"""

    items: list[HistoryItem]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total: int = Field(..., ge=0)
