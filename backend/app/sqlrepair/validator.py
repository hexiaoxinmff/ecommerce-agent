"""Repair 输出校验。

对 Repair LLM 输出做二次校验（不信任 Repair LLM）：
1. 剥离 ```json 围栏、解析 JSON、字段类型检查；
2. repaired_sql 必须再次通过 app.sqlgen.safety.check_sql_safety
   （安全/结构，与首次执行同一道闸）；
3. 引用表 ⊆ Schema Linking 提供的表（sqlglot 提取，CTE 名剔除）；
4. 有表前缀的列引用必须真实存在（无前缀列由第二次执行兜底）。

与 Task 5 复用同一套 safety / SchemaCatalog，不重写。
"""

import json
import re

from sqlglot import exp

from app.schema.metadata import SchemaCatalog
from app.sqlgen.errors import SQLUnsafeError
from app.sqlgen.safety import check_sql_safety, extract_referenced_tables
from app.sqlrepair.errors import (
    SQLRepairOutputInvalidError,
    SQLRepairSafetyError,
    SQLRepairSchemaError,
)
from app.sqlrepair.models import SQLRepairResult


def _extract_json(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    raise SQLRepairOutputInvalidError("Repair LLM 输出中未找到 JSON")


def _parse(raw: str) -> dict:
    try:
        data = json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        raise SQLRepairOutputInvalidError("Repair LLM 输出 JSON 解析失败") from exc
    if not isinstance(data, dict):
        raise SQLRepairOutputInvalidError("Repair LLM 输出不是 JSON 对象")
    return data


def _check_spelled_columns(statement, catalog: SchemaCatalog) -> None:
    """有表前缀的列引用（table.column）必须真实存在。"""
    for column in statement.find_all(exp.Column):
        table = column.table
        name = column.name
        if table and not catalog.has_column(table, name):
            raise SQLRepairSchemaError(f"Repair SQL 引用了不存在的字段: {table}.{name}")


def validate_repair_output(
    raw: str,
    original_sql: str,
    allowed_tables: list[str],
    catalog: SchemaCatalog,
) -> SQLRepairResult:
    """解析并校验 Repair LLM 输出。校验失败抛出对应异常。"""
    data = _parse(raw)
    repaired_sql = data.get("repaired_sql")
    repair_reason = data.get("repair_reason")

    if not isinstance(repaired_sql, str) or not repaired_sql.strip():
        raise SQLRepairOutputInvalidError("repaired_sql 必须为非空字符串")
    if not isinstance(repair_reason, str) or not repair_reason.strip():
        raise SQLRepairOutputInvalidError("repair_reason 必须为非空字符串")
    repaired_sql = repaired_sql.strip()

    # Safety 二次校验（与首次执行同一道闸）
    try:
        check_sql_safety(repaired_sql)
    except SQLUnsafeError as exc:
        raise SQLRepairSafetyError(f"Repair Safety Rejected: {exc}") from exc

    # Schema 一致性：引用表 ⊆ Schema Linking tables；列引用真实存在
    allowed = set(allowed_tables)
    referenced = extract_referenced_tables(repaired_sql)
    unexpected = referenced - allowed
    if unexpected:
        raise SQLRepairSchemaError(
            "Repair SQL 引用了 Schema Linking 未提供的表: "
            + ", ".join(sorted(unexpected))
        )
    import sqlglot

    statement = sqlglot.parse_one(repaired_sql, read="sqlite")
    _check_spelled_columns(statement, catalog)

    return SQLRepairResult(
        original_sql=original_sql,
        repaired_sql=repaired_sql,
        repair_reason=repair_reason,
    )