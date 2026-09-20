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