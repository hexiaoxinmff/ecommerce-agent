"""LangGraph 节点集（依赖注入化，便于单元测试时替换组件）+ Trace 包装。

设计：
- 每个节点只改自己负责的 State 字段；
- 节点由 `_wrap` 包装：记录 TraceEvent（success/error/skipped）、
  计算 duration_ms（time.perf_counter）、生成 input/output 摘要；
- 逻辑失败（Safety / 执行 / 修复）通过 State 标志 + 条件边路由；
- Provider/LLM 等异常：包装器捕获后记录 error event 并转为失败终态
  （不 raise，保证 Trace 不丢），同时记录 http_status / error_type，
  由 API 层映射 HTTP 状态码（保持 502/503 语义）；
- 条件分支未走到的节点：由 result 节点的 finalize_events 补为 skipped。
"""

import time
from dataclasses import dataclass
from typing import Any, Callable

from app.agent.state import AgentState
from app.fewshot.models import FewShotMatch, FewShotQuery, FewShotResult
from app.llm.provider import LLMAuthenticationError, LLMError
from app.sqlgen.safety import check_sql_safety
from app.sqlrepair.errors import (
    SQLRepairError,
    SQLRepairOutputInvalidError,
    SQLRepairSafetyError,
    SQLRepairSchemaError,
)
from app.sqlrepair.models import (
    SQLRepairRequest,
    sanitize_execution_error,
)
from app.sqlexec.errors import (
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
)
from app.schemas.schema_link import SchemaLinkResult
from app.trace.recorder import (
    build_event,
    finalize_events,
)

FEWSHOT_TOP_K = 3


@dataclass
class AgentComponents:
    """Graph 依赖注入容器（测试可全部替换为 fake）。"""

    schema_linker: Any
    fewshot_retriever: Any
    sql_generator: Any
    sql_executor: Callable[[str], Any]
    sql_repairer: Any


def _http_status_for(exc: Exception) -> int | None:
    """provider 异常 -> HTTP 状态（与 /api/llm/test 语义一致）。"""
    if isinstance(exc, LLMAuthenticationError):
        return 502
    if isinstance(exc, LLMError):
        return 503
    return None


def _node_input_summary(node: str, state: AgentState) -> dict[str, Any]:
    """节点输入摘要（轻量）。"""
    question = state.get("question", "")
    if node == "schema_link":
        return {"question": question}
    if node == "fewshot_retrieve":
        return {
            "question": question,
            "schema_tables": state.get("schema_tables", []),
            "schema_columns_count": len(state.get("schema_columns", [])),
        }
    if node == "sql_generate":
        return {
            "question": question,
            "tables": len(state.get("schema_tables", [])),
            "columns": len(state.get("schema_columns", [])),
            "fewshot_count": len(state.get("fewshot_examples", [])),
        }
    if node in ("sql_safety", "sql_execute"):
        return {"sql_length": len(state.get("original_sql", state.get("generated_sql", "")))}
    if node == "sql_repair":
        return {
            "sql_length": len(state.get("original_sql", "")),
            "error_message": state.get("execution_error", ""),
        }
    if node == "sql_execute_repaired":
        return {"sql_length": len(state.get("repaired_sql", ""))}
    return {"question": question}


def _node_output_summary(node: str, out: dict[str, Any], state: AgentState) -> dict[str, Any]:
    """节点输出摘要（轻量，不保存完整 SQL / rows / 隐私数据）。"""
    if node == "schema_link":
        return {
            "tables": out.get("schema_tables", []),
            "columns_count": len(out.get("schema_columns", [])),
            "confidence": out.get("schema_confidence", 0.0),
        }
    if node == "fewshot_retrieve":
        return {
            "match_count": len(out.get("fewshot_examples", [])),
            "example_ids": [m.get("example_id") for m in out.get("fewshot_examples", [])],
        }
    if node == "sql_generate":
        return {"sql_length": len(out.get("generated_sql", "")), "tables": len(out.get("schema_tables", state.get("schema_tables", [])))}
    if node == "sql_safety":
        return {"allowed": bool(out.get("sql_safety_ok"))}
    if node in ("sql_execute", "sql_execute_repaired"):
        result = out.get("execution_result")
        if result is not None:
            return {"row_count": result.row_count, "truncated": result.truncated}
        return {"ok": bool(out.get("executed_ok")), "error": out.get("execution_error", "")}
    if node == "sql_repair":
        return {
            "repair_success": bool(out.get("repair_ok")),
            "repaired_sql_length": len(out.get("repaired_sql", "")),
            "error": out.get("repair_error", ""),
        }
    if node == "result":
        return {"success": bool(state.get("success"))}
    return {}


