"""SQL Executor 异常体系。

任何执行失败（安全校验 / 数据库异常）都转换为明确异常，
保证不绕过只读保护，且不向客户端泄漏 traceback / 路径。
"""


class SQLExecutionError(Exception):
    """SQL Executor 层异常基类。"""


class SQLExecutionSafetyError(SQLExecutionError):
    """SQL 未通过安全/结构校验（写操作 / 多语句 / 无法解析等）。

    在执行前被拒绝，绝不会进入数据库连接。
    """


class SQLExecutionDatabaseError(SQLExecutionError):
    """数据库执行异常（语法错误 / 表不存在 / 只读冲突等）。"""