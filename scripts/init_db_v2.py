"""初始化第二公司（B 公司）SQLite 数据库（Phase 13 专用）。

流程：删除旧库 → 建表 → 插入数据 → 建立索引 → 执行口径验证。

用法（在项目根目录）：
    python scripts/init_db_v2.py

⚠️ 本脚本只创建 db/ecommerce_v2.db，绝不触碰 db/ecommerce.db（v1.0 冻结
基线的业务库）。数据库文件是生成物（不入 git），
本脚本与 scripts/generate_data_v2.py 才是数据的权威来源。
"""

import sqlite3
import sys
from pathlib import Path

# 保证直接运行与从测试导入两种方式都能找到 generate_data_v2
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_data_v2  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "ecommerce_v2.db"

SCHEMA_DDL = """
CREATE TABLE members (
    id          INTEGER PRIMARY KEY,
    member_code TEXT NOT NULL UNIQUE,
    member_name TEXT NOT NULL UNIQUE,
    city        TEXT NOT NULL,
    joined_on   DATE NOT NULL,
    tier        TEXT NOT NULL CHECK (tier IN ('gold', 'silver', 'bronze')),
    is_active   INTEGER NOT NULL CHECK (is_active IN (1, 0))
);

CREATE TABLE departments (
    id        INTEGER PRIMARY KEY,
    dept_name TEXT NOT NULL UNIQUE
);

CREATE TABLE items (
    id           INTEGER PRIMARY KEY,
    item_title   TEXT NOT NULL UNIQUE,
    dept_id      INTEGER NOT NULL REFERENCES departments(id),
    list_price   REAL NOT NULL CHECK (list_price > 0),
    availability TEXT NOT NULL CHECK (availability IN ('in_stock', 'discontinued'))
);

CREATE TABLE sales_orders (
    id               INTEGER PRIMARY KEY,
    member_id        INTEGER NOT NULL REFERENCES members(id),
    placed_on        DATE NOT NULL,
    order_state      TEXT NOT NULL CHECK (order_state IN ('pending', 'paid', 'shipped', 'completed', 'voided')),
    coupon_deduction REAL NOT NULL DEFAULT 0 CHECK (coupon_deduction >= 0),
    delivery_charge  REAL NOT NULL DEFAULT 0 CHECK (delivery_charge >= 0),
    payment_due      REAL NOT NULL CHECK (payment_due >= 0)
);

CREATE TABLE order_lines (
    id             INTEGER PRIMARY KEY,
    sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    item_id        INTEGER NOT NULL REFERENCES items(id),
    qty            INTEGER NOT NULL CHECK (qty > 0),
    deal_price     REAL NOT NULL CHECK (deal_price > 0),
    line_total     REAL NOT NULL CHECK (line_total >= 0)
);
"""

# 仅建立能明确服务于常见查询的基础索引
INDEX_DDL = """
CREATE INDEX idx_sales_orders_member_id ON sales_orders(member_id);
CREATE INDEX idx_sales_orders_placed_on ON sales_orders(placed_on);
CREATE INDEX idx_sales_orders_order_state ON sales_orders(order_state);
CREATE INDEX idx_order_lines_sales_order_id ON order_lines(sales_order_id);
CREATE INDEX idx_order_lines_item_id ON order_lines(item_id);
CREATE INDEX idx_items_dept_id ON items(dept_id);
"""

TABLE_ORDER = ("departments", "items", "members", "sales_orders", "order_lines")


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
    data = generate_data_v2.generate_all()
    counts = {}
    for table in TABLE_ORDER:
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


def _validate_consistency(conn: sqlite3.Connection) -> None:
    """物化口径验证：payment_due = 明细合计 − 抵扣 + 配送费；作废订单全 0。"""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM sales_orders so
        WHERE so.order_state != 'voided'
          AND ABS(
              so.payment_due
              - ROUND(
                  (SELECT COALESCE(SUM(ol.line_total), 0)
                     FROM order_lines ol WHERE ol.sales_order_id = so.id)
                  - so.coupon_deduction + so.delivery_charge, 2)
          ) > 0.01
        """
    ).fetchone()[0]
    if row:
        raise SystemExit(f"[FATAL] payment_due 口径不一致的订单数: {row}")

    row = conn.execute(
        """
        SELECT COUNT(*) FROM sales_orders
        WHERE order_state = 'voided'
          AND (coupon_deduction != 0 OR delivery_charge != 0 OR payment_due != 0)
        """
    ).fetchone()[0]
    if row:
        raise SystemExit(f"[FATAL] 作废订单存在非零金额的行数: {row}")
    print("口径验证 PASS：payment_due 一致；voided 订单三项金额全为 0。")


def main() -> None:
    conn = create_db()
    try:
        counts = insert_data(conn)
        create_indexes(conn)
        _validate_consistency(conn)
    finally:
        conn.close()
    print(f"B 公司数据库已生成: {DB_PATH}")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
