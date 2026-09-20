"""数据库基线验证测试。

只测试数据库本身是否正确（结构、约束、数据量、金额口径、业务 SQL 可执行），
不测试任何 Text2SQL 相关功能。
"""

import sqlite3
import sys
from pathlib import Path

import pytest

# 将项目根目录加入模块搜索路径，以便导入 scripts 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.init_db import DB_PATH, main as init_db_main  # noqa: E402


@pytest.fixture(scope="session")
def conn():
    """数据库连接（外键约束开启）；库不存在时自动重建。"""
    if not DB_PATH.exists():
        init_db_main()
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def test_database_opens_and_integrity(conn):
    """1. 数据库可以正常打开，且完整性检查通过。"""
    (result,) = conn.execute("PRAGMA integrity_check").fetchone()
    assert result == "ok"


def test_five_tables_exist(conn):
    """2. 5 张核心业务表存在。"""
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
        "AND name IN ('users', 'categories', 'products', 'orders', 'order_items')"
    ).fetchone()
    assert count == 5


def test_primary_keys_exist(conn):
    """3. 每张表都有主键。"""
    tables = ["users", "categories", "products", "orders", "order_items"]
    for table in tables:
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        pk_columns = [col[1] for col in info if col[5] > 0]
        assert pk_columns, f"{table} 缺少主键"


def test_foreign_keys_exist(conn):
    """4. 外键关系真实存在。"""
    expected = {
        "categories": {("parent_id", "categories")},
        "products": {("category_id", "categories")},
        "orders": {("user_id", "users")},
        "order_items": {("order_id", "orders"), ("product_id", "products")},
    }
    for table, fks in expected.items():
        actual = {
            (row[3], row[2])
            for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }
        assert fks <= actual, f"{table} 外键不完整: 期望 {fks}, 实际 {actual}"


def test_row_counts_in_expected_range(conn):
    """5. 数据量达到预期规模（允许随机生成少量偏差）。"""
    expected = {
        "users": (1900, 2100),
        "categories": (29, 31),
        "products": (480, 520),
        "orders": (9800, 10200),
        "order_items": (29500, 30500),
    }
    for table, (low, high) in expected.items():
        (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        assert low <= count <= high, f"{table} 数据量 {count} 超出预期范围"


def test_amount_columns_exist(conn):
    """6/7. orders.total_amount 与 order_items.subtotal 字段存在。"""
    orders_cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
    items_cols = {row[1] for row in conn.execute("PRAGMA table_info(order_items)")}
    assert "total_amount" in orders_cols
    assert "subtotal" in items_cols


def test_basic_select_works(conn):
    """8. 基本 SELECT 可正常执行。"""
    (count,) = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    assert count > 0


def test_business_queries_execute(conn):
    """9. 至少 3 条（此处 5 条）有实际业务意义的 SQL 可执行并返回合理结果。"""
    # 查询 1：订单总数
    (order_count,) = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
    assert order_count > 0

    # 查询 2：订单总销售额
    (total_sales,) = conn.execute(
        "SELECT ROUND(SUM(total_amount), 2) FROM orders"
    ).fetchone()
    assert total_sales > 0

    # 查询 3：商品销量 Top 5（统一口径：排除 cancelled 订单）
    top_products = conn.execute(
        "SELECT p.name, SUM(oi.quantity) AS sold "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY p.id ORDER BY sold DESC LIMIT 5"
    ).fetchall()
    assert len(top_products) == 5
    assert all(row[1] > 0 for row in top_products)

    # 查询 4：分类销售额 Top 5（统一口径：排除 cancelled 订单）
    top_categories = conn.execute(
        "SELECT c.name, ROUND(SUM(oi.subtotal), 2) AS revenue "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY c.id ORDER BY revenue DESC LIMIT 5"
    ).fetchall()
    assert len(top_categories) == 5
    assert all(row[1] > 0 for row in top_categories)

    # 查询 5：按月统计销售趋势
    monthly = conn.execute(
        "SELECT strftime('%Y-%m', order_date) AS ym, COUNT(*), "
        "ROUND(SUM(total_amount), 2) "
        "FROM orders GROUP BY ym ORDER BY ym"
    ).fetchall()
    assert len(monthly) >= 20
    assert all(row[1] > 0 for row in monthly)


def test_foreign_key_enforcement(conn):
    """10. 外键约束正常工作（插入不存在用户的订单必须失败）。"""
    (max_user_id,) = conn.execute("SELECT MAX(id) FROM users").fetchone()
    bad_user_id = max_user_id + 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (user_id, order_date, status, region, total_amount) "
            "VALUES (?, '2026-01-01', 'pending', '广东', 100.0)",
            (bad_user_id,),
        )
    conn.rollback()
    # 验证失败后没有残留脏数据
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE user_id = ?", (bad_user_id,)
    ).fetchone()
    assert count == 0


