"""初始化应用库（db/app.db）：认证 / 会话 / 查询历史三表。

与业务库初始化（scripts/init_db.py，删除重建 ecommerce.db）完全独立：
- 绝不打开、读取、修改或删除 db/ecommerce.db，也不调用 init_db.py；
- 幂等：CREATE TABLE IF NOT EXISTS，重复执行不报错、不丢数据；
- db/ 目录不存在时自动创建。

用法（在项目根目录）：
    python scripts/init_auth_db.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core import config  # noqa: E402
from app.db.appdb import APP_TABLE_NAMES, get_connection, init_app_db  # noqa: E402

EXPECTED_TABLES = ("auth_user", "auth_session", "query_history")


def _display_path(db_path: Path) -> str:
    """优先显示相对项目根的路径，超出项目根时回退绝对路径。"""
    try:
        return db_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(db_path)


def _existing_tables() -> tuple[str, ...]:
    """读取 sqlite_master 中真实存在的应用表（不假设 DDL 成功）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return tuple(row["name"] for row in rows)


def main() -> None:
    db_path = init_app_db()
    tables = _existing_tables()

    if tables != tuple(sorted(EXPECTED_TABLES)):
        missing = sorted(set(EXPECTED_TABLES) - set(tables))
        raise SystemExit(
            f"应用库初始化校验失败：期望表 {list(EXPECTED_TABLES)}，"
            f"实际 {list(tables)}，缺失 {missing}"
        )

    print("APP DB initialized:")
    print(_display_path(db_path))
    print()
    print("Tables:")
    for table in APP_TABLE_NAMES:
        print(f"- {table}")


if __name__ == "__main__":
    main()
