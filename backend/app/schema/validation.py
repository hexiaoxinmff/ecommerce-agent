"""Schema 合法性校验。

LLM 返回的 JSON 不能直接放行，必须使用当前真实数据库 Schema 复核：
- 表必须存在；
- 字段必须为「表名.字段名」格式且存在；
- 字段所属表必须出现在 tables 中（保持自洽）；
- confidence 必须在 0~1。

校验失败一律抛出 SchemaLinkingInvalidError，禁止静默降级为假成功。
"""

from app.schema.metadata import SchemaCatalog


class SchemaLinkingError(Exception):
    """Schema Linking 层异常基类。"""


class SchemaLinkingInvalidError(SchemaLinkingError):
    """LLM 输出无法解析或未通过真实 Schema 校验。"""


def validate_schema_link(
    tables: list[str],
    columns: list[str],
    confidence: float | None,
    catalog: SchemaCatalog,
) -> tuple[list[str], list[str]]:
    """校验并规范化 LLM 输出的表与字段，返回去重后的 (tables, columns)。

    Raises:
        SchemaLinkingInvalidError: 表不存在 / 字段格式错误 / 字段不存在 /
            字段所属表不在 tables / confidence 超出 0~1。
    """
    checked_tables: list[str] = []
    for table in tables:
        if not catalog.has_table(table):
            raise SchemaLinkingInvalidError(f"表不存在: {table}")
        if table not in checked_tables:
            checked_tables.append(table)

    checked_columns: list[str] = []
    for full_name in columns:
        if not isinstance(full_name, str) or "." not in full_name:
            raise SchemaLinkingInvalidError(
                f"字段必须使用「表名.字段名」格式: {full_name}"
            )
        table, column = full_name.split(".", 1)
        if not catalog.has_table(table):
            raise SchemaLinkingInvalidError(f"字段表不存在: {full_name}")
        if not catalog.has_column(table, column):
            raise SchemaLinkingInvalidError(f"字段不存在: {full_name}")
        if table not in checked_tables:
            raise SchemaLinkingInvalidError(
                f"字段 {full_name} 所属表 {table} 不在 tables 中"
            )
        if full_name not in checked_columns:
            checked_columns.append(full_name)

    if confidence is None or not (0.0 <= confidence <= 1.0):
        raise SchemaLinkingInvalidError(f"confidence 必须在 0~1 之间: {confidence}")

    return checked_tables, checked_columns