"""健康检查相关 Pydantic 模型。"""

from typing import Literal

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    """数据库健康状态。"""

    status: Literal["ok", "error"]
    type: Literal["sqlite"]
    name: str


class HealthResponse(BaseModel):
    """GET /api/health 响应结构。"""

    status: Literal["ok", "degraded"]
    service: str
    database: DatabaseHealth