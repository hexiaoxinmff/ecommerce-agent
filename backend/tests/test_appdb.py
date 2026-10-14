"""应用库（app.db）可写访问层测试（Task37-2 / P1）。

覆盖 Task37-2 §十三 要求的 10 项：
创建 app.db、三表存在、创建 auth_user、username/email UNIQUE、
auth_session 关联 auth_user（含外键拒绝）、query_history 关联 auth_user、
delete_session、按 user_id 查询历史、用户隔离（A 拿不到 B 的历史、
跨用户删除无效）。

全部测试使用 tmp_path 临时应用库（monkeypatch config.APP_DB_PATH），
绝不触碰真实 db/app.db 与业务库 db/ecommerce.db。
"""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.core import config
from app.db.appdb import (
    AppDbNotFoundError,
    create_query_history,
    create_session,
    create_user,
    delete_query_history,
    delete_session,
    get_connection,
    get_session,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    init_app_db,
    list_query_history,
    now_iso,
)

# 测试专用口令哈希样例（格式占位，非明文密码；真实哈希算法属 P2 任务）
_HASH_A = "pbkdf2_sha256$600000$testsalt-a$deadbeef"
_HASH_B = "pbkdf2_sha256$600000$testsalt-b$feedface"

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")


@pytest.fixture()
def app_db(tmp_path: Path, monkeypatch) -> Path:
    """临时应用库：重定向 APP_DB_PATH 到 tmp_path 并完成幂等初始化。"""
    db_path = tmp_path / "app" / "test-app.db"
    monkeypatch.setattr(config, "APP_DB_PATH", db_path)
    assert init_app_db() == db_path
    return db_path


def _make_user(username: str = "alice", email: str = "alice@example.com") -> int:
    return create_user(username, email, _HASH_A)


# ---------- Test 1: app.db 可以创建（且幂等） ----------


def test_app_db_created_and_idempotent(app_db: Path) -> None:
    assert app_db.is_file()
    # 重复初始化不报错、不丢数据
    assert init_app_db() == app_db
    with closing(get_connection()) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM auth_user").fetchone()
    assert count == 0


# ---------- Test 2: 三张表存在 ----------


def test_three_tables_exist(app_db: Path) -> None:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    assert tuple(row["name"] for row in rows) == (
        "auth_session",
        "auth_user",
        "query_history",
    )


# ---------- Test 3: 可以创建 auth_user ----------


def test_create_user_and_lookup(app_db: Path) -> None:
    user_id = _make_user()
    assert isinstance(user_id, int) and user_id > 0

    by_name = get_user_by_username("alice")
    assert by_name is not None
    assert by_name["id"] == user_id
    assert by_name["username"] == "alice"
    assert by_name["email"] == "alice@example.com"
    assert by_name["password_hash"] == _HASH_A  # 只存哈希字符串
    assert by_name["is_active"] == 1
    assert _ISO_UTC_RE.match(by_name["created_at"])

    assert get_user_by_email("alice@example.com")["id"] == user_id
    assert get_user_by_id(user_id)["username"] == "alice"
    assert get_user_by_username("nobody") is None
    assert get_user_by_email("nobody@example.com") is None
    assert get_user_by_id(999999) is None


# ---------- Test 4: username UNIQUE 生效 ----------


def test_username_unique(app_db: Path) -> None:
    _make_user()
    with pytest.raises(sqlite3.IntegrityError):
        create_user("alice", "other@example.com", _HASH_B)


# ---------- Test 5: email UNIQUE 生效 ----------


def test_email_unique(app_db: Path) -> None:
    _make_user()
    with pytest.raises(sqlite3.IntegrityError):
        create_user("bob", "alice@example.com", _HASH_B)


# ---------- Test 6: auth_session 可以关联 auth_user ----------


