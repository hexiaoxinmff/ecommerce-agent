"""重排序模块：在向量检索召回的候选集上做语义重排，提升 RAG 精度。

典型链路：query -> Embedding 召回 top-K 候选 -> Reranker 语义重排 -> 取 top-N 送生成。

- 有 Key（真实模式）：调用 LLM 一次性对候选片段排序（LLM-as-Reranker），
  把与问题最相关的片段排到前面，显著缓解“召回了但不相关”的噪声问题。
- 无 Key（演示模式）：用字面词重叠 + 原始相似度加权做规则兜底，保证零成本可演示。
"""
import re

from config import settings
from src.agent import llm as llm_mod
from langchain_core.messages import HumanMessage, SystemMessage


def rerank(query: str, results: list, top_n: int = None) -> list:
    """对检索结果 results 重排序，返回前 top_n 个（保留原 dict 结构）。

    results 每个元素形如 {"text":..., "meta":..., "score":...}
    """
    if not results:
        return []
    top_n = top_n or settings.RERANK_TOP_N
    if len(results) <= top_n:
        return results
    if settings.MOCK_MODE:
        return _rule_rerank(query, results)[:top_n]
    return _llm_rerank(query, results, top_n)


def _rule_rerank(query: str, results: list) -> list:
    """无 Key 兜底：字面词重叠 + 原始相似度加权。"""
    q_tokens = set(query)
    scored = []
    for i, r in enumerate(results):
        overlap = len(q_tokens & set(r["text"]))
        score = overlap + 0.1 * r.get("score", 0.0)
        scored.append((score, i))
    scored.sort(key=lambda x: -x[0])
    return [results[i] for _, i in scored]


def _llm_rerank(query: str, results: list, top_n: int) -> list:
    """有 Key 模式：让 LLM 对候选片段做一次相关性排序。"""
    numbered = "\n".join(f"{i + 1}. {r['text'][:300]}" for i, r in enumerate(results))
    prompt = (
        "你是检索结果相关性排序器。给定用户问题，对候选文档片段按与问题的语义相关性"
        "从高到低排序，仅输出候选编号（1-based）的逗号分隔序列，不要任何解释。\n\n"
        f"用户问题：{query}\n\n候选片段：\n{numbered}\n\n排序（相关性高→低）："
    )
    try:
        resp = llm_mod.get_llm(temperature=0, timeout=45).invoke(
            [
                SystemMessage(content="只输出编号序列，例如 3,1,4,2。"),
                HumanMessage(content=prompt),
            ]
        )
        order = _parse_order(resp.content, len(results))
        if order:
            ranked = [results[i] for i in order if 0 <= i < len(results)]
            seen = set(order)
            ranked += [r for i, r in enumerate(results) if i not in seen]
            return ranked[:top_n]
    except Exception:
        pass
    return results[:top_n]


def _parse_order(text: str, n: int) -> list:
    """从 LLM 返回里解析出候选编号序列（去重、越界过滤）。"""
    nums = re.findall(r"\d+", text or "")
    out = []
    for x in nums:
        v = int(x) - 1
        if 0 <= v < n and v not in out:
            out.append(v)
    return out
