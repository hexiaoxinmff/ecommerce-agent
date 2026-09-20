"""SQL Repair 路由。

- POST /api/sql/repair：Repair 能力单独测试（不执行 Repair SQL）；
- POST /api/sql/execute-with-repair：有限 Repair 闭环
  （Safety -> Execute -> 失败 -> Repair(一次) -> Safety/Schema -> Execute(一次)），
  最多 1 次 Repair / 2 次执行，绝不循环。

/api/sql/execute 保持纯 Executor 语义，本模块不改动它。

错误状态码约定（与项目既有约定统一）：
- 参数校验失败：422；
- Safety 校验拒绝（含 Repair Safety Rejected）：422；
- Repair LLM 输出非法 / Schema 越界：502；
- LLM Provider 认证失败：502，其余 Provider 错误：503；
- 闭环最终失败（Repair 后仍失败）：422（success=false + 完整诊断）；
- 未预期异常：500（固定文案，不回显 traceback / 路径 / Secret）。
"""

from fastapi import APIRouter, Response

from app.api.routes.llm import _map_failure
from app.llm.provider import LLMError
from app.sqlrepair.errors import (
    SQLRepairError,
    SQLRepairOutputInvalidError,
    SQLRepairSafetyError,
    SQLRepairSchemaError,
)
from app.sqlrepair.models import (
    SQLExecuteWithRepairRequest,
    SQLExecuteWithRepairResponse,
    SQLRepairRequest,
    SQLRepairResponse,
)
from app.sqlrepair.repairer import SQLExecuteWithRepairOrchestrator, SQLRepairer

router = APIRouter(tags=["sql"])


@router.post(
    "/sql/repair",
    response_model=SQLRepairResponse,
    summary="SQL 修复（单独测试 Repair 能力，不执行 Repair SQL）",
)
def sql_repair(
    request: SQLRepairRequest, response: Response
) -> SQLRepairResponse:
    try:
        result = SQLRepairer().repair(request)
    except SQLRepairSafetyError as exc:
        response.status_code = 422
        return SQLRepairResponse(success=False, error=f"Repair Safety Rejected: {exc}")
    except (SQLRepairOutputInvalidError, SQLRepairSchemaError) as exc:
        response.status_code = 502
        return SQLRepairResponse(success=False, error=f"SQL repair failed: {exc}")
    except SQLRepairError as exc:
        response.status_code = 502
        return SQLRepairResponse(success=False, error=f"SQL repair failed: {exc}")
    except LLMError as exc:
        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        return SQLRepairResponse(success=False, error=error_message)
    except Exception:
        response.status_code = 500
        return SQLRepairResponse(success=False, error="SQL repair internal error")

    return SQLRepairResponse(success=True, result=result)


@router.post(
    "/sql/execute-with-repair",
    response_model=SQLExecuteWithRepairResponse,
    summary="SQL 执行（有限 Repair 闭环：最多 1 次修复 / 2 次执行）",
)
def sql_execute_with_repair(
    request: SQLExecuteWithRepairRequest, response: Response
) -> SQLExecuteWithRepairResponse:
    try:
        outcome = SQLExecuteWithRepairOrchestrator().run(
            question=request.question,
            sql=request.sql,
            tables=request.tables,
            columns=request.columns,
        )
    except Exception:
        response.status_code = 500
        return SQLExecuteWithRepairResponse(
            success=False, error="Execute-with-repair internal error"
        )

    if outcome.result is not None:
        return SQLExecuteWithRepairResponse(success=True, result=outcome)

    response.status_code = 422
    return SQLExecuteWithRepairResponse(
        success=False,
        result=outcome,
        error=outcome.repair_error or outcome.original_error,
    )