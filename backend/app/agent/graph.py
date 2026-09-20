"""LangGraph 编排图：固定流程、显式状态、条件分支、有界循环。

流程：
START -> schema_link -> fewshot_retrieve -> sql_generate -> sql_safety
      -> sql_execute
         ├ 成功 / Safety拒绝 / repair已用尽 -> result -> END
         └ 数据库执行错误(repair_count==0) -> sql_repair
             ├ 被拒绝 -> result -> END
             └ 通过 -> sql_execute_repaired -> result -> END

保证：repair_count <= 1、execute_count <= 2；绝不无限循环。
"""

import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.models import AgentResult
from app.agent.nodes import (
    AgentComponents,
    build_agent_result,
    make_nodes,
    route_after_execute,
    route_after_repair,
    route_after_sql_safety,
)
from app.agent.state import AgentState
from app.fewshot.retriever import FewShotRetriever
from app.llm.provider import get_llm_provider
from app.schema.linker import SchemaLinker
from app.sqlgen.generator import SQLGenerator
from app.sqlrepair.repairer import SQLRepairer
from app.sqlexec.executor import execute as executor_execute


def default_components() -> AgentComponents:
    """生产默认组件（真实模块；provider 为当前默认 Mimo）。"""
    provider = get_llm_provider()
    schema_linker = SchemaLinker(provider=provider)
    fewshot_retriever = FewShotRetriever()
    sql_generator = SQLGenerator(
        provider=provider,
        schema_linker=schema_linker,
        fewshot_retriever=fewshot_retriever,
    )
    sql_repairer = SQLRepairer(
        provider=provider, fewshot_retriever=fewshot_retriever
    )
    return AgentComponents(
        schema_linker=schema_linker,
        fewshot_retriever=fewshot_retriever,
        sql_generator=sql_generator,
        sql_executor=executor_execute,
        sql_repairer=sql_repairer,
    )


def build_agent(components: AgentComponents | None = None) -> Any:
    """构建并编译 LangGraph（真正可 invoke）。"""
    nodes = make_nodes(components or default_components())

    builder = StateGraph(AgentState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)

    builder.add_edge(START, "schema_link")
    builder.add_edge("schema_link", "fewshot_retrieve")
    builder.add_edge("fewshot_retrieve", "sql_generate")
    builder.add_edge("sql_generate", "sql_safety")
    builder.add_conditional_edges(
        "sql_safety",
        route_after_sql_safety,
        {"execute": "sql_execute", "result": "result"},
    )
    builder.add_conditional_edges(
        "sql_execute",
        route_after_execute,
        {"result": "result", "repair": "sql_repair"},
    )
    builder.add_conditional_edges(
        "sql_repair",
        route_after_repair,
        {"result": "result", "repaired_execute": "sql_execute_repaired"},
    )
    builder.add_edge("sql_execute_repaired", "result")
    builder.add_edge("result", END)

    return builder.compile()


def run_agent(
    question: str,
    components: AgentComponents | None = None,
) -> AgentResult:
    """编排一次完整 Text2SQL 分析（含 ≤1 次 Repair），返回结构化结果与 Trace。

    total_time_ms 为整个 Graph Run 的总耗时（不是单个 Node）。
    """
    graph = build_agent(components)
    start = time.perf_counter()
    final_state = graph.invoke({"question": question})
    total_ms = round((time.perf_counter() - start) * 1000.0, 2)

    data = build_agent_result(final_state)
    data["total_time_ms"] = total_ms
    return AgentResult(**data)