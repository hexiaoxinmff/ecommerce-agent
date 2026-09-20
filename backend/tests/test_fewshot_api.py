"""POST /api/fewshot/retrieve API 测试（纯本地检索，不调用 Mimo）。

覆盖：正常请求结构、空/空白 question、top_k 非法（0/超范围）、
columns 格式非法、tables 类型非法、数据集异常、返回结构正确。
"""

import pytest
from fastapi.testclient import TestClient

from app.fewshot import retriever as retriever_module
from app.fewshot.dataset import FewShotDatasetNotFoundError

VALID_BODY = {
    "question": "近30天销售额最高的商品有哪些？",
    "tables": ["orders", "order_items", "products"],
    "columns": [
        "orders.order_date",
        "orders.status",
        "order_items.product_id",
        "order_items.subtotal",
        "products.id",
        "products.name",
    ],
    "scenario": "product_sales_ranking",
    "top_k": 3,
}


def test_fewshot_retrieve_ok(client: TestClient) -> None:
    response = client.post("/api/fewshot/retrieve", json=VALID_BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["error"] == ""
    result = data["result"]
    assert result["question"] == VALID_BODY["question"]
    assert len(result["matches"]) == 3
    scores = [m["score"] for m in result["matches"]]
    assert scores == sorted(scores, reverse=True)
    # 命中的 example 都来自真实数据集（ex_* 前缀）
    for match in result["matches"]:
        assert match["example_id"].startswith("ex_")
        assert "sql" in match and match["sql"]
        assert 0.0 <= match["score"] <= 1.0


def test_top_match_is_ex_001(client: TestClient) -> None:
    response = client.post("/api/fewshot/retrieve", json=VALID_BODY)
    assert response.json()["result"]["matches"][0]["example_id"] == "ex_001"


def test_empty_question_rejected(client: TestClient) -> None:
    assert (
        client.post("/api/fewshot/retrieve", json={"question": ""}).status_code == 422
    )


def test_blank_question_rejected(client: TestClient) -> None:
    assert (
        client.post("/api/fewshot/retrieve", json={"question": "   "}).status_code == 422
    )


def test_top_k_zero_rejected(client: TestClient) -> None:
    body = dict(VALID_BODY, top_k=0)
    assert client.post("/api/fewshot/retrieve", json=body).status_code == 422


def test_top_k_too_large_rejected(client: TestClient) -> None:
    body = dict(VALID_BODY, top_k=1000)
    assert client.post("/api/fewshot/retrieve", json=body).status_code == 422


def test_top_k_51_rejected(client: TestClient) -> None:
    body = dict(VALID_BODY, top_k=51)
    assert client.post("/api/fewshot/retrieve", json=body).status_code == 422


def test_top_k_one_returns_single_match(client: TestClient) -> None:
    body = dict(VALID_BODY, top_k=1)
    response = client.post("/api/fewshot/retrieve", json=body)
    assert response.status_code == 200
    assert len(response.json()["result"]["matches"]) == 1


def test_illegal_column_format_rejected(client: TestClient) -> None:
    body = dict(VALID_BODY, columns=["orders.order_date", "total_amount"])
    assert client.post("/api/fewshot/retrieve", json=body).status_code == 422


def test_illegal_tables_type_rejected(client: TestClient) -> None:
    body = dict(VALID_BODY, tables=["orders", 123])
    assert client.post("/api/fewshot/retrieve", json=body).status_code == 422


def test_dataset_error_returns_500(client: TestClient, monkeypatch) -> None:
    def boom():
        raise FewShotDatasetNotFoundError("Few-shot 数据集不存在: /no/such.json")

    monkeypatch.setattr(retriever_module, "get_dataset", boom)
    response = client.post("/api/fewshot/retrieve", json=VALID_BODY)
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert "dataset" in data["error"].lower()


def test_schema_link_and_fewshot_column_style_consistent(client: TestClient) -> None:
    """Few-shot 检索的 columns 与 Schema Linking 使用一致的「表.字段」风格，无异常。"""
    response = client.post(
        "/api/fewshot/retrieve",
        json={
            "question": "哪个地区的用户最多？",
            "tables": ["users"],
            "columns": ["users.region"],
        },
    )
    assert response.status_code == 200
    # ex_002 已于 Task 14.3 因泄漏移除；此处仅验证检索正常返回（column 风格无异常）
    assert response.json()["result"]["matches"]