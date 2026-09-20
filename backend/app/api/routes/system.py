"""系统信息路由。

GET /api/system/database
仅用于验证 SQLite 只读连接真实打通：返回数据库名称与各表行数。
内部只执行固定 SQL，不接收、不执行任何用户提交的 SQL。
"""

from fastapi import APIRouter, HTTPException

from app.db.sqlite import DatabaseError, get_database_info
from app.schemas.system import DatabaseInfo

router = APIRouter(tags=["system"])


@router.get("/database", response_model=DatabaseInfo, summary="数据库信息（只读验证）")
def database_info() -> DatabaseInfo:
    """返回数据库名称与 5 张业务表真实行数。"""
    try:
        info = get_database_info()
    except DatabaseError as exc:
        raise HTTPException(
            status_code=503,
            detail="数据库不可用，请确认 db/ecommerce.db 存在且可读。",
        ) from exc
    return DatabaseInfo(**info)