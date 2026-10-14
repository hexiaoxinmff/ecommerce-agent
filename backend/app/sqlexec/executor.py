"""SQL Executor：经过安全校验的只读 SQL 执行。

设计要点：
- 复用现有只读数据库层 app.db.sqlite.get_connection（mode=ro + query_only=ON），
  不创建第二套连接/路径配置；
- 执行前必须再次做 SQL Safety Validation（复用 app.sqlgen.safety），
  即使上游已校验过也不信任（最后一道安全边界）；
- 执行前额外做 SQL Scope Validation（Task 37）：发现未定义表别名 / 列限定符
  时，在**打开数据库连接之前**以 SQLExecutionScopeError 拒绝，避免把
  必然失败的 SQL 送进数据库；
- 使用 fetchmany(MAX_RESULT_ROWS + 1) 判断截断，不把全部结果加载进内存，
  也不为精确总数二次执行 SQL；
- execution_time_ms 只统计 cursor.execute + fetch，不含任何 Mimo 时间；
- 单条 SELECT / WITH（含 UNION）只读执行；写操作 / 多语句 / PRAGMA
  一律在进入数据库前拒绝。

独立职责：本模块不依赖 SQLGenerator / SchemaLinking / LLMProvider。
"""

import sqlite3
import time
from contextlib import closing
from typing import Callable

from app.db.sqlite import get_connection
from app.sqlcheck.scope_validator import check_sql_scope
from app.sqlgen.errors import SQLUnsafeError
from app.sqlgen.safety import check_sql_safety
from app.sqlexec.errors import (
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
    SQLExecutionScopeError,
)
from app.sqlexec.models import SQLExecutionResult

# 结果集保护上限（集中配置，不散落写死在多处）
MAX_RESULT_ROWS = 500


def execute(
    sql: str,
    *,
    connection_factory: Callable[[], sqlite3.Connection] | None = None,
) -> SQLExecutionResult:
    """安全执行只读 SQL，返回结构化结果。

    Phase 13（跨数据库适配）：connection_factory 可指定只读连接来源
    （默认 app.db.sqlite.get_connection，即默认业务库），行为不变。

    Raises:
        SQLExecutionSafetyError: 安全/结构校验未通过（不会执行）。
        SQLExecutionScopeError: 存在未定义表别名 / 列限定符（不会执行）。
        SQLExecutionDatabaseError: 数据库执行失败。
    """
    get_conn = connection_factory or get_connection
    # 1. 执行前安全校验（最后一道防线）
    try:
        check_sql_safety(sql)
    except SQLUnsafeError as exc:
        raise SQLExecutionSafetyError(str(exc)) from exc

    # 2. 执行前 Scope 校验（Task 37 / E-0099）
    #    早于任何数据库连接建立；错误信息对 Repair 更可操作。
    scope_result = check_sql_scope(sql)
    if not scope_result.ok:
        raise SQLExecutionScopeError(
            "SQL 引用了未定义的表别名: " + ", ".join(scope_result.messages)
        )

    # 3. 通过现有只读连接执行（mode=ro + query_only=ON 双重保护）
    start = time.perf_counter()
    try:
        with closing(get_conn()) as conn:
            cursor = conn.execute(sql)
            columns = [description[0] for description in (cursor.description or [])]
            raw_rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
    except sqlite3.Error as exc:
        raise SQLExecutionDatabaseError(f"SQL 执行失败: {exc}") from exc
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # 4. 截断保护：保留前 MAX_RESULT_ROWS 行，row_count = 返回行数
    truncated = len(raw_rows) > MAX_RESULT_ROWS
    rows = [list(row) for row in raw_rows[:MAX_RESULT_ROWS]]

    return SQLExecutionResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        execution_time_ms=round(elapsed_ms, 4),
    )