"""POST /api/schema/link API 测试（全部 mock LLMProvider，不真实调用 Mimo）。

覆盖：
- 正常问题：200，success=true，result 结构完整；
- question 空 / 空白 / 超长：422；
- LLM 输出非法（非 JSON / 非法表）：502；
- Provider 异常：认证错误 502、Key 未配置 503；
- 无关问题：200 且空匹配结果。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
)
from app.schema import linker as linker_module

VALID_JSON = json.dumps(
    {
        "tables": ["orders", "order_items", "products"],
        "columns": [
            "orders.order_date",
            "orders.status",
            "orders.total_amount",
            "order_items.product_id",
            "order_items.subtotal",
            "products.id",
            "products.name",
        ],
        "reasons": ["按 order_date 筛选近30天", "计算销售额并排除 cancelled 订单"],
        "confidence": 0.92,
    },
    ensure_ascii=False,
)


class _FakeProvider:
    name = "mimo"
    model = "mimo-v2.5-pro"

    def __init__(self, output: str = "", error: Exception | None = None) -> None:
        self._output = output
        self._error = error

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        if self._error is not None:
            raise self._error
        return self._output


@pytest.fixture()
def fake_provider(monkeypatch):
    """把 SchemaLinker 默认的 get_llm_provider 替换为模拟 Provider。"""

    def _install(output: str = VALID_JSON, error: Exception | None = None):
        provider = _FakeProvider(output=output, error=error)
        monkeypatch.setattr(linker_module, "get_llm_provider", lambda: provider)
        return provider

    return _install


def test_schema_link_ok(client: TestClient, fake_provider) -> None:
    fake_provider()  # 安装默认 mock Provider
    response = client.post("/api/schema/link", json={"question": "近30天销售额最高的商品有哪些？"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["error"] == ""
    result = data["result"]
    assert result["question"] == "近30天销售额最高的商品有哪些？"
    assert set(result["tables"]) == {"orders", "order_items", "products"}
    assert all("." in c for c in result["columns"])
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["reasons"]


def test_schema_link_out_of_domain(client: TestClient, fake_provider) -> None:
    payload = json.dumps(
        {
            "tables": [],
            "columns": [],
            "reasons": ["与电商数据库无关"],
            "confidence": 0.1,
        },
        ensure_ascii=False,
    )
    fake_provider(output=payload)
    response = client.post("/api/schema/link", json={"question": "今天天气怎么样？"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["result"]["tables"] == []
    assert data["result"]["columns"] == []


def test_blank_question_rejected(client: TestClient) -> None:
    assert (
        client.post("/api/schema/link", json={"question": "   "}).status_code == 422
    )


def test_empty_question_rejected(client: TestClient) -> None:
    assert client.post("/api/schema/link", json={"question": ""}).status_code == 422


def test_too_long_question_rejected(client: TestClient) -> None:
    response = client.post("/api/schema/link", json={"question": "长" * 501})
    assert response.status_code == 422


def test_non_json_output_returns_502(client: TestClient, fake_provider) -> None:
    fake_provider(output="抱歉，无法回答。")
    response = client.post("/api/schema/link", json={"question": "问题"})
    assert response.status_code == 502
    data = response.json()
    assert data["success"] is False
    assert data["result"] is None
    assert "failed" in data["error"]


def test_invalid_table_returns_502(client: TestClient, fake_provider) -> None:
    payload = json.dumps(
        {
            "tables": ["orders", "payments"],
            "columns": ["orders.total_amount"],
            "reasons": ["r"],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
    fake_provider(output=payload)
    response = client.post("/api/schema/link", json={"question": "问题"})
    assert response.status_code == 502
    assert "payments" in response.json()["error"]


def test_provider_auth_error_returns_502(client: TestClient, fake_provider) -> None:
    fake_provider(error=LLMAuthenticationError("auth failed"))
    response = client.post("/api/schema/link", json={"question": "问题"})
    assert response.status_code == 502
    assert response.json()["error"] == "Mimo authentication failed"


def test_provider_key_missing_returns_503(client: TestClient, fake_provider) -> None:
    fake_provider(
        error=LLMApiKeyNotConfiguredError("Mimo API key is not configured")
    )
    response = client.post("/api/schema/link", json={"question": "问题"})
    assert response.status_code == 503
    assert response.json()["error"] == "Mimo API key is not configured"