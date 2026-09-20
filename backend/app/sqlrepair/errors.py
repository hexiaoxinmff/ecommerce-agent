"""SQL Repair 异常体系。

Repair 只针对「数据库执行阶段」的错误；Safety 阶段被拒绝的 SQL
绝不进入 Repair。所有校验失败明确报错，禁止 fake success。
"""


class SQLRepairError(Exception):
    """SQL Repair 层异常基类。"""


class SQLRepairOutputInvalidError(SQLRepairError):
    """Repair LLM 输出无法解析或结构非法（非 JSON / 缺字段）。"""


class SQLRepairSafetyError(SQLRepairError):
    """Repair 出的 SQL 未通过 Safety 二次校验（写操作/多语句等），不会执行。"""


class SQLRepairSchemaError(SQLRepairError):
    """Repair 出的 SQL 引用了 Schema Linking 之外的表/字段。"""