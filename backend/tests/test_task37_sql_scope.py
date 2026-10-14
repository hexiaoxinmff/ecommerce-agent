"""Task 37：SQL Scope / Alias 静态校验（E-0099 确定性缺陷修复）单元测试。

覆盖：
1. 真阳性 —— E-0099 的真实失败形态（CTE 别名 vs SELECT 限定符不一致）被捕获；
2. 假阴性防护 —— 合法 SQL 一律放行（含相关子查询、UNION、嵌套、CTE 等）；
3. 错误类型契约 —— Scope 错误属于「数据库阶段」而非「安全阶段」，
   保证 execute-with-repair 路由行为不被隐性改变；
4. 插入点契约 —— executor 与 repair validator 两条路径都生效；
5. 非越权 —— 解析失败、空 SQL 不由本模块判定（交回 Safety 职责）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.schema.metadata import SchemaCatalog  # noqa: E402
from app.sqlcheck.scope_validator import check_sql_scope  # noqa: E402
from app.sqlexec.errors import (  # noqa: E402
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
    SQLExecutionScopeError,
)
from app.sqlexec.executor import execute  # noqa: E402
from app.sqlrepair.errors import SQLRepairSchemaError  # noqa: E402
from app.sqlrepair.validator import validate_repair_output  # noqa: E402

# ---------------------------------------------------------------- 真阳性样本

# E-0099 实测失败形态：FROM region_sales rs，却引用 r.region
E0099_PRED = (
    "WITH region_sales AS (SELECT o.region, SUM(oi.subtotal) AS total_sales "
    "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "WHERE o.status != 'cancelled' GROUP BY o.region) "
    "SELECT r.region, rs.total_sales FROM region_sales rs"
)

# 真实基线里 Repair 的失败形态：修完仍引用 rs.region
E0099_REPAIR = (
    "WITH region_sales AS (SELECT o.region, SUM(oi.subtotal) AS total_sales "
    "FROM order_items oi JOIN orders o ON o.id = oi.order_id GROUP BY o.region) "
    "SELECT rs.region, rs.total_sales FROM region_sales r"
)

# ---------------------------------------------------------------- 假阳性样本（必须放行）

LEGITIMATE = {
    "basic_alias": "SELECT o.region FROM orders o",
    "table_name_qualifier": "SELECT orders.region FROM orders",
    "unqualified_column": "SELECT region FROM orders",
    "joins": (
        "SELECT o.region, oi.subtotal FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id"
    ),
    "cte_reference": (
        "WITH t AS (SELECT o.region, SUM(o.total_amount) AS amt FROM orders o "
        "GROUP BY o.region) SELECT t.region, t.amt FROM t"
    ),
    "cte_with_alias": (
        "WITH t AS (SELECT o.region FROM orders o) SELECT x.region FROM t x"
    ),
    "subquery_alias": (
        "SELECT x.a FROM (SELECT o.region AS a FROM orders o) x"
    ),
    "union": (
        "SELECT o.region FROM orders o UNION SELECT o.region FROM orders o"
    ),
    "nested_subquery": "SELECT t.n FROM (SELECT COUNT(*) AS n FROM orders) t",
    "select_alias_in_order_by": (
        "SELECT SUM(oi.subtotal) AS s FROM order_items oi ORDER BY s DESC"
    ),
    "having": (
        "SELECT o.region FROM orders o GROUP BY o.region "
        "HAVING SUM(o.total_amount) > 100"
    ),
    "group_by_not_selected": "SELECT COUNT(*) FROM orders o GROUP BY o.region",
    # 相关子查询：内层引用外层别名，必须合法（这是 gold FP 的主要来源）
    "correlated_subquery_e0060": (
        "SELECT c.name, COUNT(*) AS above_cnt FROM products p "
        "JOIN categories c ON c.id = p.category_id "
        "WHERE p.price > (SELECT AVG(p2.price) FROM products p2 "
        "WHERE p2.category_id = p.category_id) "
        "GROUP BY c.id, c.name HAVING COUNT(*) >= 2"
    ),
    "correlated_subquery_e0087": (
        "WITH prod_sales AS (SELECT p.id, p.category_id FROM products p "
        "JOIN order_items oi ON oi.product_id = p.id GROUP BY p.id) "
        "SELECT ps.id FROM prod_sales ps "
        "WHERE ps.id > (SELECT AVG(d.sold) FROM (SELECT p2.id, "
        "SUM(oi2.quantity) AS sold FROM products p2 "
        "JOIN order_items oi2 ON oi2.product_id = p2.id "
        "WHERE p2.category_id = ps.category_id GROUP BY p2.id) d)"
    ),
    "correlated_subquery_e0095": (
        "WITH pair_sales AS (SELECT o.region, SUM(oi.subtotal) AS revenue "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.region) "
        "SELECT ps.region FROM pair_sales ps "
        "WHERE ps.revenue > (SELECT AVG(t.avg_rev) FROM "
        "(SELECT region, AVG(revenue) AS avg_rev FROM pair_sales "
        "GROUP BY region) t WHERE t.region = ps.region)"
    ),
    "cross_join_cte": (
        "WITH a AS (SELECT region FROM orders), b AS (SELECT COUNT(*) AS n "
        "FROM orders) SELECT x.region, y.n FROM a x CROSS JOIN b y"
    ),
}


# ---------------------------------------------------------------- 1. 真阳性


def test_detects_e0099_alias_mismatch():
    result = check_sql_scope(E0099_PRED)
    assert not result.ok
    assert result.violations[0].qualifier == "r"
    assert result.violations[0].column == "region"


def test_detects_repair_alias_mismatch():
    result = check_sql_scope(E0099_REPAIR)
    assert not result.ok
    assert result.violations[0].qualifier == "rs"


def test_violation_describe_is_actionable():
    msg = check_sql_scope(E0099_PRED).messages[0]
    assert "r" in msg and "r.region" in msg


def test_multiple_bad_qualifiers_all_reported():
    sql = "SELECT a.x, b.y FROM orders o"
    result = check_sql_scope(sql)
    assert not result.ok
    assert {v.qualifier for v in result.violations} == {"a", "b"}


# ---------------------------------------------------------------- 2. 假阳性


@pytest.mark.parametrize("name,sql", sorted(LEGITIMATE.items()))
def test_legitimate_sql_never_flagged(name, sql):
    result = check_sql_scope(sql)
    assert result.ok, f"{name} 被误报: {result.messages}"


def test_100_benchmark_gold_sql_zero_false_positives():
    """冻结基准 100 题 gold SQL 必须零误报（本任务的硬性门槛）。"""
    dataset = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
    data = json.loads(dataset.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data

    flagged = []
    for item in items:
        sql = item.get("gold_sql") or ""
        if sql.strip() and not check_sql_scope(sql).ok:
            flagged.append(item["id"])
    assert flagged == [], f"gold SQL 误报: {flagged}"


# ---------------------------------------------------------------- 3. 错误类型契约


def test_scope_error_is_database_domain_not_safety():
    """Scope 错误必须属于数据库故障域，否则 Repair 路由会被隐性改变。"""
    assert issubclass(SQLExecutionScopeError, SQLExecutionDatabaseError)
    assert not issubclass(SQLExecutionScopeError, SQLExecutionSafetyError)


def test_executor_raises_scope_error_not_safety_error():
    with pytest.raises(SQLExecutionScopeError) as excinfo:
        execute(E0099_PRED)
    assert not isinstance(excinfo.value, SQLExecutionSafetyError)


def test_executor_still_rejects_unsafe_sql_as_safety_error():
    """既有 Safety 语义不得被 Scope 校验改写。"""
    with pytest.raises(SQLExecutionSafetyError):
        execute("DROP TABLE orders")


def test_scope_check_runs_before_database_connection(monkeypatch):
    """Scope 校验必须早于任何数据库连接建立。"""
    import app.sqlexec.executor as executor_module

    def _boom():
        raise AssertionError("不应建立数据库连接")

    monkeypatch.setattr(executor_module, "get_connection", _boom)
    with pytest.raises(SQLExecutionScopeError):
        execute(E0099_PRED)


def test_normal_sql_still_executes(monkeypatch):
    """合法 SQL 必须原样执行，不受新增校验影响。"""
    result = execute("SELECT o.region FROM orders o LIMIT 3")
    assert result.row_count <= 3
    assert result.columns == ["region"]


# ---------------------------------------------------------------- 4. Repair 插入点


def _repair_payload(sql: str) -> str:
    return json.dumps({"repaired_sql": sql, "repair_reason": "fix alias"})


def test_repair_validator_rejects_undefined_alias():
    catalog = SchemaCatalog.get_cached()
    with pytest.raises(SQLRepairSchemaError):
        validate_repair_output(
            _repair_payload(E0099_PRED),
            E0099_PRED,
            ["orders", "order_items", "region_sales"],
            catalog,
        )


def test_repair_validator_accepts_correct_alias():
    """修正别名后，Repair 校验不再因「未定义别名」而拒绝。

    注意：本用例断言的是**错误类型/理由的改变**，而非「一定通过」。
    原因是 master 基线的 `_check_spelled_columns` 存在一个**既有的、与
    Task 37 无关的**缺陷：它把 CTE 别名当作真实表名送去 catalog 查列，
    于是任何 `cte_alias.col` 都会被判为「字段不存在」。该缺陷不在本任务
    变更边界内（修它会改变 Repair 的接受行为），因此这里只验证
    Scope 校验引入了**更精确的拒绝理由**，不擅自放宽既有约束。
    """
    catalog = SchemaCatalog.get_cached()
    good = (
        "WITH region_sales AS (SELECT o.region, SUM(oi.subtotal) AS total_sales "
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "GROUP BY o.region) "
        "SELECT rs.region, rs.total_sales FROM region_sales rs"
    )
    with pytest.raises(SQLRepairSchemaError) as excinfo:
        validate_repair_output(
            _repair_payload(good), E0099_PRED, ["orders", "order_items"], catalog
        )
    # 不再是「未定义别名」——说明 Scope 校验已放行该 SQL
    assert "未定义的表别名" not in str(excinfo.value)


def test_repair_validator_scope_reason_takes_priority_for_bad_alias():
    """未定义别名时，拒绝理由必须明确指向别名问题。"""
    catalog = SchemaCatalog.get_cached()
    with pytest.raises(SQLRepairSchemaError) as excinfo:
        validate_repair_output(
            _repair_payload(E0099_PRED),
            E0099_PRED,
            ["orders", "order_items", "region_sales"],
            catalog,
        )
    assert "未定义的表别名" in str(excinfo.value)


def test_baseline_spelled_column_check_rejects_cte_alias():
    """固化既有缺陷的事实：CTE 别名会被 _check_spelled_columns 拒绝。

    这是 master 基线的既有行为（已验证与 git HEAD 逐字一致），
    记录在此是为了防止将来有人误以为它是 Task 37 引入的回归。
    若后续任务修复该缺陷，本测试应当**有意**更新。
    """
    from app.sqlrepair.validator import _check_spelled_columns

    sql = "WITH t AS (SELECT o.region FROM orders o) SELECT rs.region FROM t rs"
    statement = __import__("sqlglot").parse_one(sql, read="sqlite")
    with pytest.raises(SQLRepairSchemaError):
        _check_spelled_columns(statement, SchemaCatalog.get_cached())


# ---------------------------------------------------------------- 5. 非越权


def test_parse_failure_is_not_this_modules_job():
    """语法错误由 Safety 负责，Scope 校验不越权判定。"""
    result = check_sql_scope("SELECT FROM WHERE ((")
    assert result.ok is True


def test_empty_and_whitespace_sql_are_passthrough():
    assert check_sql_scope("").ok is True
    assert check_sql_scope("   \n  ").ok is True


def test_scope_validator_imports_nothing_but_sqlglot():
    """模块必须保持零外部依赖。

    检查的是**实际 import 语句**而非源码全文 —— 文档里会提到被禁止的模块名
    （说明「本模块不依赖 X」），用全文 grep 会把说明文字当成违规，属自欺式测试。
    """
    import ast

    source = (
        PROJECT_ROOT / "backend" / "app" / "sqlcheck" / "scope_validator.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    allowed = {"__future__", "dataclasses", "sqlglot", "sqlglot.expressions",
               "sqlglot.optimizer.scope"}
    assert imported <= allowed, f"出现未预期依赖: {sorted(imported - allowed)}"

    for forbidden in ("app.schema.metadata", "app.llm.provider", "sqlite3",
                      "app.db.sqlite"):
        assert forbidden not in imported, f"不应依赖 {forbidden}"
