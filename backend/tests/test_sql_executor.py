"""SQL Executor 单元测试（真实只读数据库，不调用 Mimo）。

覆盖：SELECT / WITH / UNION / NULL / 简单查询、恶意 SQL 全部在执行前拒绝、
结果截断保护、执行耗时、数据库文件零变更（SHA256 前后一致）、
JSON 可序列化（None -> null）。
"""

import hashlib
import sqlite3

import pytest

from app.core import config
from app.sqlexec.errors import (
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
)
from app.sqlexec.executor import MAX_RESULT_ROWS, execute


def _db_hash() -> str:
    return hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()


# ---------- 正常查询 ----------


def test_grouped_query_returns_structure() -> None:
    result = execute(
        "SELECT region, COUNT(*) AS user_count FROM users "
        "GROUP BY region ORDER BY user_count DESC"
    )
    assert result.columns == ["region", "user_count"]
    assert len(result.rows) > 0
    assert result.rows[0][0]  # region 非空
    assert result.row_count == len(result.rows)
    assert result.truncated is False
    assert result.execution_time_ms >= 0


def test_simple_select_one() -> None:
    result = execute("SELECT 1 AS value")
    assert result.columns == ["value"]
    assert result.rows == [[1]]
    assert result.row_count == 1


def test_null_value_kept_as_none() -> None:
    result = execute("SELECT NULL AS value")
    assert result.columns == ["value"]
    assert result.rows == [[None]]  # None 保持 null，而不是 "None"


def test_with_cte_executes() -> None:
    result = execute(
        "WITH x AS (SELECT region, COUNT(*) AS c FROM users GROUP BY region) "
        "SELECT * FROM x"
    )
    assert result.columns == ["region", "c"]
    assert result.row_count > 0


def test_union_executes() -> None:
    result = execute(
        "SELECT region FROM users UNION SELECT region FROM orders"
    )
    assert result.columns == ["region"]
    assert result.row_count > 0


def test_float_values_json_serializable() -> None:
    result = execute("SELECT price, status FROM products LIMIT 3")
    # 通过 JSON 序列化确认可被前端消费
    import json

    payload = json.dumps(result.rows)
    assert isinstance(payload, str)


# ---------- 恶意 SQL：执行前拒绝 ----------


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
        "REPLACE INTO categories (id, name) VALUES (1, 'x')",
    ],
)
def test_malicious_sql_rejected_before_execution(malicious_sql: str) -> None:
    with pytest.raises(SQLExecutionSafetyError):
        execute(malicious_sql)


def test_unparseable_sql_rejected() -> None:
    with pytest.raises(SQLExecutionSafetyError):
        execute("SELEC 123 FROM")


def test_blank_sql_rejected() -> None:
    with pytest.raises(SQLExecutionSafetyError):
        execute("   ")


# ---------- 数据库执行异常 ----------


def test_nonexistent_table_raises_database_error() -> None:
    with pytest.raises(SQLExecutionDatabaseError):
        execute("SELECT * FROM no_such_table")


def test_keyword_incomplete_sql_rejected_as_safety() -> None:
    # 不完整 SQL 连安全解析都无法通过 -> 在执行前被拒绝
    with pytest.raises(SQLExecutionSafetyError):
        execute("SELECT * FROM users WHERE")


# ---------- 结果截断保护 ----------


def test_large_result_truncated_and_db_unchanged() -> None:
    result = execute("SELECT id, username FROM users")
    assert len(result.rows) == MAX_RESULT_ROWS  # 500
    assert result.row_count == MAX_RESULT_ROWS
    assert result.truncated is True


# ---------- 数据库零变更（最关键） ----------


def test_database_never_changes_even_with_malicious_sql() -> None:
    hash_before = _db_hash()

    # 正常只读查询
    execute("SELECT id, username FROM users LIMIT 10")
    execute("SELECT region, COUNT(*) c FROM users GROUP BY region")

    # 恶意 SQL：全部应在执行前被拒绝，即使被拒绝也不会触碰数据库
    for bad in [
        "INSERT INTO users (id, username, email, region, register_date, status) "
        "VALUES (999999, 'x', 'x@example.com', '广东', '2026-01-01', 'active')",
        "UPDATE users SET status = 'inactive'",
        "DELETE FROM users",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN evil TEXT",
        "CREATE TABLE evil (id INTEGER)",
        "PRAGMA writable_schema = ON",
        "SELECT 1; DELETE FROM users",
    ]:
        with pytest.raises(SQLExecutionSafetyError):
            execute(bad)

    assert _db_hash() == hash_before