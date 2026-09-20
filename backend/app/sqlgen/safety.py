"""SQL Safety Validation（结构/只读校验，不执行 SQL）。

使用 sqlglot（SQLite 方言）做静态解析，检查：
- 只能被 SQLite 方言解析；
- 必须是单条语句；
- 顶层必须是 SELECT / WITH（含 UNION 等集合查询）；
- 不得出现写操作 / DDL / PRAGMA / TRUNCATE 等节点；
- 提取 SQL 引用的表名（供 Schema 一致性检查，CTE 名称自动剔除）。
"""

import sqlglot
from sqlglot import exp

from app.sqlgen.errors import SQLUnsafeError

# 所有被禁止的"非只读"节点类型
_WRITE_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Replace,
    exp.Pragma,
)

# 允许的顶层查询类型（WITH CTE 的 SELECT 仍为 exp.Select / exp.Union）
_ALLOWED_STATEMENT_TYPES = (exp.Select, exp.Union)


def check_sql_safety(sql: str) -> None:
    """检查 SQL 是否安全（只读单条 SELECT/WITH）。

    Raises:
        SQLUnsafeError: 任一检查未通过。
    """
    if not sql or not sql.strip():
        raise SQLUnsafeError("SQL 为空")

    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except Exception as exc:
        raise SQLUnsafeError("SQL 无法被 SQLite 方言解析") from exc

    if not statements:
        raise SQLUnsafeError("SQL 内容无效")
    if len(statements) != 1:
        raise SQLUnsafeError("只允许单条 SQL 语句")

    statement = statements[0]
    if not isinstance(statement, _ALLOWED_STATEMENT_TYPES):
        raise SQLUnsafeError("只允许 SELECT / WITH 查询")

    forbidden = []
    for node_type in _WRITE_NODE_TYPES:
        forbidden.extend(statement.find_all(node_type))
    if forbidden:
        keywords = sorted({node.key for node in forbidden})
        raise SQLUnsafeError(f"SQL 包含被禁止的写操作/DDL/PRAGMA: {', '.join(keywords)}")


def extract_referenced_tables(sql: str) -> set[str]:
    """提取 SQL 引用的真实表名（剔除 CTE 名称，TO 名）。

    Raises:
        SQLUnsafeError: SQL 无法解析（应由 check_sql_safety 先行保证）。
    """
    try:
        statement = sqlglot.parse_one(sql, read="sqlite")
    except Exception as exc:
        raise SQLUnsafeError("SQL 无法被 SQLite 方言解析") from exc

    cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
    tables = {
        table.name
        for table in statement.find_all(exp.Table)
        if table.name not in cte_names
    }
    return tables