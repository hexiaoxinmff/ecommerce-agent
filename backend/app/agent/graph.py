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
    """生产默认组件（真实模块；provider 为当前默认 Provider）。

    Phase 15（P0-1/P0-2）：默认组件与 Profile 组件共享同一运行时附录
    （KPI 口径定义 + 数据时效契约）——生产 API 与实验路径行为一致；
    附录为空（库不可读降级）时 Prompt 与冻结基线逐字节一致。
    """
    from app.dbprofile.time_anchor import default_kpi_rules, default_prompt_appendix

    appendix = default_prompt_appendix()
    kpi_rules = default_kpi_rules()
    provider = get_llm_provider()
    schema_linker = SchemaLinker(provider=provider, appendix_rules=kpi_rules)
    fewshot_retriever = FewShotRetriever()
    sql_generator = SQLGenerator(
        provider=provider,
        schema_linker=schema_linker,
        fewshot_retriever=fewshot_retriever,
        appendix_rules=appendix,
    )
    sql_repairer = SQLRepairer(
        provider=provider, fewshot_retriever=fewshot_retriever, appendix_rules=appendix
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


# 进程级默认图缓存。
# 背景（Task 29 Phase 1 实测）：build_agent() 每次编译约 29 ms，
# 而图结构是静态的（节点与边不随请求变化），无需每请求重编译。
#
# 缓存以「构建函数的身份」为键：一旦 build_agent 被替换（如测试通过
# monkeypatch 注入 fake 组件图），缓存自动失效并重建。
# 这样既拿到生产路径的复用收益，又完全保留测试的可注入性与隔离性。
_DEFAULT_GRAPH_CACHE: tuple[Any, Any] | None = None  # (build_agent_fn, graph)


def get_default_graph() -> Any:
    """返回进程级复用的默认 Agent 图（首次调用时编译）。"""
    global _DEFAULT_GRAPH_CACHE
    builder = build_agent  # 读取模块全局，尊重 monkeypatch
    if _DEFAULT_GRAPH_CACHE is None or _DEFAULT_GRAPH_CACHE[0] is not builder:
        _DEFAULT_GRAPH_CACHE = (builder, builder())
    return _DEFAULT_GRAPH_CACHE[1]


def clear_default_graph_cache() -> None:
    """清空默认图缓存（测试或组件/配置变更后调用）。"""
    global _DEFAULT_GRAPH_CACHE
    _DEFAULT_GRAPH_CACHE = None


def run_agent(
    question: str,
    components: AgentComponents | None = None,
) -> AgentResult:
    """编排一次完整 Text2SQL 分析（含 ≤1 次 Repair），返回结构化结果与 Trace。

    total_time_ms 为整个 Graph Run 的总耗时（不是单个 Node）。

    components 为 None 时复用进程级默认图（避免每请求重编译）；
    显式传入 components 时按需构建，保证测试注入语义不变。
    """
    graph = build_agent(components) if components is not None else get_default_graph()
    start = time.perf_counter()
    final_state = graph.invoke({"question": question})
    total_ms = round((time.perf_counter() - start) * 1000.0, 2)

    data = build_agent_result(final_state)
    data["total_time_ms"] = total_ms
    return AgentResult(**data)