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


class SQLExecutionScopeError(SQLExecutionDatabaseError):
    """执行前静态检查发现的未定义表别名 / 列限定符（Task 37 / E-0099）。

    刻意继承 SQLExecutionDatabaseError 而非 SQLExecutionSafetyError：
    - 这类错误在语义上**等同于**数据库会报的 `no such column: q.col`，
      只是被提前到执行之前发现，因此归入「数据库阶段」故障域；
    - 继承 DatabaseError 保证既有路由行为不变 —— route_after_execute
      仍会在 repair_count==0 时触发一次 Repair，不会因为新增校验而
      静默缩短 execute-with-repair 流程；
    - 若继承 SafetyError，SQL 会被直接判死、永不进入 Repair，属于对
      既有行为的隐性破坏，本任务明确禁止。
    """