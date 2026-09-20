"""POST /api/sql/execute API 测试（真实只读数据库，不调用 Mimo）。

覆盖：正常执行 200、空/空白/超长 SQL 422、恶意 SQL 422（执行前拒绝）、
数据库执行异常 500、未预期异常 500、截断仍 200、JSON 序列化 None -> null。
"""

import pytest
from fastapi.testclient import TestClient

from app.sqlexec import executor as executor_module


def test_execute_ok(client: TestClient) -> None:
    response = client.post(
        "/api/sql/execute",
        json={"sql": "SELECT region, COUNT(*) AS user_count FROM users GROUP BY region"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["error"] == ""
    result = data["result"]
    assert result["columns"] == ["region", "user_count"]
    assert len(result["rows"]) > 0
    assert result["row_count"] == len(result["rows"])
    assert result["truncated"] is False
    assert result["execution_time_ms"] >= 0


def test_execute_null_serialized_as_json_null(client: TestClient) -> None:
    response = client.post("/api/sql/execute", json={"sql": "SELECT NULL AS value"})
    assert response.status_code == 200
    assert response.json()["result"]["rows"] == [[None]]


def test_empty_sql_rejected(client: TestClient) -> None:
    assert client.post("/api/sql/execute", json={"sql": ""}).status_code == 422


def test_blank_sql_rejected(client: TestClient) -> None:
    assert client.post("/api/sql/execute", json={"sql": "   "}).status_code == 422


def test_too_long_sql_rejected(client: TestClient) -> None:
    response = client.post("/api/sql/execute", json={"sql": "SELECT " + "a" * 10001})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "malicious_sql",
    [
        "INSERT INTO users (id, username, email, region, register_date, status) "
        "VALUES (999999, 'x', 'x@example.com', '广东', '2026-01-01', 'active')",
        "UPDATE users SET status = 'inactive'",
        "DELETE FROM users",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN evil TEXT",
        "CREATE TABLE evil (id INTEGER)",
        "PRAGMA writable_schema = ON",
        "SELECT 1; DELETE FROM users",
    ],
)
def test_malicious_sql_rejected_with_422(client: TestClient, malicious_sql: str) -> None:
    response = client.post("/api/sql/execute", json={"sql": malicious_sql})
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert "rejected" in data["error"].lower()


def test_database_error_returns_500(client: TestClient) -> None:
    response = client.post("/api/sql/execute", json={"sql": "SELECT * FROM no_such_table"})
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert data["error"]


def test_truncated_result_still_returns_200(client: TestClient) -> None:
    response = client.post("/api/sql/execute", json={"sql": "SELECT id, username FROM users"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert len(result["rows"]) == executor_module.MAX_RESULT_ROWS
    assert result["truncated"] is True
    assert result["row_count"] == executor_module.MAX_RESULT_ROWS


def test_unexpected_exception_returns_fixed_message(client: TestClient, monkeypatch) -> None:
    from app.api.routes import sql_execute as route_module

    def boom(sql: str):
        raise RuntimeError("internal boom /path/to/secret")

    monkeypatch.setattr(route_module, "execute", boom)
    response = client.post("/api/sql/execute", json={"sql": "SELECT 1"})
    assert response.status_code == 500
    assert "boom" not in response.text
    assert "/path" not in response.text