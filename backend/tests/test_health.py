"""GET /api/health 测试。

覆盖：
- 正常情况：200，status="ok"，database.status="ok"，type="sqlite"，name="ecommerce.db"；
- 退化情况（数据库文件不存在）：503，status="degraded"，database.status="error"；
- /docs、/redoc、OpenAPI schema 可访问。
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.core import config


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ecommerce-analysis-agent"
    assert data["database"] == {
        "status": "ok",
        "type": "sqlite",
        "name": "ecommerce.db",
    }


def test_health_reports_runtime_llm_config(client: TestClient) -> None:
    """Phase 4：health 携带实际配置的 Provider/Model（前端 Runtime LLM 徽标数据源）。

    断言对齐 config 真实值而非硬编码：llm.provider 必须等于当前
    LLM_PROVIDER 配置，model 与配置一致或为 null（未配置模型名时）。
    """
    response = client.get("/api/health")
    assert response.status_code == 200
    llm = response.json()["llm"]
    assert llm is not None
    assert llm["provider"] == config.LLM_PROVIDER
    expected_model = (config.MIMO_MODEL or "").strip() or None
    assert llm["model"] == expected_model


def test_health_degraded_when_database_missing(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DB_PATH", Path("no-such-dir") / "ecommerce.db")
    response = client.get("/api/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["service"] == "ecommerce-analysis-agent"
    assert data["database"] == {
        "status": "error",
        "type": "sqlite",
        "name": "ecommerce.db",
    }


def test_docs_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_openapi_contains_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/health" in schema["paths"]
    assert "/api/system/database" in schema["paths"]