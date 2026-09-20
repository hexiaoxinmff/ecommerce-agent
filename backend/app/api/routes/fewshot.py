"""Few-shot 检索路由。

POST /api/fewshot/retrieve
- 纯本地规则型检索：API -> FewShotRetriever -> FewShotDataset，
  不依赖 Mimo / OpenAI SDK；
- 返回按 (score 降序, example_id 升序) 排序的 Top-K 参考示例；
- score 是检索相似度，不是 SQL 正确性。

错误状态码约定：
- 参数校验失败（question 空 / top_k 越界 / columns 格式非法）：422；
- 数据集加载失败（文件缺失 / JSON 非法 / 表字段不存在等）：500；
- 未预期异常：500（固定文案，不回显 traceback）。
"""

from fastapi import APIRouter, Response

from app.fewshot.dataset import FewShotDatasetError
from app.fewshot.models import FewShotResult, FewShotQuery
from app.fewshot.retriever import FewShotRetriever
from app.schemas.fewshot import FewShotRetrieveRequest, FewShotRetrieveResponse

router = APIRouter(tags=["fewshot"])


@router.post(
    "/fewshot/retrieve",
    response_model=FewShotRetrieveResponse,
    summary="Few-shot 示例检索（规则型，Top-K）",
)
def fewshot_retrieve(
    request: FewShotRetrieveRequest, response: Response
) -> FewShotRetrieveResponse:
    try:
        query = FewShotQuery(**request.model_dump())
        result: FewShotResult = FewShotRetriever().retrieve(query)
    except FewShotDatasetError as exc:
        response.status_code = 500
        return FewShotRetrieveResponse(success=False, error=f"Few-shot dataset error: {exc}")
    except ValueError as exc:
        response.status_code = 422
        return FewShotRetrieveResponse(success=False, error=str(exc))
    except Exception:
        response.status_code = 500
        return FewShotRetrieveResponse(success=False, error="Few-shot retrieval internal error")

    return FewShotRetrieveResponse(success=True, result=result)