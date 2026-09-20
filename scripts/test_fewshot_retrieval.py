"""Few-shot 检索真实验证脚本（不进入默认 pytest，不调用 Mimo）。

用法（在项目根目录）：
    python scripts/test_fewshot_retrieval.py

直接使用真实 SQLite Schema + Few-shot Dataset + 规则型 Retriever。
输出：Question / Top-K / Example ID / Score / Scenario。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.fewshot.dataset import get_dataset  # noqa: E402
from app.fewshot.models import FewShotQuery  # noqa: E402
from app.fewshot.retriever import FewShotRetriever  # noqa: E402

# (问题, Schema Linking 结果中的 tables / columns, scenario 可选)
CASES = [
    (
        "近30天销售额最高的商品有哪些？",
        ["orders", "order_items", "products"],
        [
            "orders.order_date",
            "orders.status",
            "order_items.product_id",
            "order_items.subtotal",
            "products.id",
            "products.name",
        ],
        "product_sales_ranking",
    ),
    (
        "哪个地区的用户最多？",
        ["users"],
        ["users.region"],
        None,
    ),
    (
        "哪个商品类别销售额最高？",
        ["orders", "order_items", "products", "categories"],
        [
            "orders.status",
            "order_items.subtotal",
            "products.category_id",
            "categories.id",
            "categories.name",
        ],
        "category_sales_ranking",
    ),
]

TOP_K = 3


def main() -> int:
    retriever = FewShotRetriever(dataset=get_dataset())
    print(f"Few-shot 数据集规模：{len(get_dataset())} 条（纯本地规则检索，不调用 Mimo）")
    print("=" * 70)
    for question, tables, columns, scenario in CASES:
        print(f"Question: {question}")
        print(f"  Schema: tables={tables}")
        result = retriever.retrieve(
            FewShotQuery(
                question=question,
                tables=tables,
                columns=columns,
                scenario=scenario,
                top_k=TOP_K,
            )
        )
        print(f"  Top-K: {min(TOP_K, len(result.matches))}")
        for match in result.matches:
            print(
                f"  - Example ID: {match.example_id} | Score: {match.score} | "
                f"Scenario: {match.scenario}"
            )
        print("-" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())