"""Few-shot Retriever 单元测试（不依赖 Mimo）。

覆盖：三类代表性问题的 Top 命中、score 降序与稳定排序、
top_k=1/3/5、top_k=0 报错、top_k 超大数据集裁剪、
返回的 example 都存在于数据集、score 范围 0~1。
"""

import pytest

from app.fewshot.dataset import get_dataset
from app.fewshot.models import FewShotQuery
from app.fewshot.retriever import FewShotRetriever, score_example
from app.schema.metadata import SchemaCatalog

PRODUCT_SALES_SCHEMA = {
    "tables": ["orders", "order_items", "products"],
    "columns": [
        "orders.order_date",
        "orders.status",
        "order_items.product_id",
        "order_items.subtotal",
        "products.id",
        "products.name",
    ],
}
USER_REGION_SCHEMA = {"tables": ["users"], "columns": ["users.region"]}
CATEGORY_SALES_SCHEMA = {
    "tables": ["orders", "order_items", "products", "categories"],
    "columns": [
        "orders.status",
        "order_items.subtotal",
        "products.category_id",
        "categories.id",
        "categories.name",
    ],
}


@pytest.fixture(scope="module")
def retriever() -> FewShotRetriever:
    return FewShotRetriever(dataset=get_dataset())


def test_top_match_product_sales_ranking(retriever: FewShotRetriever) -> None:
    result = retriever.retrieve(
        FewShotQuery(
            question="近30天销售额最高的商品有哪些？",
            **PRODUCT_SALES_SCHEMA,
        )
    )
    assert result.matches
    assert result.matches[0].example_id == "ex_001"


def test_top_match_user_region_distribution(retriever: FewShotRetriever) -> None:
    result = retriever.retrieve(
        FewShotQuery(question="哪个地区的用户最多？", **USER_REGION_SCHEMA)
    )
    # ex_002 已于 Task 14.3 因泄漏移除；示例集可变，仅断言匹配非空且属于 users 维度
    assert result.matches
    assert "users" in result.matches[0].tables


def test_top_match_category_sales_ranking(retriever: FewShotRetriever) -> None:
    result = retriever.retrieve(
        FewShotQuery(question="哪个商品类别销售额最高？", **CATEGORY_SALES_SCHEMA)
    )
    assert result.matches[0].example_id == "ex_003"


def test_scores_sorted_desc_and_stable(retriever: FewShotRetriever) -> None:
    result = retriever.retrieve(
        FewShotQuery(question="近30天销售额最高的商品有哪些？", **PRODUCT_SALES_SCHEMA, top_k=10)
    )
    scores = [m.score for m in result.matches]
    ids = [m.example_id for m in result.matches]
    assert scores == sorted(scores, reverse=True)  # score 降序
    # 同分时按 example_id 稳定排序
    for i in range(len(ids) - 1):
        if scores[i] == scores[i + 1]:
            assert ids[i] < ids[i + 1]


def test_scores_within_0_1(retriever: FewShotRetriever) -> None:
    for ex in get_dataset():
        score = score_example(
            FewShotQuery(question="近30天销售额最高的商品有哪些？", **PRODUCT_SALES_SCHEMA),
            ex,
        )
        assert 0.0 <= score <= 1.0


@pytest.mark.parametrize("k", [1, 3, 5])
def test_top_k_works(retriever: FewShotRetriever, k: int) -> None:
    result = retriever.retrieve(
        FewShotQuery(question="哪个商品类别销售额最高？", **CATEGORY_SALES_SCHEMA, top_k=k)
    )
    assert len(result.matches) == k


def test_top_k_zero_raises(retriever: FewShotRetriever) -> None:
    with pytest.raises(ValueError):
        retriever.retrieve(FewShotQuery(question="问题", top_k=0))


def test_top_k_huge_clamped_to_dataset(retriever: FewShotRetriever) -> None:
    result = retriever.retrieve(
        FewShotQuery(question="哪个地区的用户最多？", **USER_REGION_SCHEMA, top_k=1000)
    )
    assert len(result.matches) == len(get_dataset())


def test_matches_only_from_dataset(retriever: FewShotRetriever) -> None:
    known_ids = {ex.id for ex in get_dataset()}
    result = retriever.retrieve(
        FewShotQuery(question="近30天销售额最高的商品有哪些？", **PRODUCT_SALES_SCHEMA, top_k=10)
    )
    for match in result.matches:
        assert match.example_id in known_ids


def test_score_higher_for_same_schema_than_unrelated(retriever: FewShotRetriever) -> None:
    """相同 tables/columns 的 example 得分不低于完全不相关 example。"""
    query = FewShotQuery(question="近30天销售额最高的商品有哪些？", **PRODUCT_SALES_SCHEMA)
    example_map = {ex.id: ex for ex in get_dataset()}
    same_schema_score = score_example(query, example_map["ex_001"])
    unrelated_score = score_example(query, example_map["ex_014"])  # 订单状态占比，最不相关
    assert same_schema_score >= unrelated_score


def test_retriever_answer_question_preserved(retriever: FewShotRetriever) -> None:
    result = retriever.retrieve(
        FewShotQuery(question="哪个商品类别销售额最高？", **CATEGORY_SALES_SCHEMA)
    )
    assert result.question == "哪个商品类别销售额最高？"