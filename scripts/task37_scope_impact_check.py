"""Task 37 校验：别名检查对冻结基线的行为影响（零 LLM 调用）。

目的：确认新增的 Scope 校验**不改变任何合法 SQL 的既有行为**。
方法：对冻结基线 100 题的 pred_sql / gold_sql 全量重放检查，
     统计命中集合，并与「实际执行失败集合」交叉验证。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "backend")

from app.sqlcheck.scope_validator import check_sql_scope

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "reports" / "eval" / "clean_baseline_v1_1" / "eval_clean_baseline_v1_1.json"
DATASET = ROOT / "data" / "eval" / "ecommerce_eval_v1.json"


def load_baseline():
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return data["results"] if "results" in data else data["items"]


def load_gold():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    return {it["id"]: it for it in items}


def main() -> int:
    rows = load_baseline()
    gold = load_gold()

    print("=" * 72)
    print("Task 37 — Alias Scope 校验对冻结基线的影响（零 LLM）")
    print("=" * 72)

    # --- 1. gold SQL 假阳性 ---
    gold_fp = []
    for qid, item in gold.items():
        result = check_sql_scope(item.get("gold_sql") or "")
        if not result.ok:
            gold_fp.append((qid, result.messages))
    print(f"\n[1] gold SQL 假阳性: {len(gold_fp)}/100")
    for qid, msgs in gold_fp:
        print(f"    {qid}: {msgs}")

    # --- 2. pred SQL 命中 ---
    pred_hits = []
    parse_err = []
    total = 0
    for row in rows:
        qid = row.get("eval_id") or row.get("id")
        pred = row.get("pred_sql") or ""
        if not pred.strip():
            continue
        total += 1
        try:
            result = check_sql_scope(pred)
        except Exception as exc:  # noqa: BLE001
            parse_err.append((qid, type(exc).__name__))
            continue
        if not result.ok:
            pred_hits.append((qid, result.messages, row.get("error_type") or ""))

    print(f"\n[2] pred SQL 命中: {len(pred_hits)}/{total}  (解析异常 {len(parse_err)})")
    for qid, msgs, et in pred_hits:
        print(f"    {qid}")
        print(f"        命中: {msgs}")
        print(f"        真实 error_type: {et!r}")

    # --- 3. 交叉验证：命中集 vs 真实执行失败集 ---
    real_fail = set()
    for row in rows:
        qid = row.get("eval_id") or row.get("id")
        err = str(row.get("execution_error") or "")
        if "no such column" in err:
            real_fail.add(qid)
        else:
            for ev in row.get("trace", []):
                if ev.get("node") == "sql_execute" and ev.get("status") == "error":
                    if "no such column" in str(ev.get("message") or ""):
                        real_fail.add(qid)

    hit_set = {qid for qid, _, _ in pred_hits}
    print("\n[3] 交叉验证（alias 类真实执行失败）")
    print(f"    真实 no-such-column 失败集: {sorted(real_fail)}")
    print(f"    校验命中集                : {sorted(hit_set)}")
    print(f"    命中 ∩ 真实失败           : {sorted(hit_set & real_fail)}")
    print(f"    命中 − 真实失败（误报）    : {sorted(hit_set - real_fail)}")
    print(f"    真实失败 − 命中（漏报）    : {sorted(real_fail - hit_set)}")

    # --- 4. 结论 ---
    verdict = (
        len(gold_fp) == 0
        and hit_set == real_fail
    )
    print("\n" + "=" * 72)
    print(f"gold 假阳性 = {len(gold_fp)}  (要求 0)")
    print(f"pred 误报   = {sorted(hit_set - real_fail)}  (要求空)")
    print(f"pred 漏报   = {sorted(real_fail - hit_set)}  (要求空)")
    print(f"结论: {'PASS' if verdict else 'FAIL'}")
    print("=" * 72)
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
