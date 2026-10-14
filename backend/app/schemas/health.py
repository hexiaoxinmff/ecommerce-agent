"""健康检查相关 Pydantic 模型。"""

from typing import Literal

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    """数据库健康状态。"""

    status: Literal["ok", "error"]
    type: Literal["sqlite"]
    name: str


class LlmRuntimeInfo(BaseModel):
    """当前实际配置的 LLM Provider / Model（只读展示，非探活）。

    供前端 Header 的 Runtime LLM 徽标动态显示，杜绝硬编码模型名。
    字段为 None 表示「无法安全判定」（如 Provider 配置非法），
    前端必须显示中性占位，不允许伪造。
    """

    provider: str | None = None
    model: str | None = None


class HealthResponse(BaseModel):
    """GET /api/health 响应结构。

    llm 为可选字段且默认 None：不改变既有消费方的任何行为，
    仅新增只读的运行时 Provider/Model 展示信息（不发起 LLM 调用）。
    """

    status: Literal["ok", "degraded"]
    service: str
    database: DatabaseHealth
    llm: LlmRuntimeInfo | None = None