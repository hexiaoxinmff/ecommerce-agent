"""健康检查路由。

GET /api/health
- 数据库可只读访问：HTTP 200，status = "ok"；
- 数据库不可用：HTTP 503，status = "degraded"（仅在响应体中体现，
  客户端应以响应体 status 字段为准）；
- llm：当前实际配置的 Provider / Model（只读展示）。来源是
  get_llm_provider() 的真实解析结果（与 Agent 运行同一入口），
  绝不发起任何 LLM 网络调用；解析失败（配置非法等）时为 null，
  由前端显示中性占位，不伪造。
"""

from pathlib import Path

from fastapi import APIRouter, Response, status

from app.core import config
from app.db.sqlite import is_database_readable
from app.llm.provider import get_llm_provider
from app.schemas.health import DatabaseHealth, HealthResponse, LlmRuntimeInfo

router = APIRouter(tags=["health"])


def _llm_runtime_info() -> LlmRuntimeInfo | None:
    """解析当前实际配置的 Provider/Model；无法安全判定时返回 None。

    get_llm_provider() 是全系统唯一的 Provider 分派入口（Agent 运行
    走的同一函数），因此这里读到的就是「实际运行配置」。构造 Provider
    实例只读环境配置，不产生任何网络请求；任何异常（如备用模型池
    配置非法）都收敛为 None，绝不影响健康检查本身的可用性。
    """
    try:
        provider = get_llm_provider()
    except Exception:  # noqa: BLE001 — 展示信息失败不得影响健康检查
        return None
    model = (provider.model or "").strip() or None
    provider_name = (provider.name or "").strip() or None
    if provider_name is None:
        return None
    return LlmRuntimeInfo(provider=provider_name, model=model)


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
        llm=_llm_runtime_info(),
    )