def make_nodes(components: AgentComponents) -> dict[str, Callable[[AgentState], dict]]:
    """构建全部节点函数（已包装 Trace）。"""

    def schema_link_node(state: AgentState) -> dict:
        link_result = components.schema_linker.link(state["question"])
        return {
            "schema_tables": link_result.tables,
            "schema_columns": link_result.columns,
            "schema_reasons": link_result.reasons,
            "schema_confidence": link_result.confidence,
        }

    def fewshot_retrieve_node(state: AgentState) -> dict:
        fs_result = components.fewshot_retriever.retrieve(
            FewShotQuery(
                question=state["question"],
                tables=state.get("schema_tables", []),
                columns=state.get("schema_columns", []),
                top_k=FEWSHOT_TOP_K,
            )
        )
        return {
            "fewshot_examples": [match.model_dump() for match in fs_result.matches]
        }

    def _restore_objects(
        state: AgentState,
    ) -> tuple[SchemaLinkResult, FewShotResult]:
        link_result = SchemaLinkResult(
            question=state["question"],
            tables=state.get("schema_tables", []),
            columns=state.get("schema_columns", []),
            reasons=state.get("schema_reasons", []),
            confidence=state.get("schema_confidence", 0.0),
        )
        fs_matches = [
            FewShotMatch(**item) for item in state.get("fewshot_examples", [])
        ]
        return link_result, FewShotResult(question=state["question"], matches=fs_matches)

    def sql_generate_node(state: AgentState) -> dict:
        link_result, fs_result = _restore_objects(state)
        gen = components.sql_generator.generate_with_context(
            state["question"], link_result, fs_result
        )
        return {"generated_sql": gen.sql, "original_sql": gen.sql}

    def sql_safety_node(state: AgentState) -> dict:
        sql = state.get("generated_sql", "")
        try:
            check_sql_safety(sql)
        except Exception as exc:
            return {
                "sql_safety_ok": False,
                "success": False,
                "final_error": f"SQL Safety Rejected: {exc}",
            }
        return {"sql_safety_ok": True}

    def sql_execute_node(state: AgentState) -> dict:
        sql = state.get("original_sql", state.get("generated_sql", ""))
        try:
            result = components.sql_executor(sql)
        except SQLExecutionSafetyError as exc:
            return {
                "executed_ok": False,
                "execute_error_kind": "safety",
                "success": False,
                "execution_error": sanitize_execution_error(str(exc)),
                "final_error": f"SQL Safety Rejected: {exc}",
            }
        except SQLExecutionDatabaseError as exc:
            return {
                "executed_ok": False,
                "execute_error_kind": "database",
                "execution_error": sanitize_execution_error(str(exc)),
                "execute_count": state.get("execute_count", 0) + 1,
            }
        return {
            "executed_ok": True,
            "execute_error_kind": "",
            "execution_result": result,
            "execute_count": state.get("execute_count", 0) + 1,
            "success": True,
        }

    def sql_repair_node(state: AgentState) -> dict:
        request = SQLRepairRequest(
            question=state["question"],
            original_sql=state.get("original_sql", state.get("generated_sql", "")),
            error_message=state.get("execution_error", ""),
            tables=state.get("schema_tables", []),
            columns=state.get("schema_columns", []),
        )
        try:
            repaired = components.sql_repairer.repair(request)
        except SQLRepairSafetyError as exc:
            return {
                "repair_ok": False,
                "repair_count": state.get("repair_count", 0) + 1,
                "repair_error": str(exc),
                "success": False,
                "final_error": f"Repair Safety Rejected: {exc}",
            }
        except (SQLRepairOutputInvalidError, SQLRepairSchemaError) as exc:
            return {
                "repair_ok": False,
                "repair_count": state.get("repair_count", 0) + 1,
                "repair_error": str(exc),
                "success": False,
                "final_error": f"SQL Repair failed: {exc}",
            }
        except SQLRepairError as exc:
            return {
                "repair_ok": False,
                "repair_count": state.get("repair_count", 0) + 1,
                "repair_error": str(exc),
                "success": False,
                "final_error": f"SQL Repair failed: {exc}",
            }
        return {
            "repair_ok": True,
            "repair_count": state.get("repair_count", 0) + 1,
            "repaired_sql": repaired.repaired_sql,
            "repair_reason": repaired.repair_reason,
        }

    def sql_execute_repaired_node(state: AgentState) -> dict:
        sql = state.get("repaired_sql", "")
        try:
            result = components.sql_executor(sql)
        except SQLExecutionDatabaseError as exc:
            return {
                "executed_ok": False,
                "execute_count": state.get("execute_count", 0) + 1,
                "execution_error": sanitize_execution_error(str(exc)),
                "success": False,
                "final_error": sanitize_execution_error(str(exc)),
            }
        except SQLExecutionSafetyError as exc:
            return {
                "executed_ok": False,
                "execute_count": state.get("execute_count", 0) + 1,
                "execution_error": sanitize_execution_error(str(exc)),
                "success": False,
                "final_error": f"SQL Safety Rejected: {exc}",
            }
        return {
            "executed_ok": True,
            "execution_result": result,
            "execute_count": state.get("execute_count", 0) + 1,
            "success": True,
        }

    raw_nodes = {
        "schema_link": schema_link_node,
        "fewshot_retrieve": fewshot_retrieve_node,
        "sql_generate": sql_generate_node,
        "sql_safety": sql_safety_node,
        "sql_execute": sql_execute_node,
        "sql_repair": sql_repair_node,
        "sql_execute_repaired": sql_execute_repaired_node,
        "result": lambda state: {},
    }

    def _wrap(node: str, fn: Callable[[AgentState], dict]) -> Callable[[AgentState], dict]:
        def wrapper(state: AgentState) -> dict:
            start = time.perf_counter()
            # 已经失败终止时，后续（固定边）节点直接记为 skipped，不再执行业务
            if state.get("success") is False and node != "result":
                return {
                    "trace": [
                        build_event(
                            node,
                            "skipped",
                            0.0,
                            message="未执行（Agent 已失败终止）",
                            input_summary=_node_input_summary(node, state),
                        )
                    ]
                }
            try:
                out = fn(state)
                if out.get("success") is not False:
                    # 失败节点的 success 为 False；无显式 success 字段视为成功
                    pass
            except Exception as exc:
                duration = (time.perf_counter() - start) * 1000.0
                message = sanitize_execution_error(str(exc))
                http_status = _http_status_for(exc)
                # LLMError 使用既定对外文案；其他异常注明类型便于诊断
                final_error = (
                    message if isinstance(exc, LLMError) else f"{type(exc).__name__}: {message}"
                )
                return {
                    "trace": [
                        build_event(
                            node,
                            "error",
                            duration,
                            message=message,
                            input_summary=_node_input_summary(node, state),
                        )
                    ],
                    "success": False,
                    "final_error": final_error,
                    "http_status": http_status,
                    "error_type": type(exc).__name__,
                }

            duration = (time.perf_counter() - start) * 1000.0
            failed = (
                out.get("success") is False
                or out.get("sql_safety_ok") is False
                or out.get("executed_ok") is False
                or out.get("repair_ok") is False
            )
            status = "error" if failed else "success"
            message = ""
            if status == "error":
                message = (
                    out.get("execution_error")
                    or out.get("repair_error")
                    or out.get("final_error")
                    or ""
                )

            if node == "result":
                # 终态：补全 missing 为 skipped，排序编号，写出 trace_final
                events = list(state.get("trace", []))
                canonical = finalize_events(events)
                canonical_event = build_event(
                    node,
                    "success",
                    duration,
                    input_summary={"question": state.get("question", "")},
                    output_summary={"success": bool(state.get("success"))},
                )
                canonical = finalize_events([*events, canonical_event])
                return {
                    "trace": [canonical_event],
                    "trace_final": [e.model_dump() for e in canonical],
                }

            return {
                **out,
                "trace": [
                    build_event(
                        node,
                        status,
                        duration,
                        message=message,
                        input_summary=_node_input_summary(node, state),
                        output_summary=_node_output_summary(node, out, state),
                    )
                ],
            }

        return wrapper

    return {name: _wrap(name, fn) for name, fn in raw_nodes.items()}


