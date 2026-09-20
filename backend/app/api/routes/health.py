"""健康检查路由。

GET /api/health
- 数据库可只读访问：HTTP 200，status = "ok"；
- 数据库不可用：HTTP 503，status = "degraded"（仅在响应体中体现，
  客户端应以响应体 status 字段为准）。
"""

from pathlib import Path

from fastapi import APIRouter, Response, status

from app.core import config
from app.db.sqlite import is_database_readable
from app.schemas.health import DatabaseHealth, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="服务健康检查")
def health_check(response: Response) -> HealthResponse:
    """检查服务与 SQLite 只读连接状态（真实执行 SELECT 1 探活）。"""
    database_ok = is_database_readable()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        service=config.SERVICE_NAME,
        database=DatabaseHealth(
            status="ok" if database_ok else "error",
            type="sqlite",
            name=Path(config.DB_PATH).name,
        ),
    )