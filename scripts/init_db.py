"""初始化电商 SQLite 数据库。

流程：删除旧数据库 → 建表 → 插入数据 → 建立索引 → 执行基本验证。

用法（在项目根目录）：
    python scripts/init_db.py

数据库文件是生成物（db/ecommerce.db，不入 git），
本脚本与 scripts/generate_data.py 才是数据的权威来源。
"""

import os
import sqlite3
import sys
from pathlib import Path

# 保证直接运行与从测试导入两种方式都能找到 generate_data
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_data  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "ecommerce.db"

SCHEMA_DDL = """
CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    region        TEXT NOT NULL,
    register_date DATE NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('active', 'inactive'))
);

CREATE TABLE categories (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES categories(id)
);

CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    price       REAL NOT NULL CHECK (price > 0),
    status      TEXT NOT NULL CHECK (status IN ('on_sale', 'off_sale'))
);

CREATE TABLE orders (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    order_date      DATE NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'completed', 'cancelled')),
    region          TEXT NOT NULL,
    discount_amount REAL NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    shipping_fee    REAL NOT NULL DEFAULT 0 CHECK (shipping_fee >= 0),
    total_amount    REAL NOT NULL CHECK (total_amount >= 0)
);

CREATE TABLE order_items (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    subtotal   REAL NOT NULL CHECK (subtotal >= 0)
);
"""

# 仅建立能明确服务于常见查询的基础索引
INDEX_DDL = """
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_products_category_id ON products(category_id);
"""


def create_db() -> sqlite3.Connection:
    """删除旧库，创建新库并建表。"""
    if DB_PATH.exists():
        DB_PATH.unlink()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_DDL)
    return conn


def insert_data(conn: sqlite3.Connection) -> dict[str, int]:
    """生成数据并写入，返回各表实际行数。"""
    data = generate_data.generate_all()
    counts = {}
    for table in ("categories", "products", "users", "orders", "order_items"):
        rows = data[table]
        conn.executemany(
            f"INSERT INTO {table} VALUES ({', '.join(['?'] * len(rows[0]))})",
            [tuple(row.values()) for row in rows],
        )
        counts[table] = len(rows)
    conn.commit()
    return counts


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(INDEX_DDL)
    conn.commit()


# ---------- 基本验证 ----------

# 统一销售统计口径：实际销量/销售额类指标默认排除 cancelled 订单
BUSINESS_SQL = {
    "订单总数": "SELECT COUNT(*) FROM orders;",
    "订单总销售额(SUM(total_amount), 排除取消订单)": (
        "SELECT ROUND(SUM(total_amount), 2) FROM orders "
        "WHERE status != 'cancelled';"
    ),
    "商品销量 Top 5(排除取消订单)": (
        "SELECT p.name, SUM(oi.quantity) AS sold "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY p.id ORDER BY sold DESC LIMIT 5;"
    ),
    "分类销售额 Top 5(排除取消订单)": (
        "SELECT c.name, ROUND(SUM(oi.subtotal), 2) AS revenue "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN categories c ON c.id = p.category_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY c.id ORDER BY revenue DESC LIMIT 5;"
    ),
    "月度销售趋势(排除取消订单)": (
        "SELECT strftime('%Y-%m', order_date) AS ym, COUNT(*) AS orders, "
        "ROUND(SUM(total_amount), 2) AS revenue "
        "FROM orders WHERE status != 'cancelled' GROUP BY ym ORDER BY ym;"
    ),
    "本月(2026-09)销售额(排除取消订单)": (
        "SELECT ROUND(SUM(total_amount), 2) FROM orders "
        "WHERE status != 'cancelled' AND order_date >= '2026-09-01';"
    ),
}


def validate(conn: sqlite3.Connection) -> None:
    """执行基本验证：数据量、业务 SQL、金额语义一致性。"""
    print("=" * 60)
    print("基本验证")

    print("\n[数据量]")
    for table in ("categories", "products", "users", "orders", "order_items"):
        (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  {table}: {count}")

    print("\n[业务 SQL 实际执行结果]")
    for name, sql in BUSINESS_SQL.items():
        rows = conn.execute(sql).fetchall()
        print(f"  {name}:")
        if "月度销售趋势" in name:
            print(f"    共 {len(rows)} 个月份，前 3 个月与后 3 个月：")
            for row in rows[:3] + rows[-3:]:
                print(f"      {row[0]}  订单 {row[1]}  销售额 {row[2]}")
        else:
            for row in rows[:5]:
                print(f"    {row}")

    print("\n[金额语义验证]")
    check_amount_semantics(conn)


def check_amount_semantics(conn: sqlite3.Connection) -> None:
    """验证 subtotal 口径与 total_amount 口径的一致性规则。"""
    sql = """
        SELECT o.id, o.status, o.total_amount, o.discount_amount, o.shipping_fee,
               ROUND(COALESCE(SUM(oi.subtotal), 0), 2) AS sub_sum
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.id
        GROUP BY o.id
        ORDER BY o.id
    """
    rows = conn.execute(sql).fetchall()

    # 规则：取消订单 total=0；其余订单 total = 明细合计 − 优惠 + 运费
    violation_count = 0
    cancelled_bad = 0
    diff_orders = []  # total 与明细合计存在差异的订单样例
    for order_id, status, total, discount, shipping, sub_sum in rows:
        if status == "cancelled":
            if abs(total) > 0.001 or discount != 0 or shipping != 0:
                cancelled_bad += 1
            continue
        expected = round(sub_sum - discount + shipping, 2)
        if abs(total - expected) > 0.011:
            violation_count += 1
        if abs(sub_sum - total) > 0.001 and len(diff_orders) < 5:
            diff_orders.append((order_id, sub_sum, discount, shipping, total))

    print(f"  订单总数: {len(rows)}")
    print(f"  total_amount 与「明细合计-优惠+运费」不一致的订单数: {violation_count}")
    print(f"  取消订单金额异常数: {cancelled_bad}")
    print(f"  total_amount 与明细合计存在业务差异的订单样例:")
    for oid, sub_sum, discount, shipping, total in diff_orders:
        print(f"    订单 {oid}: 明细合计 {sub_sum}, 优惠 {discount}, "
              f"运费 {shipping}, 实付 {total}")

    if violation_count == 0 and cancelled_bad == 0:
        print("  结论: 金额口径一致，差异全部来自订单级优惠/运费，非生成错误。")
    else:
        print("  结论: 存在金额口径异常，请检查数据生成脚本！")


def main() -> None:
    print(f"数据库文件: {DB_PATH}")
    conn = create_db()
    try:
        counts = insert_data(conn)
        create_indexes(conn)
        validate(conn)
        print("=" * 60)
        print("初始化完成。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()