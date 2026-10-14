"""Agent 查询历史落库 + History API 测试（Task37-5 / P4）。

覆盖任务 §十一 28 项：Agent 强制认证、成功/失败自动落库（user_id、question、
最终 SQL、row_count、total_time_ms）、error_message 安全（无 token/password/
secret）、GET（本人可见、倒序、分页、跨用户隔离）、DELETE（本人可删、跨用户
404、不存在 404）、完整生命周期。

Agent 调用全程 monkeypatch run_agent（不调真实 LLM）；用户通过真实
P3 注册/登录流程产生；数据库使用 tmp_path 隔离库。
"""

import pytest
from fastapi.testclient import TestClient

from app.agent.models import AgentResult
from app.auth.security import hash_session_token
from app.core import config
from app.db import appdb
from app.llm.provider import LLMNetworkError
from app.main import app
from app.sqlexec.models import SQLExecutionResult

AGENT_URL = "/api/agent/analyze"
INVALID_DETAIL = "Invalid credentials"


@pytest.fixture()
def p4_client(tmp_path, monkeypatch) -> TestClient:
    """临时应用库 + TestClient（正式 db/app.db 不被触碰）。"""
    db_path = tmp_path / "p4" / "test-app.db"
    monkeypatch.setattr(config, "APP_DB_PATH", db_path)
    appdb.init_app_db()
    return TestClient(app)


def _register(client: TestClient, username: str) -> None:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "S3cret!pass"},
    )
    assert resp.status_code == 201


