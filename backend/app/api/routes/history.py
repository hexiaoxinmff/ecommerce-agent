"""查询历史路由（Task37-5 / P4）。

- GET    /api/history             当前用户自己的历史（created_at 倒序 + 分页）
- DELETE /api/history/{history_id} 删除本人一条历史（204；不属于本人或不存在 → 404）

安全：
- 所有读写强制 user_id = 当前登录用户（服务端依赖取得，绝不信任前端参数）；
- DELETE 一律 WHERE user_id = ? AND id = ?（appdb.delete_query_history 保证）；
- 跨用户 / 不存在的 history 统一 404 {"detail": "History not found"}，
  不泄露"该 ID 属于谁"；
- 响应模型不含 user_id / session_id / 任何 hash 字段。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.db import appdb
from app.schemas.history import HistoryItem, HistoryListResponse

router = APIRouter(tags=["history"])

_HISTORY_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="History not found",
)


def _to_item(row) -> HistoryItem:
    """sqlite3.Row -> HistoryItem（Row 不支持属性访问，显式按下标构造）。"""
    return HistoryItem(
        id=row["id"],
        question=row["question"],
        sql=row["sql"],
        success=bool(row["success"]),
        error_message=row["error_message"],
        result_summary=row["result_summary"],
        row_count=row["row_count"],
        total_time_ms=row["total_time_ms"],
        created_at=row["created_at"],
    )


@router.get(
    "/history",
    response_model=HistoryListResponse,
    summary="当前用户的查询历史（created_at 倒序 + 分页）",
)
def list_history(
    user=Depends(get_current_user),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> HistoryListResponse:
    items = appdb.list_query_history(
        user["id"], limit=page_size, offset=(page - 1) * page_size
    )
    return HistoryListResponse(
        items=[_to_item(row) for row in items],
        page=page,
        page_size=page_size,
        total=appdb.count_query_history(user["id"]),
    )


@router.delete(
    "/history/{history_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除本人一条查询历史（不属于本人或不存在 → 404）",
)
def delete_history(history_id: int, user=Depends(get_current_user)) -> None:
    deleted = appdb.delete_query_history(user["id"], history_id)
    if not deleted:
        raise _HISTORY_NOT_FOUND