def test_session_links_user(app_db: Path) -> None:
    user_id = _make_user()
    expires = "2026-12-31T00:00:00+00:00"
    session_id = create_session(user_id, "tokenhash-abc", expires)

    row = get_session("tokenhash-abc")
    assert row is not None
    assert row["id"] == session_id
    assert row["user_id"] == user_id
    assert row["expires_at"] == expires
    assert _ISO_UTC_RE.match(row["created_at"])

    # 不存在的令牌查不到
    assert get_session("tokenhash-missing") is None

    # 外键约束生效：不存在的 user_id 无法创建会话
    with pytest.raises(sqlite3.IntegrityError):
        create_session(999999, "tokenhash-orphan", expires)


# ---------- Test 7: query_history 可以关联 auth_user ----------


def test_history_links_user(app_db: Path) -> None:
    user_id = _make_user()
    session_id = create_session(user_id, "tokenhash-h1", "2026-12-31T00:00:00+00:00")
    history_id = create_query_history(
        user_id,
        "上月总销售额是多少？",
        session_id=session_id,
        sql="SELECT SUM(total_amount) FROM orders WHERE status != 'cancelled'",
        success=True,
        result_summary="1 行 · SUM(total_amount)=8,765,432.10",
        row_count=1,
        total_time_ms=123.4,
    )

    rows = list_query_history(user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == history_id
    assert row["user_id"] == user_id
    assert row["session_id"] == session_id
    assert row["question"] == "上月总销售额是多少？"
    assert row["success"] == 1
    assert row["row_count"] == 1
    assert row["total_time_ms"] == pytest.approx(123.4)
    assert _ISO_UTC_RE.match(row["created_at"])

    # 外键约束生效：不存在的 user_id 无法写入历史
    with pytest.raises(sqlite3.IntegrityError):
        create_query_history(999999, "孤儿历史")


# ---------- Test 8: delete_session 可删除 ----------


def test_delete_session(app_db: Path) -> None:
    user_id = _make_user()
    create_session(user_id, "tokenhash-del", "2026-12-31T00:00:00+00:00")

    assert delete_session("tokenhash-del") is True
    assert get_session("tokenhash-del") is None
    # 重复删除返回 False，不报错
    assert delete_session("tokenhash-del") is False


# ---------- Test 9: query_history 可以按 user_id 查询 ----------


def test_history_listed_by_user(app_db: Path) -> None:
    user_id = _make_user()
    for i in range(3):
        create_query_history(user_id, f"问题 {i}", success=True)

    rows = list_query_history(user_id)
    assert [row["question"] for row in rows] == ["问题 2", "问题 1", "问题 0"]

    # 分页
    assert [row["question"] for row in list_query_history(user_id, limit=2)] == [
        "问题 2",
        "问题 1",
    ]
    assert [row["question"] for row in list_query_history(user_id, limit=2, offset=2)] == [
        "问题 0"
    ]


# ---------- Test 10: query_history 用户隔离 ----------


def test_history_user_isolation(app_db: Path) -> None:
    user_a = _make_user("alice", "alice@example.com")
    user_b = create_user("bob", "bob@example.com", _HASH_B)

    history_a = create_query_history(user_a, "A 的私有提问", success=True)
    create_query_history(user_b, "B 的私有提问", success=True)

    # B 的列表里只有 B 的历史，拿不到 A 的
    rows_b = list_query_history(user_b)
    assert [row["question"] for row in rows_b] == ["B 的私有提问"]
    assert all(row["user_id"] == user_b for row in rows_b)

    # 跨用户删除无效：B 删不掉 A 的历史，且历史仍然存在
    assert delete_query_history(user_b, history_a) is False
    rows_a = list_query_history(user_a)
    assert [row["id"] for row in rows_a] == [history_a]

    # 本人删除有效
    assert delete_query_history(user_a, history_a) is True
    assert list_query_history(user_a) == []


# ---------- 补充：未初始化时报错、时间格式 ----------


def test_connection_error_when_app_db_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "no-such-dir" / "app.db")
    with pytest.raises(AppDbNotFoundError):
        get_connection()


def test_now_iso_is_utc_8601() -> None:
    assert _ISO_UTC_RE.match(now_iso())
