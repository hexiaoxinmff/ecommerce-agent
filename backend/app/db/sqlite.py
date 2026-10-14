"""SQLite 只读访问层。

设计上即为只读，双重保障：
1. 连接统一使用 SQLite URI `mode=ro`（文件级只读）；
2. 附加 `PRAGMA query_only = ON`（会话级只读）。

本层不提供任何写方法。通过本层获得的连接执行
INSERT / UPDATE / DELETE / DROP / ALTER / CREATE / REPLACE 等写入语句，
会被 SQLite 直接以 OperationalError 拒绝。

用法：
    conn = get_connection()   # 每次调用返回一条独立只读连接
    try:
        row = conn.execute("SELECT ...").fetchone()
    finally:
        conn.close()          # 调用方负责关闭，不允许连接泄漏

不做连接池：当前项目只有一个本地 SQLite 文件，每次请求独立连接即可。
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

from app.core import config

# 5 张核心业务表
TABLE_NAMES: Final[tuple[str, ...]] = (
    "users",
    "categories",
    "products",
    "orders",
    "order_items",
)


class DatabaseError(Exception):
    """SQLite 访问层异常基类。"""


class DatabaseNotFoundError(DatabaseError):
    """数据库文件不存在。"""


class DatabaseConnectionError(DatabaseError):
    """数据库文件存在但无法以只读方式打开。"""


def _readonly_uri(path: Path) -> str:
    """构造 SQLite URI 只读连接串（跨平台，兼容 Windows 盘符路径）。"""
    # 对空格与百分号做 URI 百分号编码，避免路径解析歧义
    uri_path = path.resolve().as_posix().replace("%", "%25").replace(" ", "%20")
    return f"file:{uri_path}?mode=ro"


def get_connection_for(db_path: Path) -> sqlite3.Connection:
    """获取指向指定数据库文件的一条独立只读连接，调用方负责关闭。

    Phase 13（跨数据库适配）：把「连接哪个库」参数化，
    get_connection() 等价于 get_connection_for(config.DB_PATH)。

    Raises:
        DatabaseNotFoundError: 数据库文件不存在。
        DatabaseConnectionError: 数据库文件存在但无法以只读方式打开。
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise DatabaseNotFoundError(
            f"数据库文件不存在: {db_path}（请先运行 scripts/init_db.py 生成数据库）"
        )
    try:
        conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    except sqlite3.Error as exc:
        raise DatabaseConnectionError(
            f"无法以只读方式打开数据库: {db_path}"
        ) from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_connection() -> sqlite3.Connection:
    """获取默认业务库（config.DB_PATH）的一条独立只读连接，调用方负责关闭。

    Raises:
        DatabaseNotFoundError: 数据库文件不存在。
        DatabaseConnectionError: 数据库文件存在但无法以只读方式打开。
    """
    return get_connection_for(config.DB_PATH)


def is_database_readable() -> bool:
    """轻量探活：数据库能否打开并执行 SELECT 1。"""
    try:
        conn = get_connection()
    except DatabaseError:
        return False
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def get_database_info() -> dict[str, str | int]:
    """读取数据库名称、表数量与 5 张业务表行数（全部来自真实查询）。"""
    with closing(get_connection()) as conn:
        (table_count,) = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()
        counts: dict[str, int] = {}
        for table in TABLE_NAMES:
            (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = count
    return {
        "database": Path(config.DB_PATH).name,
        "tables": table_count,
        **counts,
    }