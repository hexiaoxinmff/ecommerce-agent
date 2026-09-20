"""Schema Linking 路由。

POST /api/schema/link
- 用户问题 -> SchemaLinker -> LLMProvider（Mimo）-> 真实 Schema 复核 -> 结构化结果；
- 不生成 SQL、不执行 SQL。

错误状态码约定：
- 请求参数校验失败（question 空/超长）：422（FastAPI 自动）；
- LLM 输出非法（JSON 解析失败 / 表字段不存在 / confidence 越界）：502；
- LLM/Provider 调用失败：与 /api/llm/test 一致的状态码映射
  （401/403 -> 502，其余 -> 503 等）；
- 未预期异常：500（固定文案，不回显 traceback / 路径 / Secret）。
"""

from fastapi import APIRouter, Response

from app.api.routes.llm import _map_failure
from app.llm.provider import LLMError
from app.schema.linker import SchemaLinker
from app.schema.validation import SchemaLinkingInvalidError
from app.schemas.schema_link import SchemaLinkRequest, SchemaLinkResponse

router = APIRouter(tags=["schema"])


@router.post(
    "/schema/link",
    response_model=SchemaLinkResponse,
    summary="Schema Linking（识别问题相关表与字段）",
)
def schema_link(
    request: SchemaLinkRequest, response: Response
) -> SchemaLinkResponse:
    """返回用户问题相关的表、字段、理由与置信度（经真实 Schema 复核）。"""
    try:
        result = SchemaLinker().link(request.question)
    except SchemaLinkingInvalidError as exc:
        response.status_code = 502
        return SchemaLinkResponse(success=False, error=f"Schema linking failed: {exc}")
    except LLMError as exc:
        status_code, error_message = _map_failure(exc)
        response.status_code = status_code
        return SchemaLinkResponse(success=False, error=error_message)
    except Exception:
        response.status_code = 500
        return SchemaLinkResponse(success=False, error="Schema linking internal error")

    return SchemaLinkResponse(success=True, result=result)