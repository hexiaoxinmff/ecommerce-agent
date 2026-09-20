"""SQL Generator 输出校验。

对 LLM 返回结果做二次校验（任务第 9、10、19 节）：
1. SQL 不为空；
2. tables 全部属于真实 Schema 且 ⊆ Schema Linking 提供的表；
3. columns 为「表.字段」、表 ∈ Schema Linking 提供的表、字段真实存在；
4. SQL 安全/结构校验（sqlglot：单条只读 SELECT/WITH）；
5. SQL 引用的表 ⊆ Schema Linking 提供的表（基础一致性）。
"""

import json
import re

from app.schema.metadata import SchemaCatalog
from app.sqlgen.errors import (
    SQLGenOutputInvalidError,
    SQLGenSchemaMismatchError,
    SQLTableMismatchError,
    SQLUnsafeError,
)
from app.sqlgen.safety import check_sql_safety_with_tables


def extract_json(raw: str) -> str:
    """剥离开头 ```json 围栏后提取最外层 {...}。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    raise SQLGenOutputInvalidError("LLM 输出中未找到 JSON")


def parse_llm_output(raw: str) -> dict:
    extracted = extract_json(raw)
    try:
        data = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise SQLGenOutputInvalidError("LLM 输出 JSON 解析失败") from exc
    if not isinstance(data, dict):
        raise SQLGenOutputInvalidError("LLM 输出不是 JSON 对象")
    return data


def validate_output(
    data: dict, allowed_tables: list[str], catalog: SchemaCatalog
) -> dict:
    """校验并规范化 LLM 输出的 sql/tables/columns/explanation。

    Returns:
        规范化后的 dict（sql、tables、columns、explanation）。

    Raises:
        SQLGenOutputInvalidError / SQLGenSchemaMismatchError /
        SQLUnsafeError / SQLTableMismatchError。
    """
    sql = data.get("sql")
    tables = data.get("tables")
    columns = data.get("columns")
    explanation = data.get("explanation")

    if not isinstance(sql, str) or not sql.strip():
        raise SQLGenOutputInvalidError("sql 必须为非空字符串")
    sql = sql.strip()

    if not isinstance(tables, list) or not all(isinstance(t, str) for t in tables):
        raise SQLGenOutputInvalidError("tables 必须是字符串数组")
    if not isinstance(columns, list) or not all(
        isinstance(c, str) for c in columns
    ):
        raise SQLGenOutputInvalidError("columns 必须是字符串数组")
    if not isinstance(explanation, str):
        raise SQLGenOutputInvalidError("explanation 必须是字符串")

    allowed = set(allowed_tables)

    # tables：必须在真实 Schema 且属于 Schema Linking 提供的对象
    for table in tables:
        if not catalog.has_table(table):
            raise SQLGenSchemaMismatchError(f"tables 包含不存在的表: {table}")
        if table not in allowed:
            raise SQLGenSchemaMismatchError(
                f"tables 出现 Schema Linking 未提供的表: {table}"
            )

    # columns：格式「表.字段」，表属于 Schema Linking 提供的对象，字段真实存在
    for full_name in columns:
        if "." not in full_name:
            raise SQLGenSchemaMismatchError(
                f"columns 必须使用「表名.字段名」: {full_name}"
            )
        table, column = full_name.split(".", 1)
        if table not in allowed:
            raise SQLGenSchemaMismatchError(
                f"columns 出现 Schema Linking 未提供的表: {full_name}"
            )
        if not catalog.has_column(table, column):
            raise SQLGenSchemaMismatchError(f"columns 包含不存在的字段: {full_name}")

    # SQL 安全/结构校验 + 表引用一致性
    # （Task 29：单次 sqlglot 解析同时完成两项检查，避免重复解析；
    #   校验顺序与错误信息与原先完全一致）
    referenced = check_sql_safety_with_tables(sql)
    unexpected = referenced - allowed
    if unexpected:
        raise SQLTableMismatchError(
            "SQL 引用了 Schema Linking 未提供的表: " + ", ".join(sorted(unexpected))
        )
    # SQL 引用的表不在返回的 tables 中也可以接受（以 Schema Linking 为权威），
    # 但返回的 tables/columns 不能超出 Schema Linking 范围（已在上方校验）。

    return {
        "sql": sql,
        "tables": list(dict.fromkeys(tables)),
        "columns": list(dict.fromkeys(columns)),
        "explanation": explanation,
    }