def test_orphan_rows_not_exist(conn):
    """附加检查：所有外键引用有效，无孤儿行。"""
    orphan_checks = [
        ("orders", "user_id", "users"),
        ("order_items", "order_id", "orders"),
        ("order_items", "product_id", "products"),
        ("products", "category_id", "categories"),
        ("categories", "parent_id", "categories"),
    ]
    for child, fk, parent in orphan_checks:
        (count,) = conn.execute(
            f"SELECT COUNT(*) FROM {child} c "
            f"WHERE c.{fk} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = c.{fk})"
        ).fetchone()
        assert count == 0, f"{child}.{fk} 存在 {count} 条孤儿记录"


def test_subtotal_formula(conn):
    """附加检查：subtotal = unit_price × quantity（保留两位小数的容差内）。"""
    (bad,) = conn.execute(
        "SELECT COUNT(*) FROM order_items "
        "WHERE ABS(subtotal - ROUND(unit_price * quantity, 2)) > 0.011"
    ).fetchone()
    assert bad == 0


def test_order_amount_semantics(conn):
    """附加检查：金额口径一致性。

    取消订单 total=0；其余订单 total = 明细合计 − 订单级优惠 + 运费。
    """
    rows = conn.execute(
        "SELECT o.id, o.status, o.total_amount, o.discount_amount, o.shipping_fee, "
        "ROUND(COALESCE(SUM(oi.subtotal), 0), 2) AS sub_sum "
        "FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.id"
    ).fetchall()
    violations = 0
    cancelled_bad = 0
    for _, status, total, discount, shipping, sub_sum in rows:
        if status == "cancelled":
            if abs(total) > 0.001 or discount != 0 or shipping != 0:
                cancelled_bad += 1
            continue
        expected = round(sub_sum - discount + shipping, 2)
        if abs(total - expected) > 0.011:
            violations += 1
    assert violations == 0
    assert cancelled_bad == 0


def test_amount_difference_exists(conn):
    """附加检查：存在部分订单，明细合计与实付金额有可解释的业务差异。"""
    (diff_count,) = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT o.total_amount, ROUND(COALESCE(SUM(oi.subtotal), 0), 2) AS sub_sum "
        "  FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.id "
        "  WHERE o.status != 'cancelled' "
        "  GROUP BY o.id "
        ") WHERE ABS(total_amount - sub_sum) > 0.1"
    ).fetchone()
    assert diff_count > 0


def test_cancelled_orders_have_items_but_zero_total(conn):
    """附加检查：取消订单允许有明细行，但实付金额为 0。"""
    (with_items,) = conn.execute(
        "SELECT COUNT(DISTINCT o.id) FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id WHERE o.status = 'cancelled'"
    ).fetchone()
    assert with_items > 0
    (bad,) = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'cancelled' AND total_amount != 0"
    ).fetchone()
    assert bad == 0


def test_cancelled_orders_excluded_from_sales_stats(conn):
    """统一口径：cancelled 订单的 order_items 不进入实际销量/销售额统计。"""
    # 1. 数据库中确实存在 cancelled 订单
    (cancelled_orders,) = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'"
    ).fetchone()
    assert cancelled_orders > 0

    # 2. cancelled 订单确实存在 order_items（因此必须靠过滤排除）
    (cancelled_lines,) = conn.execute(
        "SELECT COUNT(*) FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.status = 'cancelled'"
    ).fetchone()
    assert cancelled_lines > 0

    # 3. 商品销量统计：排除 cancelled 的结果 = 总量 − 取消部分，且确实少了
    (qty_all,) = conn.execute("SELECT SUM(quantity) FROM order_items").fetchone()
    (qty_cancelled,) = conn.execute(
        "SELECT SUM(oi.quantity) FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.status = 'cancelled'"
    ).fetchone()
    (qty_excluded,) = conn.execute(
        "SELECT SUM(oi.quantity) FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled'"
    ).fetchone()
    assert qty_cancelled > 0
    assert qty_excluded == qty_all - qty_cancelled
    assert qty_excluded < qty_all

    # 4. 分类销售额统计：同样验证排除口径
    (rev_all,) = conn.execute("SELECT SUM(subtotal) FROM order_items").fetchone()
    (rev_cancelled,) = conn.execute(
        "SELECT SUM(oi.subtotal) FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.status = 'cancelled'"
    ).fetchone()
    (rev_excluded,) = conn.execute(
        "SELECT SUM(oi.subtotal) FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled'"
    ).fetchone()
    assert rev_cancelled > 0
    assert round(rev_excluded, 2) == round(rev_all - rev_cancelled, 2)
    assert rev_excluded < rev_all

    # 5. 修正后的分类销售额 Top SQL 确能正常执行
    top_categories = conn.execute(
        "SELECT c.name, ROUND(SUM(oi.subtotal), 2) AS revenue "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY c.id ORDER BY revenue DESC LIMIT 5"
    ).fetchall()
    assert len(top_categories) == 5