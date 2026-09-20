"""SQL Executor 真实验证脚本（不进入默认 pytest，不调用 Mimo）。

用法（在项目根目录）：
    python scripts/test_sql_executor.py

直接使用真实 SQLite 只读数据库执行只读 SQL，输出结构化结果
（columns / rows / row_count / truncated / execution_time_ms）。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.sqlexec import executor as executor_module  # noqa: E402

QUERIES = [
    (
        "用户按地区分布",
        "SELECT region, COUNT(*) AS user_count FROM users "
        "GROUP BY region ORDER BY user_count DESC",
    ),
    (
        "商品销售额 Top 5（排除取消订单）",
        "SELECT p.name AS product_name, ROUND(SUM(oi.subtotal), 2) AS total_sales "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY p.id ORDER BY total_sales DESC LIMIT 5",
    ),
    (
        "NULL 值处理验证",
        "SELECT NULL AS value",
    ),
]


def main() -> int:
    print("=" * 70)
    print("SQL Executor 真实验证（SQLite 只读，不调用 Mimo）")
    print(f"MAX_RESULT_ROWS = {executor_module.MAX_RESULT_ROWS}")
    print("=" * 70)

    all_ok = True
    for label, sql in QUERIES:
        print("-" * 70)
        print(f"Query ({label}): {sql}")
        try:
            result = executor_module.execute(sql)
            print(f"columns: {result.columns}")
            print(f"rows: {json.dumps(result.rows[:5], ensure_ascii=False)}"
                  f"{'  ...(前5行)' if len(result.rows) > 5 else ''}")
            print(f"row_count: {result.row_count}")
            print(f"truncated: {result.truncated}")
            print(f"execution_time_ms: {result.execution_time_ms}")
        except Exception as exc:
            print(f"执行失败：{type(exc).__name__}: {exc}")
            all_ok = False

    print("=" * 70)
    print(f"SQL Executor 真实验证：{'成功' if all_ok else '存在失败'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())