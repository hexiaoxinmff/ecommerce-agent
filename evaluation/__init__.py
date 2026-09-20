"""ECO-SQL-Bench 自动化评测（Task 13）。

包结构：
- runner.py       评测主流程（Gold Hash Gate / Agent 调用 / EX 判定 / 失败归因）
- metrics.py      指标聚合（Exec Rate / EX / Pass@1 / Repair / Latency 等）
- normalization.py 结果归一化与 D1~D9 等价比较（唯一权威实现）
- report.py       报告生成（JSON/Markdown）+ Bad Case 沉淀
- models.py       数据结构（单题结果 / 运行摘要 / 元信息）
"""

from evaluation.normalization import (
    ComparisonOutcome,
    NormalizedResult,
    compare_results,
    normalize_result,
)

__all__ = [
    "ComparisonOutcome",
    "NormalizedResult",
    "compare_results",
    "normalize_result",
]