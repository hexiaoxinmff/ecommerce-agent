"""Agent 编排接口相关 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator

from app.sqlexec.models import SQLExecutionResult
from app.trace.models import TraceEvent


class AgentRequest(BaseModel):
    """POST /api/agent/analyze 请求体。"""

    question: str = Field(..., min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question 不能为空")
        return value


class AgentResult(BaseModel):
    """LangGraph 编排最终输出（保留全部中间证据 + 结构化 Trace）。"""

    question: str
    success: bool
    generated_sql: str = ""
    repaired_sql: str = ""
    execution_result: SQLExecutionResult | None = None
    execution_error: str = ""
    repair_reason: str = ""
    repair_error: str = ""
    execute_count: int
    repair_count: int
    final_error: str = ""
    trace: list[TraceEvent] = Field(default_factory=list)
    total_time_ms: float = 0.0
    http_status: int | None = None
    error_type: str = ""


class AgentResponse(BaseModel):
    """POST /api/agent/analyze 响应体。

    data_as_of（Phase 15 · P0-1 最小版）：业务数据截止日，来自
    Data As-Of 契约的真实查询；前端在结果区展示「数据截至」，使
    相对时间口径可验证。契约不可用时为空串（前端不展示该行）。
    """

    success: bool
    result: AgentResult | None = None
    error: str = ""
    data_as_of: str = ""