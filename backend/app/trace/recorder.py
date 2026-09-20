"""Trace 工具：生成事件字典 / 补全 skipped / 排序编号。

Recorder 不进入 AgentState；State 只保存 trace 事件字典列表
（通过 LangGraph reducer `operator.add` 追加）。
"""

import time
from typing import Any

from app.trace.models import TraceEvent, TraceStatus

# 固定节点顺序（用于 skipped 补全与最终排序）
TRACED_NODES: tuple[str, ...] = (
    "schema_link",
    "fewshot_retrieve",
    "sql_generate",
    "sql_safety",
    "sql_execute",
    "sql_repair",
    "sql_execute_repaired",
    "result",
)

_NODE_ORDER = {name: index for index, name in enumerate(TRACED_NODES)}


def elapsed_ms(start: float) -> float:
    """perf_counter 起止耗时（毫秒，>= 0）。"""
    return max(0.0, (time.perf_counter() - start) * 1000.0)


def build_event(
    node: str,
    status: TraceStatus,
    duration_ms: float,
    *,
    message: str = "",
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 TraceEvent 字典（放入 State 的 trace 列表）。

    注意：sequence 在此为 0 占位，由 finalize_events 统一编号后再做
    TraceEvent 校验（避免中间态触发 sequence>=1 校验错误）。
    """
    return {
        "sequence": 0,
        "node": node,
        "status": status,
        "duration_ms": duration_ms,
        "message": message,
        "input_summary": input_summary or {},
        "output_summary": output_summary or {},
    }


def _skipped_message(node: str) -> str:
    """为被跳过的节点生成可解释原因。"""
    if node == "sql_execute":
        return "未执行（SQL Safety 未通过）"
    if node == "sql_execute_repaired":
        return "未执行（未进入 Repair）"
    if node == "sql_repair":
        return "未执行（无需修复）"
    return "未执行（条件分支未命中）"


def finalize_events(events: list[dict[str, Any]]) -> list[TraceEvent]:
    """补全缺失节点为 skipped，并按固定顺序排序、重新编号。

    events：已产生的节点事件（成功/失败/提前跳过）。
    返回：覆盖全部 TRACED_NODES 的规范事件列表。
    """
    seen: dict[str, dict[str, Any]] = {}
    for event in events:
        seen[event["node"]] = event

    for node in TRACED_NODES:
        if node not in seen:
            seen[node] = build_event(
                node,
                "skipped",
                0.0,
                message=_skipped_message(node),
            )

    ordered = sorted(seen.values(), key=lambda e: _NODE_ORDER[e["node"]])
    for index, event in enumerate(ordered, start=1):
        event["sequence"] = index
    return [TraceEvent(**event) for event in ordered]