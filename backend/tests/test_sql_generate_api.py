"""POST /api/sql/generate API 测试（mock SQLGenerator，不调用 Mimo）。

覆盖：正常请求、question 空、SQL 不安全 502、非法表 502、非法 JSON 502、
Schema Linking 失败 502、Few-shot 数据集异常 500、Provider 认证 502、
Key 未配置 503、未预期异常 500。
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routes import sql_generate as route_module
from app.fewshot.dataset import FewShotDatasetNotFoundError
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
)
from app.schema.validation import SchemaLinkingInvalidError
from app.sqlgen.errors import (
    SQLGenOutputInvalidError,
    SQLGenSchemaMismatchError,
    SQLTableMismatchError,
    SQLUnsafeError,
)
from app.schemas.sql_generate import SQLGenerationResult


def _ok_result() -> SQLGenerationResult:
    return SQLGenerationResult(
        question="近30天销售额最高的商品有哪些？",
        sql="SELECT 1",
        tables=["orders"],
        columns=["orders.total_amount"],
        fewshot_examples=["ex_001", "ex_006", "ex_003"],
        explanation="按商品汇总销售额",
    )


class _FakeGenerator:
    def __init__(self, error: Exception | None = None, result=None):
        self._error = error
        self._result = result

    def generate(self, question: str):
        if self._error is not None:
            raise self._error
        return self._result or _ok_result()


@pytest.fixture()
def fake_generator(monkeypatch):
    def _install(error: Exception | None = None, result=None):
        fake = _FakeGenerator(error=error, result=result)
        monkeypatch.setattr(route_module, "SQLGenerator", lambda: fake)
        return fake

    return _install


def test_sql_generate_ok(client: TestClient, fake_generator) -> None:
    fake_generator()
    response = client.post("/api/sql/generate", json={"question": "近30天销售额最高的商品有哪些？"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["error"] == ""
    result = data["result"]
    assert result["question"] == "近30天销售额最高的商品有哪些？"
    assert result["sql"].strip() != ""
    assert result["fewshot_examples"] == ["ex_001", "ex_006", "ex_003"]


def test_empty_question_rejected(client: TestClient) -> None:
    assert client.post("/api/sql/generate", json={"question": ""}).status_code == 422


def test_blank_question_rejected(client: TestClient) -> None:
    assert client.post("/api/sql/generate", json={"question": "   "}).status_code == 422


def test_unsafe_sql_returns_502(client: TestClient, fake_generator) -> None:
    fake_generator(error=SQLUnsafeError("只允许单条 SQL 语句"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 502
    assert "SQL generation failed" in response.json()["error"]


def test_schema_mismatch_returns_502(client: TestClient, fake_generator) -> None:
    fake_generator(error=SQLGenSchemaMismatchError("tables 包含不存在的表: payments"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 502
    assert "payments" in response.json()["error"]


def test_table_mismatch_returns_502(client: TestClient, fake_generator) -> None:
    fake_generator(error=SQLTableMismatchError("SQL 引用了未提供的表: payments"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 502


def test_invalid_json_returns_502(client: TestClient, fake_generator) -> None:
    fake_generator(error=SQLGenOutputInvalidError("LLM 输出 JSON 解析失败"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 502
    assert "JSON" in response.json()["error"]


def test_schema_linking_failure_returns_502(client: TestClient, fake_generator) -> None:
    fake_generator(error=SchemaLinkingInvalidError("表不存在: payments"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 502
    assert "Schema linking failed" in response.json()["error"]


def test_fewshot_dataset_error_returns_500(client: TestClient, fake_generator) -> None:
    fake_generator(error=FewShotDatasetNotFoundError("数据集不存在"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 500
    assert "dataset" in response.json()["error"].lower()


def test_provider_auth_error_returns_502(client: TestClient, fake_generator) -> None:
    fake_generator(error=LLMAuthenticationError("auth failed"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 502
    assert response.json()["error"] == "Mimo authentication failed"


def test_provider_key_missing_returns_503(client: TestClient, fake_generator) -> None:
    fake_generator(error=LLMApiKeyNotConfiguredError("Mimo API key is not configured"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 503
    assert response.json()["error"] == "Mimo API key is not configured"


def test_unexpected_error_returns_500(client: TestClient, fake_generator) -> None:
    fake_generator(error=RuntimeError("boom /path/to/secret"))
    response = client.post("/api/sql/generate", json={"question": "问题"})
    assert response.status_code == 500
    assert "boom" not in response.text
    assert "/path" not in response.text