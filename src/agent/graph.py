"""LangGraph 状态图：意图分类 -> 检索 -> (订单工具) -> 生成。

状态流转：
  START -> classify -> retrieve ->[条件]-> order -> generate -> END
                                  └─> generate -> END
"""
import re
from typing import Annotated, List, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from config import settings
from src.agent import llm as llm_mod, prompts
from src.agent.tools import lookup_order
from src.rag import retrieve as rag_retrieve
from src.rag import reranker as rag_rerank

INTENTS = ["售前咨询", "售后问题", "物流订单", "投诉建议", "闲聊"]


class AgentState(TypedDict):
    messages: Annotated[List, add_messages]
    query: str
    intent: str
    context: List[dict]
    sources: List[dict]
    order_info: dict
    answer: str


# ---------------------- 节点 ----------------------
def _classify_mock(query: str) -> str:
    if any(k in query for k in ["物流", "快递", "发货", "签收", "运单", "订单", "改地址"]):
        return "物流订单"
    if any(k in query for k in ["退货", "换货", "退款", "保修", "维修", "质量", "坏了", "碎"]):
        return "售后问题"
    if any(k in query for k in ["投诉", "差评", "举报", "建议", "不满"]):
        return "投诉建议"
    if any(k in query for k in ["你好", "您好", "在吗", "谢谢", "你是", "哈哈"]):
        return "闲聊"
    return "售前咨询"


def classify_node(state: AgentState) -> dict:
    query = state["query"]
    if settings.MOCK_MODE:
        intent = _classify_mock(query)
    else:
        resp = llm_mod.get_llm(temperature=0).invoke(
            [
                SystemMessage(content="你是意图分类器，只输出分类标签。"),
                HumanMessage(content=prompts.INTENT_PROMPT.format(query=query)),
            ]
        )
        text = resp.content.strip()
        intent = next((i for i in INTENTS if i in text), "售前咨询")
    return {"intent": intent}


def retrieve_node(state: AgentState) -> dict:
    # 1) 向量检索多召回一批候选
    results = rag_retrieve.retrieve(state["query"], k=settings.RERANK_CANDIDATES)
    # 2) Reranker 语义重排，精选最相关的片段送生成
    ranked = rag_rerank.rerank(state["query"], results, top_n=settings.RERANK_TOP_N)
    context = [r["text"] for r in ranked]
    sources = [
        {"title": r["meta"]["title"], "source": r["meta"]["source"]} for r in ranked
    ]
    return {"context": context, "sources": sources}


def order_node(state: AgentState) -> dict:
    m = re.search(r"(YS\d{6,})", state["query"])
    order_no = m.group(1) if m else "YS20240001"
    return {"order_info": lookup_order(order_no)}


def generate_node(state: AgentState) -> dict:
    query = state["query"]
    intent = state["intent"]
    context = state.get("context", [])
    sources = state.get("sources", [])
    order_info = state.get("order_info")

    if settings.MOCK_MODE or not settings.API_KEY:
        answer = _generate_mock(query, intent, context, order_info)
    else:
        answer = _generate_llm(query, intent, context, sources, order_info)
    return {"answer": answer, "messages": [AIMessage(content=answer)]}


# ---------------------- 生成逻辑 ----------------------
def _generate_mock(query, intent, context, order_info):
    head = f"【{intent}】"
    if order_info:
        return (
            f"{head} 已为您查询到订单信息：\n"
            f"订单号：{order_info['order_no']}\n"
            f"状态：{order_info['status']}\n"
            f"物流：{order_info['logistics']}\n（以上为演示数据）"
        )
    if context:
        snippet = context[0][:180].replace("\n", " ")
        return (
            f"{head} 根据知识库内容：{snippet}……\n"
            f"如需更详细帮助，请提供订单号或联系人工客服（服务时间 9:00-22:00）。"
        )
    return f"{head} 您好，这里是云栖数码旗舰店智能客服，请问有什么可以帮您？"


def _generate_llm(query, intent, context, sources, order_info):
    ctx = (
        "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(context))
        if context
        else "（未检索到相关文档）"
    )
    order_block = f"\n订单信息：{order_info}\n" if order_info else ""
    src_note = ""
    if sources:
        src_note = "\n参考来源：" + "；".join(f"{s['title']}({s['source']})" for s in sources)
    human = HumanMessage(
        content=(
            f"用户意图：{intent}\n"
            f"检索到的知识：\n{ctx}{order_block}\n"
            f"用户问题：{query}{src_note}"
        )
    )
    resp = llm_mod.get_llm(temperature=0.3).invoke(
        [SystemMessage(content=prompts.SYSTEM_PROMPT), human]
    )
    return _sanitize_identity(resp.content)


_IDENTITY_BANNED_RE = re.compile(
    r"通义千问|阿里云|Qwen|由[^，。]*(?:研发|开发|训练)|大模型|基础模型|开源模型|语言模型",
    re.IGNORECASE,
)


def _sanitize_identity(answer: str) -> str:
    """屏蔽基座模型自我认知，维持店铺客服身份。"""
    if _IDENTITY_BANNED_RE.search(answer):
        return "您好！我是云栖数码旗舰店的 AI 客服助手，专门为您解答商品、订单和售后问题。请问有什么可以帮您？"
    return answer


def _route(state: AgentState) -> str:
    return "order" if state["intent"] == "物流订单" else "generate"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", classify_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("order", order_node)
    g.add_node("generate", generate_node)
    g.add_edge(START, "classify")
    g.add_edge("classify", "retrieve")
    g.add_conditional_edges(
        "retrieve", _route, {"order": "order", "generate": "generate"}
    )
    g.add_edge("order", "generate")
    g.add_edge("generate", END)
    return g.compile()


graph = build_graph()


def run_agent(query: str) -> dict:
    result = graph.invoke(
        {"messages": [HumanMessage(content=query)], "query": query}
    )
    return {
        "answer": result["answer"],
        "intent": result["intent"],
        "sources": result.get("sources", []),
    }
