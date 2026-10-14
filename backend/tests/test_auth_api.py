"""认证 API 测试（Task37-4 / P3）。

覆盖任务 §九 的 21 项：Register（成功/冲突/校验）、Login（成功/失败统一
401/会话落库为 token_hash）、Me（Bearer 链路：缺失/畸形/未知/过期/正常）、
Logout（204/登出失效/无效 token 不泄漏）、Integration 全生命周期。

测试隔离：每个测试把 config.APP_DB_PATH 重定向到 tmp_path 并重新初始化，
正式 db/app.db 与业务库 db/ecommerce.db 全程不被触碰。
"""

import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.security import hash_session_token
from app.core import config
from app.db import appdb
from app.main import app

AUTH = {"Authorization": "Bearer {token}"}
INVALID_DETAIL = "Invalid credentials"


@pytest.fixture()
def auth_client(tmp_path, monkeypatch) -> TestClient:
    """独立临时应用库 + TestClient（不触碰正式 db/app.db）。"""
    db_path = tmp_path / "auth-api" / "test-app.db"
    monkeypatch.setattr(config, "APP_DB_PATH", db_path)
    appdb.init_app_db()
    return TestClient(app)


def _register(
    client: TestClient,
    username: str = "alice",
    email: str = "alice@example.com",
    password: str = "S3cret!pass",
):
    return client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def _login(client: TestClient, username: str = "alice", password: str = "S3cret!pass"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _token_of(response) -> str:
    return response.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _deactivate_user(username: str) -> None:
    """测试辅助：直接置 is_active = 0（appdb 无 update 函数，用 SQL 设置）。"""
    with closing(appdb.get_connection()) as conn:
        conn.execute("UPDATE auth_user SET is_active = 0 WHERE username = ?", (username,))
        conn.commit()


# ---------- Register ----------


def test_register_success(auth_client: TestClient) -> None:
    resp = _register(auth_client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] > 0
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["is_active"] is True
    # 不返回任何内部安全字段
    assert "password_hash" not in body
    assert "token_hash" not in body


def test_register_duplicate_username_409(auth_client: TestClient) -> None:
    assert _register(auth_client).status_code == 201
    # 精确重复与前后空白（trim 后同值）都冲突
    assert _register(auth_client, email="other@example.com").status_code == 409
    assert _register(auth_client, username="  alice  ", email="other2@example.com").status_code == 409


def test_register_duplicate_email_409(auth_client: TestClient) -> None:
    assert _register(auth_client).status_code == 201
    resp = _register(auth_client, username="bob")
    assert resp.status_code == 409


def test_register_empty_username_422(auth_client: TestClient) -> None:
    for bad in ("", "   "):
        resp = _register(auth_client, username=bad)
        assert resp.status_code == 422


def test_register_empty_password_422(auth_client: TestClient) -> None:
    for bad in ("", "   "):
        resp = _register(auth_client, password=bad)
        assert resp.status_code == 422


def test_register_invalid_email_422(auth_client: TestClient) -> None:
    resp = _register(auth_client, email="not-an-email")
    assert resp.status_code == 422


# ---------- Login ----------


def test_login_success(auth_client: TestClient) -> None:
    _register(auth_client)
    resp = _login(auth_client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    # expires_at 是未来的 ISO 8601 UTC
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires.tzinfo is not None
    assert expires > datetime.now(timezone.utc)
    assert body["user"] == {"id": body["user"]["id"], "username": "alice", "email": "alice@example.com"}


def test_login_wrong_password_401(auth_client: TestClient) -> None:
    _register(auth_client)
    resp = _login(auth_client, password="wrong-password")
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_login_unknown_user_401(auth_client: TestClient) -> None:
    resp = _login(auth_client, username="nobody")
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_login_inactive_user_401(auth_client: TestClient) -> None:
    _register(auth_client, username="bob", email="bob@example.com")
    _deactivate_user("bob")
    resp = _login(auth_client, username="bob")
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_login_creates_session(auth_client: TestClient) -> None:
    _register(auth_client)
    before = None  # 无需精确计数，登录后该用户必有会话
    token = _token_of(_login(auth_client))
    row = appdb.get_session(hash_session_token(token))
    assert before is None
    assert row is not None
    assert row["user_id"] == 1
    assert row["expires_at"] > appdb.now_iso()  # 未过期


def test_db_stores_token_hash_not_plaintext(auth_client: TestClient) -> None:
    _register(auth_client)
    token = _token_of(_login(auth_client))
    # 原始 token 无法查到会话；只有哈希能查到
    assert appdb.get_session(token) is None
    stored = appdb.get_session(hash_session_token(token))
    assert stored is not None
    assert stored["token_hash"] != token


# ---------- Me ----------


def test_me_without_authorization_401(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


@pytest.mark.parametrize(
    "header",
    [
        "",  # 空头
        "Basic YWxpY2U6cGFzcw==",  # 非 Bearer 方案
        "Bearer",  # 方案后无 token
        "Bearer ",  # 空 token
        "bearer-not-a-real-scheme",  # 畸形
        f"Bearer {base64.b64encode(b'garbage').decode()}",  # 随机串
    ],
)
def test_me_malformed_bearer_401(auth_client: TestClient, header: str) -> None:
    headers = {"Authorization": header} if header else {}
    resp = auth_client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_me_unknown_token_401(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/auth/me", headers=_auth_header("no-such-token"))
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_me_expired_token_401(auth_client: TestClient) -> None:
    _register(auth_client)
    # 直接写入一条已过期会话（过去时刻）
    appdb.create_session(
        appdb.get_user_by_username("alice")["id"],
        hash_session_token("expired-token"),
        "2020-01-01T00:00:00+00:00",
    )
    resp = auth_client.get("/api/auth/me", headers=_auth_header("expired-token"))
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


def test_me_with_valid_token_200(auth_client: TestClient) -> None:
    _register(auth_client)
    token = _token_of(_login(auth_client))
    resp = auth_client.get("/api/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["is_active"] is True


def test_me_response_excludes_hash_fields(auth_client: TestClient) -> None:
    _register(auth_client)
    token = _token_of(_login(auth_client))
    body = auth_client.get("/api/auth/me", headers=_auth_header(token)).json()
    assert "password_hash" not in body
    assert "token_hash" not in body


def test_me_rejects_token_of_deactivated_user(auth_client: TestClient) -> None:
    """登录后用户被置 inactive：既有会话也必须立即失效（active 检查在依赖里）。"""
    _register(auth_client)
    token = _token_of(_login(auth_client))
    assert auth_client.get("/api/auth/me", headers=_auth_header(token)).status_code == 200
    _deactivate_user("alice")
    resp = auth_client.get("/api/auth/me", headers=_auth_header(token))
    assert resp.status_code == 401
    assert resp.json()["detail"] == INVALID_DETAIL


# ---------- Logout ----------


def test_logout_success_204(auth_client: TestClient) -> None:
    _register(auth_client)
    token = _token_of(_login(auth_client))
    resp = auth_client.post("/api/auth/logout", headers=_auth_header(token))
    assert resp.status_code == 204
    assert resp.text == ""


def test_me_after_logout_401(auth_client: TestClient) -> None:
    _register(auth_client)
    token = _token_of(_login(auth_client))
    auth_client.post("/api/auth/logout", headers=_auth_header(token))
    resp = auth_client.get("/api/auth/me", headers=_auth_header(token))
    assert resp.status_code == 401


def test_logout_only_kills_presented_session(auth_client: TestClient) -> None:
    """多端登录：登出一个会话不影响该用户的其他会话。"""
    _register(auth_client)
    token_a = _token_of(_login(auth_client))
    token_b = _token_of(_login(auth_client))
    assert auth_client.post("/api/auth/logout", headers=_auth_header(token_a)).status_code == 204
    assert auth_client.get("/api/auth/me", headers=_auth_header(token_a)).status_code == 401
    assert auth_client.get("/api/auth/me", headers=_auth_header(token_b)).status_code == 200


def test_logout_invalid_token_no_internal_info(auth_client: TestClient) -> None:
    resp = auth_client.post("/api/auth/logout", headers=_auth_header("no-such-token"))
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"] == INVALID_DETAIL
    # 不泄漏内部信息（无堆栈 / SQL / 路径）
    assert set(body.keys()) == {"detail"}


# ---------- Integration：完整认证生命周期 ----------


def test_full_auth_lifecycle(auth_client: TestClient) -> None:
    # 1. 注册
    assert _register(auth_client, username="carol", email="carol@example.com").status_code == 201
    # 2. 登录
    login_resp = _login(auth_client, username="carol")
    assert login_resp.status_code == 200
    token = _token_of(login_resp)
    # 3. 当前用户
    me_resp = auth_client.get("/api/auth/me", headers=_auth_header(token))
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "carol"
    # 4. 登出
    assert auth_client.post("/api/auth/logout", headers=_auth_header(token)).status_code == 204
    # 5. 登出后再访问 me → 失败
    assert auth_client.get("/api/auth/me", headers=_auth_header(token)).status_code == 401


# ---------- OpenAPI 文档 ----------


def test_openapi_documents_auth_endpoints(auth_client: TestClient) -> None:
    schema = auth_client.get("/openapi.json").json()
    paths = schema["paths"]
    for path in ("/api/auth/register", "/api/auth/login", "/api/auth/me", "/api/auth/logout"):
        assert path in paths
    # Bearer 认证方案已进入 OpenAPI（/docs 的 Authorization 文档由它驱动）
    schemes = schema["components"]["securitySchemes"]
    assert any(v.get("scheme") == "bearer" or v.get("type") == "apiKey" for v in schemes.values())
    assert auth_client.get("/docs").status_code == 200
