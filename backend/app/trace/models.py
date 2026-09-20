"""TraceEvent 数据结构（Pydantic）。

约束：sequence >= 1、duration_ms >= 0、node 非空、
status 仅允许 success / error / skipped。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

TraceStatus = Literal["success", "error", "skipped"]


class TraceEvent(BaseModel):
    """一次节点执行轨迹。

    input_summary / output_summary 只保存轻量摘要，禁止塞入完整 State、
    完整 SQL、查询结果全集或任何敏感数据。
    """

    sequence: int = Field(..., ge=1, description="全局序号，严格递增")
    node: str = Field(..., min_length=1)
    status: TraceStatus
    duration_ms: float = Field(..., ge=0)
    message: str = ""
    input_summary: dict[str, Any] = {}
    output_summary: dict[str, Any] = {}