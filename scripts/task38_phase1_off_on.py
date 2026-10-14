"""Task 38 第一阶段：E-0057 单例 OFF / ON 对照（真实 Mimo）。

唯一变量 = 「条件性统计实体 / 驱动表约束」（SQLGEN_EXTRA_RULES=E8）。
其余全部冻结：Prompt 其余部分、Few-shot、Schema Linking、Repair、
Model、Provider、DB、Evaluation runner。

API Key 仅从环境变量 MIMO_API_KEY 读取，绝不写入任何文件。
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

QID = "E-0057"


def _load_item() -> dict:
    data = json.loads(
        (ROOT / "data" / "eval" / "ecommerce_eval_v1.json").read_text(encoding="utf-8")
    )
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    return next(it for it in items if it["id"] == QID)


def _provider_calls(row: dict) -> int:
    """统计实际 LLM 调用：schema_link + sql_generate（+ repair 若触发）。"""
    return sum(
        1
        for ev in row.get("trace", [])
        if ev.get("node") in ("schema_link", "sql_generate", "sql_repair")
        and ev.get("status") == "success"
    )


def _adopted(sql: str) -> dict:
    """结构性判定：是否采用正确统计实体（不读 gold）。"""
    u = sql.upper()
    return {
        "driver_is_orders": ("FROM ORDERS" in u),
        "no_left_join": ("LEFT JOIN" not in u),
        "grain_user_id": ("USER_ID" in u),
    }


def main() -> int:
    if not os.getenv("MIMO_API_KEY"):
        print("MIMO_API_KEY 未设置 —— 无法执行真实对照。")
        return 2

    from app.schema.metadata import SchemaCatalog
    from evaluation.runner import EvalConfig, eval_single_item

    item = _load_item()
    question, gold = item["question"], item["gold_sql"]
    print(f"问题: {question}\n")

    results: dict[str, dict] = {}
    for arm in ("OFF", "ON"):
        if arm == "ON":
            os.environ["SQLGEN_EXTRA_RULES"] = "E8"
        else:
            os.environ.pop("SQLGEN_EXTRA_RULES", None)
        SchemaCatalog.clear_cache()

        print(f"{'='*72}\n[{arm}] 运行中...\n{'='*72}")
        started = time.perf_counter()
        res = eval_single_item(dict(item), EvalConfig(timeout_s=60.0))
        wall_ms = round((time.perf_counter() - started) * 1000.0, 2)

        row = dataclasses.asdict(res)
        row["_wall_ms"] = wall_ms
        row["_provider_calls"] = _provider_calls(row)
        results[arm] = row

        print(f"  pred_sql   : {row['pred_sql']}")
        print(f"  exec_success = {row['exec_success']}")
        print(f"  EX           = {row['execution_accuracy']}")
        print(f"  error_type   = {row['error_type']!r}")
        print(f"  repair_count = {row['repair_count']}")
        print(f"  provider_calls = {row['_provider_calls']}")
        print(f"  wall_ms      = {wall_ms}")
        print("  trace:")
        for t in row.get("trace", []):
            print(f"     {t.get('node'):24s} {t.get('status'):8s} "
                  f"{round(t.get('duration_ms', 0), 1)} ms")

    print(f"\n{'='*72}\n对照总结\n{'='*72}")
    for arm in ("OFF", "ON"):
        r = results[arm]
        print(f"\n[{arm}]")
        for k, v in _adopted(r["pred_sql"]).items():
            print(f"    {k:20s} = {v}")
        print(f"    EX                   = {r['execution_accuracy']}")
        print(f"    exec_success         = {r['exec_success']}")
        print(f"    provider_calls       = {r['_provider_calls']}")
        print(f"    wall_ms              = {r['_wall_ms']}")

    out = ROOT / "reports" / "eval" / "task38_phase1"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "question_id": QID,
        "question": question,
        "gold_sql": gold,
        "single_variable": "SQLGEN_EXTRA_RULES=E8 (条件性统计实体/驱动表约束)",
        "arms": {
            arm: {k: v for k, v in results[arm].items() if k != "trace"}
            | {"trace": [
                {"node": t.get("node"), "status": t.get("status"),
                 "duration_ms": t.get("duration_ms")}
                for t in results[arm].get("trace", [])
            ]}
            for arm in ("OFF", "ON")
        },
    }
    (out / "e0057_off_on.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n结果已写入: {out / 'e0057_off_on.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
