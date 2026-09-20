"""LangGraph Agent 编排路由。

POST /api/agent/analyze
Question -> [SchemaLinking -> Few-shot -> SQL Generation -> Safety -> Execute
            (-> Repair(≤1) -> Safety -> Execute)] -> Result + Trace

编排不新增业务能力，全部复用已验收模块。有界：repair_count ≤ 1、execute_count ≤ 2。
响应内含结构化 Trace（success/error/skipped 各节点事件）与 total_time_ms。

Provider/LLM 错误映射为终态（Trace 保留 schema_link=error）并给出 HTTP 状态：
认证 502，其余 503；参数 422；未预期异常 500 固定文案。
"""

from fastapi import APIRouter, Response

from app.agent.graph import build_agent, run_agent
from app.agent.models import AgentRequest, AgentResponse
from app.llm.provider import LLMError

router = APIRouter(tags=["agent"])


@router.post(
    "/agent/analyze",
    response_model=AgentResponse,
    summary="Text2SQL Agent 编排分析（LangGraph，≤1 次修复，含 Trace）",
)
def agent_analyze(
    request: AgentRequest, response: Response
) -> AgentResponse:
    try:
        result = run_agent(request.question)
    except LLMError as exc:
        # 兼容兜底：provider 错误映射保持既有语义
        from app.api.routes.llm import _map_failure

        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        return AgentResponse(success=False, error=error_message)
    except Exception:
        response.status_code = 500
        return AgentResponse(success=False, error="Agent analysis internal error")

    if result.http_status is not None:
        response.status_code = result.http_status
        return AgentResponse(
            success=False,
            error=result.final_error or "Agent analysis failed",
        )

    return AgentResponse(success=result.success, result=result)