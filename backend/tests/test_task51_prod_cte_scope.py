"""Task 51：Production CTE Output-Column Scope Validation —— deterministic tests。

用例 A–J（§五）+ 回归保护（§六）。纯离线，0 API。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.sqlcheck.scope_validator import check_sql_scope  # noqa: E402
from app.sqlexec.errors import (  # noqa: E402
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
    SQLExecutionScopeError,
)
from app.sqlexec.executor import execute  # noqa: E402

SCOPE_HIDDEN = "SCOPE_HIDDEN_CTE_COLUMN"
SCOPE_UNKNOWN = "SCOPE_UNKNOWN_RELATION"


def codes(sql: str) -> list[str]:
    return [v.code for v in check_sql_scope(sql).violations]


# --- A. Base table column ---
def test_A_base_table_column_pass():
    assert check_sql_scope("SELECT c.id, c.name FROM categories c").ok is True


# --- B. CTE exposed column ---
def test_B_cte_exposed_column_pass():
    sql = (
        "WITH rcs AS (SELECT o.region, c.name AS category_name, "
        "SUM(oi.subtotal) AS total_sales FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id GROUP BY o.region, c.id) "
        "SELECT rcs.category_name FROM rcs"
    )
    assert check_sql_scope(sql).ok is True


# --- C. CTE hidden column ---
def test_C_cte_hidden_column_fail():
    sql = (
        "WITH rcs AS (SELECT o.region, c.name AS category_name, "
        "SUM(oi.subtotal) AS total_sales FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id GROUP BY o.region, c.id) "
        "SELECT rcs.category_id FROM rcs"
    )
    result = check_sql_scope(sql)
    assert not result.ok
    assert codes(sql) == [SCOPE_HIDDEN]
    assert result.violations[0].column == "category_id"
    assert result.violations[0].qualifier == "rcs"
    assert SCOPE_UNKNOWN not in codes(sql)


# --- D. CTE internal hidden column (内部用 category_id，但 SELECT 未输出) ---
def test_D_cte_internal_hidden_column_fail():
    sql = (
        "WITH rcs AS (SELECT c.name AS category_name, SUM(oi.subtotal) AS total_sales "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id GROUP BY c.id, c.name) "
        "SELECT rcs.category_id FROM rcs"
    )
    assert not check_sql_scope(sql).ok
    assert SCOPE_HIDDEN in codes(sql)


# --- E. Subquery output ---
def test_E_subquery_output():
    ok_sql = "SELECT x.id, x.name FROM (SELECT p.id, p.name FROM products p) x"
    assert check_sql_scope(ok_sql).ok is True
    bad_sql = "SELECT x.price FROM (SELECT p.id, p.name FROM products p) x"
    result = check_sql_scope(bad_sql)
    assert not result.ok
    assert codes(bad_sql) == [SCOPE_HIDDEN]


# --- F. Base-table alias qualifier 兼容 ---
def test_F_base_table_qualifier_pass():
    assert check_sql_scope("SELECT o.total_amount FROM orders o").ok is True
    assert check_sql_scope("SELECT orders.total_amount FROM orders").ok is True


# --- G. 多 JOIN 两侧合法列 ---
def test_G_multijoin_legal_pass():
    sql = (
        "SELECT o.region, c.name FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id"
    )
    assert check_sql_scope(sql).ok is True


# --- H. JOIN ON 合法 CTE 列 ---
def test_H_join_on_legal_cte_pass():
    sql = (
        "WITH rcs AS (SELECT o.region, c.name AS category_name, "
        "SUM(oi.subtotal) AS total_sales FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id GROUP BY o.region, c.name) "
        "SELECT 1 FROM rcs JOIN categories c ON c.name = rcs.category_name"
    )
    assert check_sql_scope(sql).ok is True


# --- I. JOIN ON hidden CTE column ---
def test_I_join_on_hidden_cte_fail():
    sql = (
        "WITH rcs AS (SELECT o.region, c.name AS category_name, "
        "SUM(oi.subtotal) AS total_sales FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id GROUP BY o.region, c.name) "
        "SELECT 1 FROM rcs JOIN categories c ON c.id = rcs.category_id"
    )
    result = check_sql_scope(sql)
    assert not result.ok
    assert SCOPE_HIDDEN in codes(sql)


# --- J. unknown qualifier 保持既有行为 ---
def test_J_unknown_qualifier_preserved():
    result = check_sql_scope("SELECT foo.id FROM orders o")
    assert not result.ok
    assert codes("SELECT foo.id FROM orders o") == [SCOPE_UNKNOWN]
    msg = result.messages[0]
    assert "foo" in msg and "foo.id" in msg


# --- §六 回归保护 ---
def test_safety_still_rejects_drop():
    with pytest.raises(SQLExecutionSafetyError):
        execute("DROP TABLE orders")


def test_safety_still_rejects_multi_statement():
    with pytest.raises(SQLExecutionSafetyError):
        execute("SELECT 1; SELECT 2")


def test_scope_error_hierarchy_unchanged():
    assert issubclass(SQLExecutionScopeError, SQLExecutionDatabaseError)
    assert not issubclass(SQLExecutionScopeError, SQLExecutionSafetyError)


def test_normal_base_join_still_executes():
    result = execute("SELECT o.region FROM orders o LIMIT 2")
    assert result.row_count <= 2


def test_executor_rejects_hidden_cte_column_before_db(monkeypatch):
    """hidden CTE 列被生产 validator 在 DB 连接前拦截（E-0093 形态）。"""
    sql = (
        "WITH rcs AS (SELECT c.name AS category_name FROM categories c) "
        "SELECT 1 FROM rcs JOIN categories c ON c.id = rcs.category_id"
    )
    import app.sqlexec.executor as executor_module

    def _boom():
        raise AssertionError("不应建立数据库连接")

    monkeypatch.setattr(executor_module, "get_connection", _boom)
    with pytest.raises(SQLExecutionScopeError) as excinfo:
        execute(sql)
    assert "不属于" in str(excinfo.value) or "category_id" in str(excinfo.value)
    assert not isinstance(excinfo.value, SQLExecutionSafetyError)


def test_executor_rejects_e0093_pred_raw():
    """Task50 录得的 E-0093 pred 全文 → production validator 必须拦截。"""
    sql = (
        "WITH region_category_sales AS (SELECT o.region, c.name AS category_name, "
        "SUM(oi.subtotal) AS total_sales FROM orders o "
        "JOIN order_items oi ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id "
        "WHERE o.status != 'cancelled' AND o.order_date LIKE '2025%' "
        "GROUP BY o.region, c.id), ranked AS (SELECT region, category_name, total_sales, "
        "ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC) AS rn "
        "FROM region_category_sales rcs JOIN categories c ON c.id = rcs.category_id) "
        "SELECT region, category_name, ROUND(total_sales, 2) AS total_sales FROM ranked "
        "WHERE rn <= 3 ORDER BY region, rn"
    )
    result = check_sql_scope(sql)
    assert not result.ok
    assert [v.code for v in result.violations] == [SCOPE_HIDDEN]
    assert result.violations[0].column == "category_id"


# --- §五 legacy unknown relation 仍报 unknown（不合并成 hidden） ---
def test_legacy_unknown_relation_code_unchanged():
    assert codes("SELECT r.region FROM orders o") == [SCOPE_UNKNOWN]