# ---------- 条件边路由 ----------


def route_after_sql_safety(state: AgentState) -> str:
    """sql_safety 失败 -> 直接终态；通过 -> sql_execute。"""
    return "execute" if state.get("sql_safety_ok") else "result"


def route_after_execute(state: AgentState) -> str:
    """执行结果路由：
    - 成功 -> result；
    - Safety 拒绝 -> result（禁止 Repair）；
    - 数据库执行错误：repair_count == 0 -> repair；否则 -> result（有界）。
    """
    if state.get("executed_ok"):
        return "result"
    if state.get("execute_error_kind") == "safety":
        return "result"
    if state.get("repair_count", 0) >= 1:
        return "result"
    return "repair"


def route_after_repair(state: AgentState) -> str:
    """Repair 通过 -> 第二次执行；被拒绝（Safety/Schema/输出非法）-> 终态。"""
    return "repaired_execute" if state.get("repair_ok") else "result"


# ---------- 结果组装 ----------


def build_agent_result(state: AgentState) -> dict:
    """把终态 State 整理为对外输出（保留全部中间证据 + Trace）。"""
    trace_events = [
        e for e in state.get("trace_final") or state.get("trace", [])
    ]
    return {
        "question": state.get("question", ""),
        "success": bool(state.get("success")),
        "generated_sql": state.get("generated_sql", ""),
        "repaired_sql": state.get("repaired_sql", ""),
        "execution_result": state.get("execution_result"),
        "execution_error": state.get("execution_error", ""),
        "repair_reason": state.get("repair_reason", ""),
        "repair_error": state.get("repair_error", ""),
        "execute_count": state.get("execute_count", 0),
        "repair_count": state.get("repair_count", 0),
        "final_error": state.get("final_error", ""),
        "trace": trace_events,
        "http_status": state.get("http_status"),
        "error_type": state.get("error_type", ""),
    }