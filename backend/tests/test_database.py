"""SQLite 只读访问层测试。

重点验证：
1. 只读连接可以正常打开，且可以执行 SELECT 1；
2. 可以读取真实业务表，行数与当前数据库一致；
3. 一切写操作（INSERT / UPDATE / DELETE / REPLACE / DROP / ALTER / CREATE）
   都会被 SQLite 拒绝（OperationalError）；
4. 测试全程数据库内容不发生变化（行数 + 文件哈希回归）；
5. /api/system/database 返回真实行数（非写死）。
"""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.db.sqlite import (
    DatabaseNotFoundError,
    get_connection,
    is_database_readable,
)

# 当前数据库（2026-09-14 生成，固定种子 20260914）的真实行数
EXPECTED_COUNTS = {
    "users": 2000,
    "categories": 30,
    "products": 500,
    "orders": 10000,
    "order_items": 30457,
}

# 各类写入语句：全部应被只读连接拒绝
WRITE_STATEMENTS = [
    "INSERT INTO users (id, username, email, region, register_date, status) "
    "VALUES (999998, '只读探针', 'readonly-probe@example.com', '广东', "
    "'2026-01-01', 'active')",
    "UPDATE orders SET total_amount = 0 WHERE id = 1",
    "DELETE FROM order_items WHERE id = 1",
    "REPLACE INTO categories (id, name, parent_id) "
    "VALUES (999998, '只读探针', NULL)",
    "DROP TABLE users",
    "ALTER TABLE products ADD COLUMN readonly_probe TEXT",
    "CREATE TABLE readonly_probe (id INTEGER)",
]


def _db_hash() -> str:
    """数据库文件内容哈希。"""
    return hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()


def _real_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """通过给定连接读取 5 张业务表真实行数。"""
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in EXPECTED_COUNTS
    }


def test_readonly_connection_opens() -> None:
    conn = get_connection()
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_select_one_works() -> None:
    with closing(get_connection()) as conn:
        (value,) = conn.execute("SELECT 1").fetchone()
        assert value == 1


def test_row_factory_is_sqlite_row() -> None:
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT username FROM users LIMIT 1").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert len(row["username"]) > 0


def test_real_tables_readable() -> None:
    with closing(get_connection()) as conn:
        assert _real_counts(conn) == EXPECTED_COUNTS


def test_connection_error_when_database_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "no-such-db.db")
    with pytest.raises(DatabaseNotFoundError):
        get_connection()
    assert is_database_readable() is False


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_write_operations_rejected(sql: str) -> None:
    with closing(get_connection()) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(sql)


def test_database_unchanged_after_failed_writes() -> None:
    """写操作被拒后，数据库行数与文件内容必须与原状完全一致。"""
    hash_before = _db_hash()
    with closing(get_connection()) as conn:
        assert _real_counts(conn) == EXPECTED_COUNTS
    assert _db_hash() == hash_before


def test_system_database_endpoint_returns_real_counts(client: TestClient) -> None:
    """/api/system/database 必须来自真实 SQL 查询，返回当前数据库真实行数。"""
    response = client.get("/api/system/database")
    assert response.status_code == 200
    data = response.json()
    assert data["database"] == "ecommerce.db"
    assert data["tables"] == 5
    for table, expected in EXPECTED_COUNTS.items():
        assert data[table] == expected


def test_system_database_endpoint_error_when_missing(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DB_PATH", Path("no-such-dir") / "ecommerce.db")
    response = client.get("/api/system/database")
    assert response.status_code == 503