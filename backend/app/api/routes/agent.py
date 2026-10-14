"""LangGraph Agent 编排路由。

POST /api/agent/analyze
Question -> [SchemaLinking -> Few-shot -> SQL Generation -> Safety -> Execute
            (-> Repair(≤1) -> Safety -> Execute)] -> Result + Trace

编排不新增业务能力，全部复用已验收模块。有界：repair_count ≤ 1、execute_count ≤ 2。
响应内含结构化 Trace（success/error/skipped 各节点事件）与 total_time_ms。

Provider/LLM 错误映射为终态（Trace 保留 schema_link=error）并给出 HTTP 状态：
认证 502，其余 503；参数 422；未预期异常 500 固定文案。

P4 接入认证与历史落库：
- 必须 Bearer 认证（Depends(get_current_session)，复用 P3 依赖，不重复解析）；
- 每次请求（成功或任一步失败）尽力写入一条 query_history（user_id 来自服务端
  登录态）；落库失败只记 warning 日志（仅异常类型），绝不改变已产生的 Agent
  响应/状态码；
- 写入的 error_message 复用对外响应文案（本就客户端安全），不含 traceback /
  API key / token / 密码。
"""

import logging
import re

from fastapi import APIRouter, Depends, Response

from app.agent.graph import build_agent, run_agent
from app.agent.models import AgentRequest, AgentResponse
from app.auth.dependencies import get_current_session
from app.db import appdb
from app.llm.provider import LLMError

router = APIRouter(tags=["agent"])

# 历史落库失败仅记日志（异常类型，不含任何业务/凭据内容）
logger = logging.getLogger("app.agent.history")

# error_message 入库前的脱敏：常见凭据形态统一打码（响应体语义不变）
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(token|password|passwd|secret|api[_-]?key)\s*[=:]\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)bearer\s+\S+"), "Bearer ***"),
    (re.compile(r"sk-[A-Za-z0-9]+"), "sk-***"),
    (re.compile(r"eyJ[A-Za-z0-9._-]+"), "***"),
)


def _scrub(text: str) -> str:
    """对即将入库的错误信息做凭据形态脱敏。"""
    if not text:
        return ""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _final_sql(result) -> str:
    """最终实际执行的 SQL：发生 repair 时为 repaired_sql，否则 generated_sql。"""
    return result.repaired_sql or result.generated_sql or ""


def _result_summary(result) -> str:
    """由既有 execution_result 字段拼装轻量摘要（不引入新摘要体系）。"""
    execution = result.execution_result
    if execution is None:
        return ""
    columns = ", ".join(execution.columns[:5])
    suffix = "…（已截断）" if execution.truncated else ""
    return f"{execution.row_count} 行 · 列: {columns}{suffix}"


def _persist_history_safe(session_and_user, question: str, *, sql: str, success: bool,
                          error_message: str = "", result_summary: str = "",
                          row_count: int | None = None,
                          total_time_ms: float | None = None) -> None:
    """尽力写入查询历史；失败只记日志，绝不影响已产生的 Agent 结果。"""
    try:
        session, user = session_and_user
        appdb.create_query_history(
            user["id"],
            question,
            session_id=session["id"],
            sql=sql,
            success=success,
            error_message=_scrub(error_message),
            result_summary=_scrub(result_summary),
            row_count=row_count,
            total_time_ms=total_time_ms,
        )
    except Exception as exc:  # noqa: BLE001 — 落库失败不得阻断主请求
        logger.warning("query history persistence failed: %s", type(exc).__name__)


@router.post(
    "/agent/analyze",
    response_model=AgentResponse,
    summary="Text2SQL Agent 编排分析（LangGraph，≤1 次修复，含 Trace，需登录）",
)
def agent_analyze(
    request: AgentRequest,
    response: Response,
    session_and_user=Depends(get_current_session),
) -> AgentResponse:
    try:
        result = run_agent(request.question)
    except LLMError as exc:
        # 兼容兜底：provider 错误映射保持既有语义
        from app.api.routes.llm import _map_failure

        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        _persist_history_safe(
            session_and_user,
            request.question,
            sql="",
            success=False,
            error_message=error_message,
        )
        return AgentResponse(success=False, error=error_message)
    except Exception:
        response.status_code = 500
        _persist_history_safe(
            session_and_user,
            request.question,
            sql="",
            success=False,
            error_message="Agent analysis internal error",
        )
        return AgentResponse(success=False, error="Agent analysis internal error")

    # 结果路径（成功与 Agent 终态失败都落库）
    _persist_history_safe(
        session_and_user,
        request.question,
        sql=_final_sql(result),
        success=bool(result.success),
        error_message=result.final_error,
        result_summary=_result_summary(result),
        row_count=result.execution_result.row_count if result.execution_result else None,
        total_time_ms=result.total_time_ms,
    )

    # 数据时效契约（Phase 15 · P0-1 最小版）：结果附带数据截止日，
    # 供前端展示「数据截至」，使相对时间口径可验证；失败不阻断响应。
    data_as_of = ""
    try:
        from app.dbprofile.time_anchor import default_time_contract

        contract = default_time_contract()
        data_as_of = contract.data_as_of if contract else ""
    except Exception:  # noqa: BLE001 — as_of 属增强信息，绝不影响主响应
        data_as_of = ""

    if result.http_status is not None:
        response.status_code = result.http_status
        return AgentResponse(
            success=False,
            error=result.final_error or "Agent analysis failed",
            data_as_of=data_as_of,
        )

    return AgentResponse(success=result.success, result=result, data_as_of=data_as_of)
