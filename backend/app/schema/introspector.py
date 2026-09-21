"""从真实 SQLite 数据库读取 Schema 结构。

表名、字段名、字段类型、约束全部来自真实数据库（sqlite_master /
PRAGMA table_info / PRAGMA foreign_key_list），业务描述保存在代码中
（metadata.py）。禁止在代码内硬编码整套表结构作为唯一来源。
"""

import sqlite3
from contextlib import closing
from typing import Any

from app.db.sqlite import TABLE_NAMES, get_connection

# 期望的业务表（顺序即展示顺序）；实际以数据库为准，缺失的表不会出现
_BUSINESS_TABLE_NAMES = set(TABLE_NAMES)


def introspect_table_names() -> tuple[str, ...]:
    """读取真实业务表名（按 TABLE_NAMES 顺序返回，忽略 sqlite_ 系统表）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    present = {row[0] for row in rows}
    return tuple(name for name in TABLE_NAMES if name in present)


def introspect_columns(table: str) -> list[dict[str, Any]]:
    """读取真实表字段结构（cid, name, type, not_null, default, pk）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        {
            "name": row[1],
            "type": row[2] or "",
            "not_null": bool(row[3]),
            "primary_key": bool(row[5]),
        }
        for row in rows
    ]


def introspect_foreign_keys(table: str) -> list[dict[str, Any]]:
    """读取真实表的外键约束（PRAGMA foreign_key_list）。

    返回值每项包含 from_column / to_table / to_column，全部来自数据库，
    不做任何推断、补全或去重。

    说明：
    - SQLite 在未显式写出引用列（隐含引用父表主键）时 `to` 列为 NULL，
      此时 to_column 归一化为空字符串；
    - PRAGMA 的返回顺序与建表声明顺序相反，故按
      (from_column, to_table, to_column) 排序，保证同一数据库的输出稳定。
    """
    with closing(get_connection()) as conn:
        rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    foreign_keys = [
        {
            "from_column": row[3],
            "to_table": row[2],
            "to_column": row[4] or "",
        }
        for row in rows
    ]
    return sorted(
        foreign_keys,
        key=lambda fk: (fk["from_column"], fk["to_table"], fk["to_column"]),
    )


def schema_is_readable() -> bool:
    """Schema 内省是否可用的轻量探活。"""
    try:
        introspect_table_names()
        return True
    except Exception:
        return False