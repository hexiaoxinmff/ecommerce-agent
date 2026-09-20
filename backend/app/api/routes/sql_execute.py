"""SQL 执行路由。

POST /api/sql/execute
- 只接收 SQL（不接收自然语言问题）；
- 执行前再次做 SQL Safety Validation（最后一道安全边界）；
- 复用现有 SQLite 只读层，写操作/多语句/PRAGMA 一律拒绝；
- 结果超限不是崩溃：返回 200 + truncated=true。

错误状态码约定：
- 参数校验失败（sql 空/空白/超长）：422；
- 安全校验失败（写操作/多语句/无法解析等）：422；
- 数据库执行异常（语法错误/表不存在等）：500；
- 未预期异常：500（固定文案，不回显 traceback / 路径）。
"""

from fastapi import APIRouter, Response

from app.sqlexec.errors import (
    SQLExecutionDatabaseError,
    SQLExecutionError,
    SQLExecutionSafetyError,
)
from app.sqlexec.executor import execute
from app.sqlexec.models import SQLExecutionRequest, SQLExecutionResponse

router = APIRouter(tags=["sql"])


@router.post(
    "/sql/execute",
    response_model=SQLExecutionResponse,
    summary="SQL 执行（只读 SELECT/WITH，结构化结果）",
)
def sql_execute(
    request: SQLExecutionRequest, response: Response
) -> SQLExecutionResponse:
    try:
        result = execute(request.sql)
    except SQLExecutionSafetyError as exc:
        response.status_code = 422
        return SQLExecutionResponse(success=False, error=f"SQL rejected: {exc}")
    except SQLExecutionDatabaseError as exc:
        response.status_code = 500
        return SQLExecutionResponse(success=False, error=str(exc))
    except SQLExecutionError as exc:
        response.status_code = 500
        return SQLExecutionResponse(success=False, error=str(exc))
    except Exception:
        response.status_code = 500
        return SQLExecutionResponse(success=False, error="SQL execution internal error")

    return SQLExecutionResponse(success=True, result=result)