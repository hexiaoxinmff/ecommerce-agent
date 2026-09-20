"""SQL Repair API 测试（mock Repair LLM Provider；闭环执行使用真实 SQLite 只读）。

覆盖：/api/sql/repair 正常/拒绝/非法 JSON；/api/sql/execute-with-repair
成功闭环 / 无错误 / Safety 拒绝 / Repair 后仍失败（422 + 诊断）/ 参数 422。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import sql_repair as route_module
from app.fewshot.models import FewShotResult
from app.sqlrepair.repairer import SQLExecuteWithRepairOrchestrator, SQLRepairer


class _FakeProvider:
    name = "mimo"
    model = "mimo-v2.5-pro"

    def __init__(self, output: str = ""):
        self._output = output

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        return self._output


class _FakeRetriever:
    def retrieve(self, query) -> FewShotResult:
        return FewShotResult(question="q", matches=[])


def _install(monkeypatch, repair_output: str):
    """安装带固定 Repair 输出的真实 Repairer + Orchestrator。"""
    restore = lambda: None  # noqa: E731
    repairer = SQLRepairer(
        provider=_FakeProvider(repair_output), fewshot_retriever=_FakeRetriever()
    )
    orchestrator = SQLExecuteWithRepairOrchestrator(repairer=repairer)
    monkeypatch.setattr(route_module, "SQLRepairer", lambda: repairer)
    monkeypatch.setattr(
        route_module, "SQLExecuteWithRepairOrchestrator", lambda: orchestrator
    )


def _o(sql: str, reason: str = "修复") -> str:
    return json.dumps({"repaired_sql": sql, "repair_reason": reason}, ensure_ascii=False)


# ---------- /api/sql/repair ----------


def test_sql_repair_ok(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, _o("SELECT region, COUNT(*) AS user_count FROM users GROUP BY region"))  # noqa: E501
    response = client.post(
        "/api/sql/repair",
        json={
            "question": "哪个地区的用户最多？",
            "original_sql": "SELECT region, COUNT(*) FROM user GROUP BY region",
            "error_message": "no such table: user",
            "tables": ["users"],
            "columns": ["users.region"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "FROM users" in data["result"]["repaired_sql"]
    assert data["result"]["original_sql"]  # 修复前后 SQL 都被保留


def test_sql_repair_safety_reject_422(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, _o("DELETE FROM users"))
    response = client.post(
        "/api/sql/repair",
        json={
            "question": "q",
            "original_sql": "SELECT 1 FROM user",
            "error_message": "e",
            "tables": ["users"],
        },
    )
    assert response.status_code == 422
    assert "Safety" in response.json()["error"]


def test_sql_repair_invalid_json_502(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, "这不是 JSON")
    response = client.post(
        "/api/sql/repair",
        json={"question": "q", "original_sql": "SELECT 1", "error_message": "e"},
    )
    assert response.status_code == 502


def test_sql_repair_empty_question_422(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, _o("SELECT 1"))
    assert (
        client.post(
            "/api/sql/repair",
            json={"question": " ", "original_sql": "SELECT 1", "error_message": "e"},
        ).status_code
        == 422
    )


# ---------- /api/sql/execute-with-repair ----------


def test_execute_with_repair_success(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, _o("SELECT region, COUNT(*) AS user_count FROM users GROUP BY region", "修复表名"))  # noqa: E501
    response = client.post(
        "/api/sql/execute-with-repair",
        json={
            "question": "哪个地区的用户最多？",
            "sql": "SELECT region, COUNT(*) AS user_count FROM user GROUP BY region",
            "tables": ["users"],
            "columns": ["users.region", "users.username"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    result = data["result"]
    assert result["execute_count"] == 2
    assert result["repair_count"] == 1
    assert result["result"]["row_count"] > 0
    assert result["original_error"]  # 第一次错误保留


def test_execute_with_repair_no_error(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, "")
    response = client.post(
        "/api/sql/execute-with-repair",
        json={"question": "q", "sql": "SELECT region FROM users LIMIT 1", "tables": ["users"]},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["execute_count"] == 1
    assert result["repair_count"] == 0


def test_execute_with_repair_safety_reject_422(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, "")
    response = client.post(
        "/api/sql/execute-with-repair",
        json={"question": "q", "sql": "DELETE FROM users", "tables": ["users"]},
    )
    assert response.status_code == 422
    result = response.json()["result"]
    assert result["execute_count"] == 0
    assert result["repair_count"] == 0


def test_execute_with_repair_still_fails_422(client: TestClient, monkeypatch) -> None:
    # Repair 出可过校验但仍失败的 SQL（无前缀列名不存在）
    _install(monkeypatch, _o("SELECT nonexistent_col FROM users", "尝试"))
    response = client.post(
        "/api/sql/execute-with-repair",
        json={
            "question": "q",
            "sql": "SELECT region FROM user GROUP BY region",
            "tables": ["users"],
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    result = data["result"]
    assert result["execute_count"] == 2
    assert result["repair_count"] == 1
    assert result["repair_error"]  # 第二次失败原因保留
    assert result["original_error"]


def test_execute_with_repair_bad_repair_delete(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, _o("DELETE FROM users"))
    response = client.post(
        "/api/sql/execute-with-repair",
        json={
            "question": "q",
            "sql": "SELECT region FROM user GROUP BY region",
            "tables": ["users"],
        },
    )
    assert response.status_code == 422
    result = response.json()["result"]
    assert result["execute_count"] == 1  # 不执行第二次
    assert result["repair_count"] == 1
    assert "Safety" in result["repair_error"]


def test_execute_with_repair_empty_sql_422(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, "")
    assert (
        client.post(
            "/api/sql/execute-with-repair",
            json={"question": "q", "sql": "   "},
        ).status_code
        == 422
    )