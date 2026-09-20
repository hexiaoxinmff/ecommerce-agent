"""AgentState：LangGraph 显式状态。

约定：每个节点只写入自己负责的字段；不使用全局变量保存 Agent 状态。
- trace：使用 reducer `operator.add` 追加（节点返回单元素列表即可自动追加）；
- trace_final：result 节点写回的规范化/补全后的最终 Trace（覆盖语义）；
- 内部标志（sql_safety_ok / executed_ok / execute_error_kind / repair_ok）
  用于有界条件分支；http_status / error_type 供 API 层映射 provider 错误。
"""

from typing import Annotated, Any, TypedDict, operator

from app.sqlexec.models import SQLExecutionResult


class AgentState(TypedDict, total=False):
    # 输入
    question: str

    # Schema Linking
    schema_tables: list[str]
    schema_columns: list[str]
    schema_reasons: list[str]
    schema_confidence: float

    # Few-shot
    fewshot_examples: list[dict[str, Any]]

    # SQL 生成 / 修复
    generated_sql: str
    original_sql: str
    repaired_sql: str
    repair_reason: str
    repair_error: str

    # 执行
    execution_result: SQLExecutionResult | None
    execution_error: str

    # 计数
    execute_count: int
    repair_count: int

    # 内部分支标志
    sql_safety_ok: bool
    executed_ok: bool
    execute_error_kind: str  # "" | "safety" | "database"
    repair_ok: bool

    # 最终
    success: bool
    final_error: str

    # 错误分类（供 API 层映射 HTTP 状态）
    http_status: int | None
    error_type: str

    # Trace
    trace: Annotated[list[dict[str, Any]], operator.add]
    trace_final: list[dict[str, Any]]