#!/usr/bin/env python
"""Benchmark Leakage Gate（Task 14.3）：检测 Few-shot 与 Benchmark Gold 之间的泄漏。

检查项：
1. Question 规范化后完全相等；
2. SQL 规范化后完全相等；
3. SQL 高相似（token Jaccard > 阈值，且长度足够）；
4. Benchmark 专属常量泄漏（专用日期/阈值出现在 Few-shot SQL 中，作为补充信号）。

命中任一泄漏 → EXIT != 0（禁止使用该 Few-shot 集做实验）。

阈值设计（避免误伤普通业务相似）：
- exact 匹配：100% 判定泄漏；
- 高相似：SQL 规范化 token 数 >= 15 且 Jaccard > 0.72 且（一方包含另一方或长度比 < 0.7）。
  （"每个地区用户数" vs "每个地区订单数" 之类表名/指标不同 → Jaccard 显著低于阈值，不会误判。）

用法：
    python scripts/check_benchmark_leakage.py
    python scripts/check_benchmark_leakage.py --fewshot data/fewshot/ecommerce_examples.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

JACCARD_THRESHOLD = 0.72
MIN_TOKEN_COUNT = 15
CONTAINMENT_RATIO = 0.70

# Benchmark 专属常量（日期/阈值等；命中即泄漏信号）
BENCH_CONSTANTS = (
    "2026-08-14", "2026-09-12", "2026-06-14", "2026-07-01",
    "2025-10-01", "2025-12-31", "2024-06-01", "2024-06-30",
    "2024-01-01", "2025-01-01", "2026-01-01",
    "30000",  # E-0095 专属阈值
    "50000",  # E-0056 专属阈值
)


def _norm_sql(sql: str) -> str:
    s = re.sub(r"\s+", " ", sql).strip().lower()
    return re.sub(r"[\s'\"]", "", s)


def _norm_q(q: str) -> str:
    return re.sub(r"[\s，。？、（）()：:：]", "", q)


def _tokens(sql: str) -> set[str]:
    return set(re.findall(r"[a-z_0-9]+", _norm_sql(sql)))


def check_leakage(
    fewshot_items: list[dict],
    bench_items: list[dict],
    *,
    bench_constants: tuple[str, ...] = BENCH_CONSTANTS,
) -> list[str]:
    """返回泄漏问题列表（空 = 无泄漏）。"""
    problems: list[str] = []
    bench_sql = {i["id"]: _norm_sql(i["gold_sql"]) for i in bench_items}
    bench_q = {i["id"]: _norm_q(i["question"]) for i in bench_items}
    bench_sql_raw = {i["id"]: i["gold_sql"] for i in bench_items}

    for ex in fewshot_items:
        fid = ex.get("id", "?")
        fsql = _norm_sql(ex.get("sql", ""))
        fq = _norm_q(ex.get("question", ""))
        ftokens = _tokens(ex.get("sql", ""))

        # 1) SQL 完全相等
        for eid, bsql in bench_sql.items():
            if fsql and fsql == bsql:
                problems.append(f"{fid}: SQL 与 {eid} Gold 完全一致（泄漏）")
            # 2) 一方包含另一方（规范化后）
            elif fsql and len(fsql) > 30 and (fsql in bsql or bsql in fsql):
                problems.append(f"{fid}: SQL 与 {eid} Gold 存在包含关系（泄漏）")

        # 3) Question 完全相等
        for eid, bq in bench_q.items():
            if fq and fq == bq:
                problems.append(f"{fid}: question 与 {eid} 完全一致（泄漏）")

        # 4) 高相似 SQL
        for eid, bsql in bench_sql.items():
            btokens = _tokens(bench_sql_raw[eid])
            if len(ftokens) < MIN_TOKEN_COUNT or len(btokens) < MIN_TOKEN_COUNT:
                continue
            inter = len(ftokens & btokens)
            union = len(ftokens | btokens)
            j = inter / union if union else 0.0
            # 长度悬殊时（一方极短）不算高相似（防误伤）
            if len(ftokens) == 0 or len(btokens) == 0:
                continue
            len_ratio = min(len(ftokens), len(btokens)) / max(len(ftokens), len(btokens))
            if j > JACCARD_THRESHOLD and len_ratio >= CONTAINMENT_RATIO:
                problems.append(
                    f"{fid}: SQL 与 {eid} 高相似（Jaccard={j:.2f}）——模板级泄漏风险"
                )

        # 5) Benchmark 专属常量泄漏
        fsql_lower = _norm_sql(ex.get("sql", "")).lower()
        for c in bench_constants:
            if c.lower() in fsql_lower:
                problems.append(f"{fid}: 命中 Benchmark 专属常量 {c!r}（泄漏信号）")

    # 去重
    return list(dict.fromkeys(problems))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark Leakage Gate")
    p.add_argument("--fewshot", type=Path, default=PROJECT_ROOT / "data" / "fewshot" / "ecommerce_examples.json")
    p.add_argument("--benchmark", type=Path, default=PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    few = json.loads(args.fewshot.read_text(encoding="utf-8"))
    bench = json.loads(args.benchmark.read_text(encoding="utf-8"))["items"]
    problems = check_leakage(few, bench)

    if not args.quiet:
        print(f"Few-shot 条数：{len(few)}；Benchmark 条数：{len(bench)}")
        if problems:
            print(f"泄漏命中：{len(problems)} 项")
            for pr in problems:
                print(f"  ✗ {pr}")
        else:
            print("Leakage Gate：PASS（无泄漏）")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())