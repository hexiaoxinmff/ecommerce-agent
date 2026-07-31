"""RAG 检索质量评测：构造（问题 -> 期望章节）标注集，
计算 Recall@k 与 MRR，量化向量检索效果。

同时对比「纯向量召回 top-N」与「向量召回候选 -> Reranker 重排 top-N」两套管线，
直观体现 Reranker 对送入生成片段质量的提升。

运行：python -m src.eval.evaluate
"""
import json
from pathlib import Path

from config import settings
from src.rag import retrieve as rag_retrieve
from src.rag import reranker as rag_rerank

# (用户问题, 期望命中章节标题)
TEST_SET = [
    ("云栖 X1 手机的电池容量和快充是多少", "云栖 X1 智能手机"),
    ("Buds Pro 耳机降噪深度多少", "云栖 Buds Pro 主动降噪耳机"),
    ("Watch 2 智能手表续航几天", "云栖 Watch 2 智能手表"),
    ("Pad Air 平板电脑屏幕规格", "云栖 Pad Air 平板电脑"),
    ("七天无理由退货需要满足什么条件", "七天无理由退货"),
    ("质量问题怎么申请换货", "质量问题退换货"),
    ("退款一般多久到账", "退款时效"),
    ("怎么修改收货地址", "如何修改收货地址"),
    ("支持开增值税专用发票吗", "发票怎么开"),
    ("优惠券怎么使用", "优惠券如何使用"),
    ("订单满多少包邮", "运费规则"),
    ("下单后降价了能申请价保吗", "价格保护"),
    ("怎么查询我的物流", "如何查询物流"),
    ("会员有什么权益和等级", "会员权益"),
]


def _recall_metrics(results_list, expected_title_set, k_list):
    """results_list: 每个 query 对应的有序候选列表（已按使用顺序排好）。
    返回 recall@k 与 MRR。"""
    n = len(results_list)
    per_query = []
    for q, res in results_list:
        hits = [i for i, r in enumerate(res) if r["meta"]["title"] in expected_title_set]
        rank = hits[0] if hits else None
        per_query.append({"query": q, "rank": rank, "hit": rank is not None})
    recall = {
        k: sum(1 for p in per_query if p["rank"] is not None and p["rank"] < k) / n
        for k in k_list
    }
    mrr = sum(1 / (p["rank"] + 1) for p in per_query if p["rank"] is not None) / n
    return {"recall": recall, "mrr": mrr, "per_query": per_query}


def evaluate(k_list=(1, 3, 5)):
    baseline_list = []   # 纯向量召回 top-N（无 Reranker）
    reranked_list = []    # 向量召回候选 -> Reranker 重排 top-N

    for q, exp_title in TEST_SET:
        # 基线：直接用向量召回 top-N（RETRIEVE_TOP_K）
        base = rag_retrieve.retrieve(q, k=settings.RERANK_TOP_N)
        baseline_list.append((q, base))

        # 新管线：向量多召回候选 -> Reranker 语义重排 -> 取 top-N
        cands = rag_retrieve.retrieve(q, k=settings.RERANK_CANDIDATES)
        reranked = rag_rerank.rerank(q, cands, top_n=settings.RERANK_TOP_N)
        reranked_list.append((q, reranked))

    exp_set = {t for _, t in TEST_SET}
    base_out = _recall_metrics(baseline_list, exp_set, k_list)
    rerank_out = _recall_metrics(reranked_list, exp_set, k_list)

    improved = [
        p for p, rb in zip(rerank_out["per_query"], base_out["per_query"])
        if (p["rank"] is not None and (rb["rank"] is None or p["rank"] < rb["rank"]))
    ]
    return {
        "n": len(TEST_SET),
        "baseline": base_out,
        "reranked": rerank_out,
        "improved": improved,
    }


def _main():
    out = evaluate()
    print(f"测试集大小: {out['n']}")
    print("\n指标                      纯向量召回        +Reranker 重排")
    ks = sorted(out["baseline"]["recall"].keys())
    for k in ks:
        b = out["baseline"]["recall"][k]
        r = out["reranked"]["recall"][k]
        print(f"  Recall@{k:<2}: {b:14.2%}   {r:14.2%}")
    print(f"  {'MRR':<22}{out['baseline']['mrr']:14.3f}   {out['reranked']['mrr']:14.3f}")

    if out["improved"]:
        print(f"\nReranker 提升的查询（{len(out['improved'])} 条）：")
        for p in out["improved"]:
            print(f"  - {p['query']}   rank={p['rank'] + 1}")
    else:
        print("\n两套管线在该测试集上召回表现一致。")

    Path(settings.DATA_DIR / "generated").mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / "generated" / "eval_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("\n结果已保存至 data/generated/eval_results.json")


if __name__ == "__main__":
    _main()
