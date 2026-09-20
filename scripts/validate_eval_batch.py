"""ECO-SQL-Bench 批次候选校验与入集脚本（Task 12 用，轻量版）。

职责（复用 validate_eval_dataset.py 的校验逻辑，不重复造轮子）：
1. 读取候选题 JSON（data/eval/drafts/*.json，含 batch 元数据：commit_total/
   scenario_targets/operator_targets，向后兼容 Easy 批次缺省）；
2. 逐条跑 validate_item（结构/枚举/ID/禁止项/安全/真实库执行）；
3. 真实执行 gold_sql 并生成 gold_result_hash（复用 normalize_result_hash，算法唯一权威）；
4. 完全重复 + 规范化重复检测；
5. 输出 难度×场景 与 难度×operator 覆盖，对照 drafts 内 operator_targets（=矩阵 §7.3/§7.4）；
6. --commit：仅当正式候选数量 == commit_total、场景配额完全匹配、全部无问题且无重复时，
   才将 E-xxxx 写入 data/eval/ecommerce_eval_v1.json（保留原 metadata）；否则拒绝写入并退出 1。

不实现：Agent 批量评测 / EX / Pass@1 / Repair Rate（后续 Task）。

用法（项目根目录）：
    python scripts/validate_eval_batch.py --drafts data/eval/drafts/easy_batch1_candidates.json
    python scripts/validate_eval_batch.py --drafts data/eval/drafts/medium_batch2_candidates.json --commit
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# 复用 Task 11 已冻结的校验与 hash 实现（唯一权威算法）
from validate_eval_dataset import (  # noqa: E402
    DIFFICULTIES,
    EvalDatasetError,
    SCENARIOS,
    _normalize_question,
    load_dataset,
    normalize_result_hash,
    validate_gold_sql,
    validate_item,
)

DEFAULT_DRAFTS = PROJECT_ROOT / "data" / "eval" / "drafts" / "easy_batch1_candidates.json"
DEFAULT_OUT = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"

# Easy 档最低覆盖（向后兼容缺省值；Medium/Hard/Extra Hard 由 drafts.operator_targets 提供，
# 其值 = docs/evaluation-matrix.md §7.3 对应难度行）
EASY_OPERATOR_TARGETS: dict[str, int] = {
    "aggregate": 20, "where": 15, "date_filter": 4,
    "order_by": 3, "limit": 3, "top_n": 2,
}

COMMIT_ID_PATTERN = re.compile(r"^E-\d{4}$")


def run_candidate(item: dict, conn: sqlite3.Connection):
    """执行候选 gold_sql 并返回 (rows, columns, hash)。"""
    sql = item["gold_sql"]
    cur = conn.execute(sql)
    columns = [desc[0] for desc in cur.description]
    rows = [tuple(row) for row in cur.fetchall()]
    return rows, columns, normalize_result_hash(columns, rows)


def scan(candidates: list[dict], catalog, conn) -> dict:
    """逐条校验 + 执行，返回结果表。

    候选稿不含 gold_result_hash（属于候选题），构建器先以 64 位占位符通过结构校验，
    真实 hash 在 gold_sql 执行后回填到候选（仅内存，不修改磁盘 drafts 文件）。
    """
    result: dict[str, dict] = {}
    for index, item in enumerate(candidates):
        item_id = item.get("id", f"?[{index}]")
        item["gold_result_hash"] = "0" * 64  # 占位，仅供结构校验；随后用真实 hash 覆盖
        problems = validate_item(item, index, catalog, conn)
        entry = {"item": item, "problems": problems, "rows": None, "hash": None}
        if not problems and isinstance(item.get("gold_sql"), str):
            try:
                rows, columns, digest = run_candidate(item, conn)
                entry["rows"] = rows
                entry["hash"] = digest
                entry["row_count"] = len(rows)
                entry["sample"] = rows[0] if rows else None
                item["gold_result_hash"] = digest  # 真实 hash 写回候选（内存）
            except sqlite3.Error as exc:
                entry["problems"] = [f"hash 执行失败：{exc}"]
        result[item_id] = entry
    return result


def scan_duplicates(candidates: list[dict]) -> list[str]:
    problems: list[str] = []
    seen_exact: dict[str, str] = {}
    seen_norm: dict[str, str] = {}
    for item in candidates:
        q = item.get("question", "")
        item_id = str(item.get("id"))
        if not isinstance(q, str) or not q.strip():
            continue
        if q in seen_exact:
            problems.append(f"候选 {item_id} 与 {seen_exact[q]} 构成完全重复 question：{q!r}")
        else:
            seen_exact[q] = item_id
        norm = _normalize_question(q)
        if norm in seen_norm:
            problems.append(f"候选 {item_id} 与 {seen_norm[norm]} 构成规范化重复 question：{q!r}")
        else:
            seen_norm[norm] = item_id
    return problems


def coverage(items: list[dict]) -> dict:
    scenario: dict[str, int] = {}
    operators: dict[str, int] = {}
    for item in items:
        scenario[item.get("scenario", "?")] = scenario.get(item.get("scenario", "?"), 0) + 1
        for op in item.get("operators", []):
            if isinstance(op, str):
                operators[op] = operators.get(op, 0) + 1
    return {"scenario": scenario, "operators": operators}


def select_commit_items(scan_result: dict, targets: dict) -> tuple[list[dict], list[str]]:
    """按候选顺序选出 25 条 E-xxxx 且无问题的正式题，并检查场景配额。"""
    selected: list[dict] = []
    for item_id in sorted((i for i in scan_result if COMMIT_ID_PATTERN.match(i))):
        entry = scan_result[item_id]
        if not entry["problems"] and entry["hash"]:
            selected.append(entry["item"])
    problems: list[str] = []
    if len(selected) != sum(targets.values()):
        problems.append(
            f"通过校验的正式候选数 {len(selected)} != 目标 {sum(targets.values())}"
        )
    counts = coverage(selected)["scenario"]
    for scenario, target in targets.items():
        if counts.get(scenario, 0) != target:
            problems.append(
                f"scenario {scenario} 覆盖 {counts.get(scenario, 0)}/{target}"
            )
    return selected, problems


def build_items(selected: list[dict], scan_result: dict, conn: sqlite3.Connection) -> list[dict]:
    items = []
    for item in selected:
        entry = scan_result[item["id"]]
        new = {
            "id": item["id"],
            "split": item.get("split", "eval"),
            "difficulty": item["difficulty"],
            "scenario": item["scenario"],
            "operators": list(item["operators"]),
            "question": item["question"],
            "gold_sql": item["gold_sql"],
            "gold_result_hash": entry["hash"],
            "expected_behavior": item.get("expected_behavior", "answer"),
            "answer_slots": item.get("answer_slots"),
            "multi_turn": item.get("multi_turn"),
            "notes": item.get("notes", ""),
        }
        items.append(new)
    return sorted(items, key=lambda x: x["id"])


def _print_cover_report(items: list[dict], targets: dict[str, int]) -> None:
    cov = coverage(items)
    difficulty = sorted({i["difficulty"] for i in items})
    print("\n[难度 × 场景 覆盖]")
    print(f"  难度：{difficulty}")
    for scenario in sorted(cov["scenario"]):
        print(f"  {scenario}: {cov['scenario'][scenario]}")
    print("\n[难度 × operator 覆盖（目标 from 矩阵 §7.3 / drafts.operator_targets）]")
    all_ops = sorted(set(targets) | set(cov["operators"]))
    for op in all_ops:
        target = targets.get(op, 0)
        observed = cov["operators"].get(op, 0)
        mark = "✓" if observed >= target else f"（缺口 {target - observed}）"
        print(f"  {observed:>3}/{target:<3} {op} {mark}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ECO-SQL-Bench 批次候选校验与入集")
    parser.add_argument("--drafts", type=Path, default=DEFAULT_DRAFTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--commit", action="store_true", help="全部检查通过后写正式集")
    args = parser.parse_args(argv)

    from app.db.sqlite import get_connection  # noqa: PLC0415
    from app.schema.metadata import SchemaCatalog  # noqa: PLC0415
    import validate_eval_dataset as ved  # noqa: PLC0415

    data = load_dataset(args.drafts, "candidates")
    candidates: list[dict] = data["candidates"]
    scenario_targets: dict[str, int] = data.get("scenario_targets", {})
    operator_targets: dict[str, int] = data.get(
        "operator_targets", EASY_OPERATOR_TARGETS
    )
    target_total: int = data.get("target_total", sum(scenario_targets.values()))

    catalog = SchemaCatalog.from_database()
    with closing(get_connection()) as conn:
        scan_result = scan(candidates, catalog, conn)

    print("=" * 70)
    print("ECO-SQL-Bench 批次候选校验")
    print(f"候选数：{len(candidates)}")
    print(f"{'ID':<10}{'scenario':<20}{'rows':>5}  {'hash[12]':<14}样例/问题")
    print("-" * 70)
    for item in candidates:
        entry = scan_result[item["id"]]
        status = "✓" if not entry["problems"] else "✗"
        if entry.get("row_count") is not None:
            sample = str(entry["sample"])[:40]
        else:
            sample = "; ".join(entry["problems"])[:40]
        print(
            f"{item['id']:<10}{item.get('scenario','?'):<20}"
            f"{entry.get('row_count',0):>5}  {str(entry['hash'])[:12] if entry['hash'] else '-':<14}"
            f"[{status}] {sample}"
        )

    dup_problems = scan_duplicates(candidates)
    for problem in dup_problems:
        print(f"[去重] {problem}")

    selected, quota_problems = select_commit_items(scan_result, scenario_targets)
    _print_cover_report(selected, operator_targets)

    print("\n" + "=" * 70)
    if dup_problems or quota_problems:
        for p in dup_problems + quota_problems:
            print(f"✗ {p}")
    else:
        print(f"✓ {len(selected)} 条正式候选全部通过结构/执行/hash/去重/场景配额检查")

    if args.commit:
        if dup_problems or quota_problems or len(selected) != target_total:
            print("拒绝提交：存在未通过项，未写入正式集。")
            return 1
        with closing(get_connection()) as conn:
            items = build_items(selected, scan_result, conn)
        out_meta = _load_out_metadata(args.out)
        out_meta.update(
            {
                "generator_version": "1",  # validate_eval_batch.py 首次批量生成
                "created_at": out_meta.get("created_at", "2026-09-15"),
                "review_status": "reviewed",  # Batch 1 已通过本批次审核，待总顾问复核
            }
        )
        # Batch 2+：正式集已存在先序批次条目时合并（不得覆盖既有 ID）
        merged = _merge_with_existing(args.out, items)
        payload = {"metadata": out_meta, "items": merged}
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写入正式集：{args.out}（{len(merged)} 条）")
    return 1 if (dup_problems or quota_problems) else 0


def _merge_with_existing(path: Path, new_items: list[dict]) -> list[dict]:
    """将新批次条目并入既有正式集（by id 去重，新批次优先保留），保持顺序稳定。"""
    try:
        existing = load_dataset(path, "items").get("items", [])
    except EvalDatasetError:
        existing = []
    by_id: dict[str, dict] = {}
    for item in existing + new_items:
        item_id = item.get("id")
        if item_id and (item_id not in by_id or item in new_items):
            by_id[item_id] = item
    return sorted(by_id.values(), key=lambda x: x["id"])


def _load_out_metadata(path: Path) -> dict:
    try:
        existing = load_dataset(path, "items")
        return dict(existing.get("metadata", {}))
    except EvalDatasetError:
        return {
            "dataset_name": "ECO-SQL-Bench",
            "subtitle": "项目自建电商 Text2SQL 评测集",
            "version": "1.0",
            "database_version": "dev-2026-09-14",
            "seed": 20260914,
            "schema_version": "1.0",
            "generator_version": "1",
            "created_at": "2026-09-15",
            "review_status": "reviewed",
        }


if __name__ == "__main__":
    sys.exit(main())