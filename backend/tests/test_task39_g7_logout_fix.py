"""G7 回归测试（Task39）：查询历史 × Logout 的 session 外键冲突修复。

Task38 发现的阻塞缺陷：用户产生 query_history（session_id 指向当前会话）后
logout，`DELETE FROM auth_session` 被 FK 约束拒绝 → IntegrityError → 500，
会话残留、token 仍有效。修复（appdb.delete_session）：同事务先
`UPDATE query_history SET session_id = NULL WHERE session_id = ?` 再删除会话，
任一步失败整体回滚。

覆盖任务书 §八 6 项 + §九 命名回归。Agent 全程 monkeypatch fake（不调真实
LLM）；数据库使用 tmp_path 隔离库，正式 db/app.db 与 db/ecommerce.db 不被触碰。
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.models import AgentResult
from app.auth.security import hash_session_token
from app.core import config
from app.db import appdb
from app.main import app
from app.sqlexec.models import SQLExecutionResult

PASSWORD = "S3cret!pass"


@pytest.fixture()
def g7_client(tmp_path: Path, monkeypatch) -> TestClient:
    """临时应用库 + TestClient（正式 db/app.db 不被触碰）。"""
    db_path = tmp_path / "g7" / "test-app.db"
    monkeypatch.setattr(config, "APP_DB_PATH", db_path)
    appdb.init_app_db()
    return TestClient(app)


@pytest.fixture()
def fake_agent(monkeypatch):
    """Agent 成功路径替身（不调真实 LLM）。"""
    def _run(question: str) -> AgentResult:
        return AgentResult(
            question=question,
            success=True,
            generated_sql="SELECT region FROM users",
            execution_result=SQLExecutionResult(
                columns=["region"],
                rows=[["广东"], ["北京"]],
                row_count=2,
                truncated=False,
                execution_time_ms=1.0,
            ),
            execute_count=1,
            repair_count=0,
            total_time_ms=55.5,
        )

    monkeypatch.setattr("app.api.routes.agent.run_agent", _run)
    return _run


def _register(client: TestClient, username: str) -> None:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    assert resp.status_code == 201


def _login(client: TestClient, username: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _session_id(token: str) -> int:
    return appdb.get_session(hash_session_token(token))["id"]


# ---------- §九 核心回归：query → logout 保留历史 ----------


def test_query_then_logout_preserves_history(g7_client: TestClient, fake_agent) -> None:
    _register(g7_client, "carol")
    token = _login(g7_client, "carol")

    assert g7_client.post(
        "/api/agent/analyze", json={"question": "广东的用户数"}, headers=_auth(token)
    ).status_code == 200

    user_id = appdb.get_user_by_username("carol")["id"]
    before = appdb.list_query_history(user_id)
    assert len(before) == 1
    assert before[0]["session_id"] == _session_id(token)

    # logout：修复前此处 IntegrityError → 500
    assert g7_client.post("/api/auth/logout", headers=_auth(token)).status_code == 204
    # token 立即失效
    assert g7_client.get("/api/auth/me", headers=_auth(token)).status_code == 401

    # 历史记录仍然存在（重新登录后经 API 可见），且 session_id 已解除关联
    token2 = _login(g7_client, "carol")
    listing = g7_client.get("/api/history", headers=_auth(token2)).json()
    assert listing["total"] == 1
    after = appdb.list_query_history(user_id)
    assert len(after) == 1
    assert after[0]["session_id"] is None
    # 业务字段逐项保留
    for field in ("question", "sql", "success", "error_message", "result_summary",
                  "row_count", "total_time_ms", "created_at"):
        assert after[0][field] == before[0][field], field


# ---------- §八.1 / §八.2 ----------


def test_logout_returns_204_after_query(g7_client: TestClient, fake_agent) -> None:
    _register(g7_client, "dave")
    token = _login(g7_client, "dave")
    assert g7_client.post(
        "/api/agent/analyze", json={"question": "q"}, headers=_auth(token)
    ).status_code == 200
    assert g7_client.post("/api/auth/logout", headers=_auth(token)).status_code == 204


def test_me_401_after_logout_with_history(g7_client: TestClient, fake_agent) -> None:
    _register(g7_client, "erin")
    token = _login(g7_client, "erin")
    assert g7_client.post(
        "/api/agent/analyze", json={"question": "q"}, headers=_auth(token)
    ).status_code == 200
    g7_client.post("/api/auth/logout", headers=_auth(token))
    assert g7_client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    # 受保护 API 同样立即 401
    assert g7_client.get("/api/history", headers=_auth(token)).status_code == 401


# ---------- §八.3 / §八.4 ----------


def test_history_session_id_null_after_logout(g7_client: TestClient, fake_agent) -> None:
    _register(g7_client, "frank")
    token = _login(g7_client, "frank")
    assert g7_client.post(
        "/api/agent/analyze", json={"question": "q"}, headers=_auth(token)
    ).status_code == 200

    user_id = appdb.get_user_by_username("frank")["id"]
    assert appdb.list_query_history(user_id)[0]["session_id"] == _session_id(token)

    g7_client.post("/api/auth/logout", headers=_auth(token))

    row = appdb.list_query_history(user_id)[0]
    assert row["session_id"] is None
    # 会话行确已删除
    assert appdb.get_session(hash_session_token(token)) is None


# ---------- §八.5 多端 / 多用户 ----------


def test_multi_session_logout_unlinks_only_current(g7_client: TestClient, fake_agent) -> None:
    """同用户双端：A1 查询后登出，只解除 A1 历史关联；A2 会话与历史不受影响。"""
    _register(g7_client, "gina")
    token_a1 = _login(g7_client, "gina")
    token_a2 = _login(g7_client, "gina")

    for q, tok in (("A1 的提问", token_a1), ("A2 的提问", token_a2)):
        assert g7_client.post(
            "/api/agent/analyze", json={"question": q}, headers=_auth(tok)
        ).status_code == 200
    user_id = appdb.get_user_by_username("gina")["id"]
    sid_a1, sid_a2 = _session_id(token_a1), _session_id(token_a2)

    assert g7_client.post("/api/auth/logout", headers=_auth(token_a1)).status_code == 204

    assert g7_client.get("/api/auth/me", headers=_auth(token_a1)).status_code == 401
    assert g7_client.get("/api/auth/me", headers=_auth(token_a2)).status_code == 200

    rows = appdb.list_query_history(user_id)
    assert len(rows) == 2
    by_question = {r["question"]: r["session_id"] for r in rows}
    assert by_question["A1 的提问"] is None           # 仅 A1 解除关联
    assert by_question["A2 的提问"] == sid_a2          # A2 关联保持
    assert appdb.get_session(hash_session_token(token_a2)) is not None


def test_other_user_unaffected_by_logout(g7_client: TestClient, fake_agent) -> None:
    """A 查询后登出：B（另一用户）的 token、会话与数据完全不受影响。"""
    _register(g7_client, "hank")
    _register(g7_client, "iris")
    token_a = _login(g7_client, "hank")
    token_b = _login(g7_client, "iris")

    assert g7_client.post(
        "/api/agent/analyze", json={"question": "A 的问题"}, headers=_auth(token_a)
    ).status_code == 200

    assert g7_client.post("/api/auth/logout", headers=_auth(token_a)).status_code == 204

    assert g7_client.get("/api/auth/me", headers=_auth(token_a)).status_code == 401
    assert g7_client.get("/api/auth/me", headers=_auth(token_b)).status_code == 200
    # A 的历史仍存在（session_id 已置 NULL），B 不受影响
    a_id = appdb.get_user_by_username("hank")["id"]
    assert len(appdb.list_query_history(a_id)) == 1
    assert appdb.list_query_history(a_id)[0]["session_id"] is None
    assert g7_client.get("/api/history", headers=_auth(token_b)).json()["total"] == 0


# ---------- §八.6 事务失败 → 回滚，无半完成状态 ----------


class _FailOnExecute:
    """sqlite3 连接代理：对指定 SQL 前缀注入失败，其余全部转发真实连接。"""

    def __init__(self, conn, fail_prefix: str):
        self._conn = conn
        self._fail_prefix = fail_prefix.upper()  # 与 execute 内 upper() 归一化对齐

    def execute(self, sql, *args, **kwargs):
        if sql.strip().upper().startswith(self._fail_prefix):
            raise sqlite3.OperationalError(f"simulated failure: {self._fail_prefix}")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture()
def _isolated_user_with_history(g7_client: TestClient, fake_agent):
    _register(g7_client, "jack")
    token = _login(g7_client, "jack")
    assert g7_client.post(
        "/api/agent/analyze", json={"question": "q"}, headers=_auth(token)
    ).status_code == 200
    user_id = appdb.get_user_by_username("jack")["id"]
    return token, user_id


def test_rollback_on_delete_session_failure(
    g7_client: TestClient, _isolated_user_with_history, monkeypatch
) -> None:
    """DELETE 失败（UPDATE 已执行）→ 回滚：会话仍在、history.session_id 未被置 NULL。"""
    token, user_id = _isolated_user_with_history
    token_hash = hash_session_token(token)
    real_get_connection = appdb.get_connection
    monkeypatch.setattr(
        appdb,
        "get_connection",
        lambda: _FailOnExecute(real_get_connection(), "DELETE FROM auth_session"),
    )

    with pytest.raises(sqlite3.OperationalError):
        appdb.delete_session(token_hash)

    # 无半完成状态：会话未被删除，unlink 被 rollback
    assert appdb.get_session(token_hash) is not None
    row = appdb.list_query_history(user_id)[0]
    assert row["session_id"] == _session_id(token)
    assert appdb.count_query_history(user_id) == 1


def test_rollback_on_unlink_failure(
    g7_client: TestClient, _isolated_user_with_history, monkeypatch
) -> None:
    """UPDATE（unlink）失败 → 会话与历史均保持原状。"""
    token, user_id = _isolated_user_with_history
    token_hash = hash_session_token(token)
    real_get_connection = appdb.get_connection
    monkeypatch.setattr(
        appdb,
        "get_connection",
        lambda: _FailOnExecute(real_get_connection(), "UPDATE query_history"),
    )

    with pytest.raises(sqlite3.OperationalError):
        appdb.delete_session(token_hash)

    assert appdb.get_session(token_hash) is not None
    assert appdb.list_query_history(user_id)[0]["session_id"] == _session_id(token)


# ---------- 回归护栏：原语义保持 ----------


def test_logout_without_history_still_works(g7_client: TestClient) -> None:
    """无历史行时行为与修复前一致：204 → 401（unlink 为 no-op）。"""
    _register(g7_client, "kate")
    token = _login(g7_client, "kate")
    assert g7_client.post("/api/auth/logout", headers=_auth(token)).status_code == 204
    assert g7_client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_delete_session_semantics_unchanged(g7_client: TestClient) -> None:
    """appdb.delete_session 返回值语义保持：删除 True、重复删除 False。"""
    user_id = appdb.create_user("liam", "liam@example.com", "pbkdf2_sha256$1$s$d")
    token_hash = "tokenhash-g7"
    appdb.create_session(user_id, token_hash, "2026-12-31T00:00:00+00:00")
    assert appdb.delete_session(token_hash) is True
    assert appdb.delete_session(token_hash) is False


def test_no_dangling_session_reference_remains(g7_client: TestClient, fake_agent) -> None:
    """登出后 app.db 中不存在指向已删除会话的悬挂引用（FK 安全性终检）。"""
    _register(g7_client, "mona")
    token = _login(g7_client, "mona")
    assert g7_client.post(
        "/api/agent/analyze", json={"question": "q"}, headers=_auth(token)
    ).status_code == 200
    g7_client.post("/api/auth/logout", headers=_auth(token))

    db_path = Path(config.APP_DB_PATH)
    with closing(sqlite3.connect(db_path)) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM query_history h "
            "WHERE h.session_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM auth_session s WHERE s.id = h.session_id)"
        ).fetchone()[0]
    assert orphans == 0
