"""SQL Generator 异常体系。

所有校验失败（非法 JSON / 非法表字段 / SQL 不安全 / 多语句 / 表不一致）
一律抛出对应异常并明确失败，禁止静默降级或 fake success。
"""


class SQLGeneratorError(Exception):
    """SQL Generator 层异常基类。"""


class SQLGenOutputInvalidError(SQLGeneratorError):
    """LLM 输出无法解析或结构非法（非 JSON / 缺字段 / 类型错误）。"""


class SQLGenSchemaMismatchError(SQLGeneratorError):
    """返回的 tables / columns 超出 Schema Linking 提供的范围或字段不存在。"""


class SQLUnsafeError(SQLGeneratorError):
    """SQL 安全/结构校验未通过（无法解析 / 多语句 / 写操作 / 非 SELECT / PRAGMA）。"""


class SQLTableMismatchError(SQLGeneratorError):
    """SQL 引用的表不在 Schema Linking 提供的表内。"""