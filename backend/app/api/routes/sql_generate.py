"""SQL 生成路由。

POST /api/sql/generate
Question -> SchemaLinker -> FewShotRetriever -> SQLGenerator(LLMProvider) -> SQL Validation -> Response。
本阶段只生成与校验 SQL，不执行 SQL，不做失败重试 / SQL Repair。

错误状态码约定：
- 参数校验失败（question 空/超长）：422；
- Few-shot 数据集异常：500；
- Schema Linking 输出非法：502；
- LLM 输出非法 JSON / 非法表字段 / SQL 不安全 / 多语句 / 表引用越界：502；
- LLM/Provider 调用失败：与 /api/llm/test 一致映射（401/403->502，其余->503）；
- 未预期异常：500（固定文案，不回显 traceback / 路径 / Secret）。
"""

from fastapi import APIRouter, Response

from app.api.routes.llm import _map_failure
from app.fewshot.dataset import FewShotDatasetError
from app.llm.provider import LLMError
from app.schema.validation import SchemaLinkingError
from app.schemas.sql_generate import (
    SQLGenerationRequest,
    SQLGenerationResponse,
)
from app.sqlgen.errors import SQLGeneratorError
from app.sqlgen.generator import SQLGenerator

router = APIRouter(tags=["sql"])


@router.post(
    "/sql/generate",
    response_model=SQLGenerationResponse,
    summary="SQL 生成（Text2SQL，只生成不执行）",
)
def sql_generate(
    request: SQLGenerationRequest, response: Response
) -> SQLGenerationResponse:
    try:
        result = SQLGenerator().generate(request.question)
    except FewShotDatasetError as exc:
        response.status_code = 500
        return SQLGenerationResponse(
            success=False, error=f"Few-shot dataset error: {exc}"
        )
    except SchemaLinkingError as exc:
        response.status_code = 502
        return SQLGenerationResponse(success=False, error=f"Schema linking failed: {exc}")
    except SQLGeneratorError as exc:
        response.status_code = 502
        return SQLGenerationResponse(success=False, error=f"SQL generation failed: {exc}")
    except LLMError as exc:
        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        return SQLGenerationResponse(success=False, error=error_message)
    except Exception:
        response.status_code = 500
        return SQLGenerationResponse(success=False, error="SQL generation internal error")

    return SQLGenerationResponse(success=True, result=result)