def _login(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": "S3cret!pass"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _agent_call(client: TestClient, token: str, question: str):
    return client.post(AGENT_URL, json={"question": question}, headers=_auth(token))


def _session_row_id(token: str) -> int:
    return appdb.get_session(hash_session_token(token))["id"]


def _ok_result(question: str, *, sql: str = "SELECT region FROM users", repaired: str = "",
               row_count: int = 3, total_ms: float = 88.8) -> AgentResult:
    return AgentResult(
        question=question,
        success=True,
        generated_sql=sql,
        repaired_sql=repaired,
        execution_result=SQLExecutionResult(
            columns=["region"],
            rows=[["广东"], ["北京"], ["上海"]][:row_count],
            row_count=row_count,
            truncated=False,
            execution_time_ms=1.0,
        ),
        execute_count=1,
        repair_count=0,
        total_time_ms=total_ms,
    )


# ---------- Agent authentication（1-2） ----------


def test_agent_requires_auth(p4_client: TestClient) -> None:
    resp = p4_client.post(AGENT_URL, json={"question": "哪个地区用户最多？"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_agent_with_login_succeeds(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.agent.run_agent",
        lambda q: _ok_result(q),
    )
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    resp = _agent_call(p4_client, token, "哪个地区用户最多？")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------- Success persistence（3-9） ----------


def test_agent_success_persists_history(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.agent.run_agent",
        lambda q: _ok_result(q, repaired="SELECT region FROM users WHERE region = '广东'", row_count=1),
    )
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    assert _agent_call(p4_client, token, "广东的用户数").status_code == 200

    rows = appdb.list_query_history(appdb.get_user_by_username("alice")["id"])
    assert len(rows) == 1
    row = rows[0]
    # 4. user_id = 当前用户；8. session_id 关联当前会话
    assert row["user_id"] == appdb.get_user_by_username("alice")["id"]
    assert row["session_id"] == _session_row_id(token)
    # 5. question 正确
    assert row["question"] == "广东的用户数"
    # 6. final SQL 正确：repair 路径记录 repaired_sql
    assert row["sql"] == "SELECT region FROM users WHERE region = '广东'"
    # 7. success = 1
    assert row["success"] == 1
    # 8. row_count 正确
    assert row["row_count"] == 1
    # 9. total_time_ms > 0
    assert row["total_time_ms"] is not None and row["total_time_ms"] > 0
    # result_summary 来自既有 execution_result 字段
    assert "1 行" in row["result_summary"]


def test_agent_success_without_repair_records_generated_sql(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.agent.run_agent",
        lambda q: _ok_result(q, sql="SELECT 1", repaired=""),
    )
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    _agent_call(p4_client, token, "q")
    row = appdb.list_query_history(appdb.get_user_by_username("alice")["id"])[0]
    assert row["sql"] == "SELECT 1"


# ---------- Failure persistence（10-14） ----------


def test_agent_failure_persists_history_llm_error(p4_client: TestClient, monkeypatch) -> None:
    """LLM 失败（SQL 生成之前）：success=0、sql 为空串、error_message 安全。"""

    def boom(question: str):
        raise LLMNetworkError("Mimo network error")

    monkeypatch.setattr("app.api.routes.agent.run_agent", boom)
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    resp = _agent_call(p4_client, token, "q")
    assert resp.status_code == 503

    row = appdb.list_query_history(appdb.get_user_by_username("alice")["id"])[0]
    # 10-12
    assert row["success"] == 0
    assert row["error_message"] != ""
    # 14. 失败发生在 SQL 生成之前 → 空字符串
    assert row["sql"] == ""
    assert row["row_count"] is None
    assert row["session_id"] == _session_row_id(token)


def test_agent_failure_with_sql_records_sql(p4_client: TestClient, monkeypatch) -> None:
    """执行阶段失败：已有可用 SQL 也要记录。"""
    monkeypatch.setattr(
        "app.api.routes.agent.run_agent",
        lambda q: AgentResult(
            question=q,
            success=False,
            generated_sql="SELECT bad_sql FROM nothing",
            execute_count=2,
            repair_count=1,
            final_error="SQL execution failed after repair",
            http_status=422,
            total_time_ms=55.0,
        ),
    )
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    assert _agent_call(p4_client, token, "q").status_code == 422

    row = appdb.list_query_history(appdb.get_user_by_username("alice")["id"])[0]
    assert row["success"] == 0
    assert row["sql"] == "SELECT bad_sql FROM nothing"
    assert row["error_message"] == "SQL execution failed after repair"


def test_agent_failure_persists_history_internal_error(p4_client: TestClient, monkeypatch) -> None:
    def boom(question: str):
        raise RuntimeError("traceback secret stuff")

    monkeypatch.setattr("app.api.routes.agent.run_agent", boom)
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    resp = _agent_call(p4_client, token, "q")
    assert resp.status_code == 500
    row = appdb.list_query_history(appdb.get_user_by_username("alice")["id"])[0]
    assert row["success"] == 0
    assert row["error_message"] == "Agent analysis internal error"
    assert row["sql"] == ""


@pytest.mark.parametrize("field", ["error_message", "sql", "result_summary"])
def test_history_error_fields_contain_no_secrets(p4_client: TestClient, monkeypatch, field: str) -> None:
    """13. 入库字段经脱敏：不含真实凭据形态内容（token=值 / Bearer 值 / sk-密钥 / JWT）。"""
    monkeypatch.setattr(
        "app.api.routes.agent.run_agent",
        lambda q: AgentResult(
            question=q,
            success=False,
            generated_sql="SELECT 1",
            execute_count=1,
            repair_count=0,
            final_error="failed: token=abc123 password=xyz sk-ABCDEF123 Bearer eyJhbGci.eyJ4",
            http_status=422,
            total_time_ms=1.0,
        ),
    )
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    _agent_call(p4_client, token, "q")

    rows = appdb.list_query_history(appdb.get_user_by_username("alice")["id"])
    assert len(rows) == 1
    value = rows[0][field] or ""
    # 真实凭据值不入库
    for secret_value in ("abc123", "xyz", "ABCDEF123", "eyJhbGci"):
        assert secret_value not in value, f"{field} 泄漏凭据值: {secret_value}"
    # error_message 保持可理解（键名仍在，值已打码）
    if field == "error_message":
        assert "token=***" in value and "password=***" in value


# ---------- History GET（15-18） ----------


def test_history_list_own_desc_and_pagination(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.agent.run_agent",
        lambda q: _ok_result(q),
    )
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    for q in ("问题一", "问题二", "问题三"):
        assert _agent_call(p4_client, token, q).status_code == 200

    # 15. 能看到自己的历史；16. created_at 倒序（同时刻内 id 倒序）
    resp = p4_client.get("/api/history", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [item["question"] for item in body["items"]] == ["问题三", "问题二", "问题一"]
    # 响应不含内部字段
    assert all(
        "user_id" not in item and "password_hash" not in item and "token_hash" not in item
        for item in body["items"]
    )

    # 17. 分页有效（默认 page=1, page_size=20）
    p1 = p4_client.get("/api/history", params={"page": 1, "page_size": 2}, headers=_auth(token)).json()
    assert p1["page"] == 1 and p1["page_size"] == 2
    assert [i["question"] for i in p1["items"]] == ["问题三", "问题二"]
    p2 = p4_client.get("/api/history", params={"page": 2, "page_size": 2}, headers=_auth(token)).json()
    assert [i["question"] for i in p2["items"]] == ["问题一"]
    assert p2["total"] == 3


def test_history_user_a_cannot_see_user_b(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.agent.run_agent", lambda q: _ok_result(q))
    _register(p4_client, "alice")
    _register(p4_client, "bob")
    token_a = _login(p4_client, "alice")
    token_b = _login(p4_client, "bob")
    assert _agent_call(p4_client, token_a, "A 的提问").status_code == 200
    assert _agent_call(p4_client, token_b, "B 的提问").status_code == 200

    items_a = p4_client.get("/api/history", headers=_auth(token_a)).json()["items"]
    items_b = p4_client.get("/api/history", headers=_auth(token_b)).json()["items"]
    # 18. 用户 A 看不到用户 B 的历史
    assert [i["question"] for i in items_a] == ["A 的提问"]
    assert [i["question"] for i in items_b] == ["B 的提问"]


# ---------- History DELETE（19-22） ----------


def test_delete_own_history(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.agent.run_agent", lambda q: _ok_result(q))
    _register(p4_client, "alice")
    token = _login(p4_client, "alice")
    _agent_call(p4_client, token, "待删除")
    history_id = p4_client.get("/api/history", headers=_auth(token)).json()["items"][0]["id"]

    # 19. 本人可删除
    assert p4_client.delete(f"/api/history/{history_id}", headers=_auth(token)).status_code == 204
    # 20. 删除后 GET 不再出现
    remaining = p4_client.get("/api/history", headers=_auth(token)).json()
    assert remaining["total"] == 0 and remaining["items"] == []


def test_delete_cross_user_and_missing_404(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.agent.run_agent", lambda q: _ok_result(q))
    _register(p4_client, "alice")
    _register(p4_client, "bob")
    token_a = _login(p4_client, "alice")
    token_b = _login(p4_client, "bob")
    assert _agent_call(p4_client, token_b, "B 的私有历史").status_code == 200
    b_history_id = p4_client.get("/api/history", headers=_auth(token_b)).json()["items"][0]["id"]

    # 21. A 删 B 的 history → 404（不泄露归属），且 B 的历史仍在
    resp = p4_client.delete(f"/api/history/{b_history_id}", headers=_auth(token_a))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "History not found"
    assert p4_client.get("/api/history", headers=_auth(token_b)).json()["total"] == 1

    # 22. 删除不存在的 history → 404
    resp = p4_client.delete("/api/history/999999", headers=_auth(token_a))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "History not found"


# ---------- Multi-user isolation（23-27） ----------


def test_multi_user_isolation(p4_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.agent.run_agent", lambda q: _ok_result(q))
    _register(p4_client, "alice")
    _register(p4_client, "bob")
    token_a = _login(p4_client, "alice")
    token_b = _login(p4_client, "bob")

    # 23-24. 各自创建
    for q in ("A-1", "A-2"):
        assert _agent_call(p4_client, token_a, q).status_code == 200
    assert _agent_call(p4_client, token_b, "B-1").status_code == 200

    # 25-26. 各自只看到自己的
    a_items = p4_client.get("/api/history", headers=_auth(token_a)).json()
    b_items = p4_client.get("/api/history", headers=_auth(token_b)).json()
    assert a_items["total"] == 2 and [i["question"] for i in a_items["items"]] == ["A-2", "A-1"]
    assert b_items["total"] == 1 and [i["question"] for i in b_items["items"]] == ["B-1"]

    # 27. A 删 B 的 history 无效
    b_id = b_items["items"][0]["id"]
    assert p4_client.delete(f"/api/history/{b_id}", headers=_auth(token_a)).status_code == 404
    assert p4_client.get("/api/history", headers=_auth(token_b)).json()["total"] == 1

    # DB 层直接复核隔离（防 API 层意外放行）
    a_uid = appdb.get_user_by_username("alice")["id"]
    b_uid = appdb.get_user_by_username("bob")["id"]
    assert all(row["user_id"] == a_uid for row in appdb.list_query_history(a_uid))
    assert all(row["user_id"] == b_uid for row in appdb.list_query_history(b_uid))


# ---------- Integration lifecycle（28） ----------


def test_full_history_lifecycle(p4_client: TestClient, monkeypatch) -> None:
    # register
    _register(p4_client, "carol")
    # login
    token = _login(p4_client, "carol")
    # agent query
    monkeypatch.setattr("app.api.routes.agent.run_agent", lambda q: _ok_result(q))
    assert _agent_call(p4_client, token, "完整生命周期提问").status_code == 200
    # history GET
    listing = p4_client.get("/api/history", headers=_auth(token)).json()
    assert listing["total"] == 1
    history_id = listing["items"][0]["id"]
    # DELETE
    assert p4_client.delete(f"/api/history/{history_id}", headers=_auth(token)).status_code == 204
    # history GET again
    assert p4_client.get("/api/history", headers=_auth(token)).json()["total"] == 0


# ---------- History API 认证与 OpenAPI ----------


def test_history_requires_auth(p4_client: TestClient) -> None:
    assert p4_client.get("/api/history").status_code == 401
    assert p4_client.delete("/api/history/1").status_code == 401


def test_openapi_documents_history_endpoints(p4_client: TestClient) -> None:
    schema = p4_client.get("/openapi.json").json()
    assert "/api/history" in schema["paths"]
    assert "/api/history/{history_id}" in schema["paths"]
    assert p4_client.get("/docs").status_code == 200
