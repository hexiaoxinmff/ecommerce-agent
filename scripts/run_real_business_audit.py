#!/usr/bin/env python
"""Phase 14：Real Business Question Set 离线审计（真实 Agent 运行）。

用法（项目根目录）：
    python scripts/run_real_business_audit.py                # P20 全部 + 陷阱题
    python scripts/run_real_business_audit.py --ids RBQ-011  # 指定题号
    python scripts/run_real_business_audit.py --no-traps     # 只跑 P20

行为约定：
- 复用正式评测核心 evaluation.runner.eval_single_item（Agent Core 零改动）；
- Agent = 当前真实运行配置（default_components：Profile A + config Provider）；
- 数据集 = data/eval/real_business_v1.json（Phase 14 新增，不触碰冻结 Benchmark）；
- 陷阱题（无 gold）单独运行并保留完整响应供人工评审；
- 产物写入 reports/phase14/rbq_audit_results.json / rbq_trap_results.json；
- 全部只读，不修改任何数据库与冻结资产。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from evaluation.models import EvalCaseResult  # noqa: E402
from evaluation.runner import EvalConfig, eval_single_item  # noqa: E402
from app.agent.graph import run_agent  # noqa: E402

DATASET_PATH = PROJECT_ROOT / "data" / "eval" / "real_business_v1.json"
OUT_DIR = PROJECT_ROOT / "reports" / "phase14"


def run_one_with_timeout(item: dict, eval_cfg: EvalConfig, timeout_s: float):
    holder: dict = {}
    error: dict = {}

    def _wrapped():
        try:
            holder["r"] = eval_single_item(item, eval_cfg)
        except Exception as exc:  # noqa: BLE001
            error["e"] = exc

    t = threading.Thread(target=_wrapped, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        return EvalCaseResult(
            eval_id=item["id"], question=item["question"],
            difficulty=item.get("difficulty", ""), scenario=item.get("scenario", ""),
            gold_sql=item.get("gold_sql") or "", pred_sql="",
            exec_success=False, execution_accuracy=False, valid_model_run=False,
            failure_stage="timeout", error_type="timeout", latency_ms=timeout_s * 1000,
        )
    if "e" in error:
        raise error["e"]
    return holder["r"]


def main() -> None:
    ap = argparse.ArgumentParser(description="RBQ 离线审计 Runner")
    ap.add_argument("--ids", type=str, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--no-traps", action="store_true")
    ap.add_argument(
        "--out-dir",
        type=str,
        default=str(OUT_DIR),
        help="产物目录（Phase 15 复跑用 reports/phase15，避免覆盖 Phase 14 原始产物）",
    )
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    items = data["items"]
    wanted = set(args.ids.split(",")) if args.ids else None

    p20 = [
        i for i in items
        if i["tier"] == "P20" and (wanted is None or i["id"] in wanted)
    ]
    traps = [
        i for i in items
        if i["tier"] == "TRAP" and (wanted is None or i["id"] in wanted)
        and not args.no_traps
    ]

    eval_cfg = EvalConfig(
        dataset_path=DATASET_PATH,
        enable_gold_hash_gate=False,  # 非 Benchmark 数据集，gold 已由构建脚本逐一验证
    )

    results = []
    print(f"[RBQ audit] P20={len(p20)} 题, TRAP={len(traps)} 题, timeout={args.timeout}s")
    for idx, item in enumerate(p20, 1):
        t0 = time.perf_counter()
        try:
            r = run_one_with_timeout(item, eval_cfg, args.timeout)
        except Exception as exc:  # noqa: BLE001
            r = EvalCaseResult(
                eval_id=item["id"], question=item["question"],
                difficulty=item.get("difficulty", ""), scenario=item.get("scenario", ""),
                gold_sql=item.get("gold_sql") or "", pred_sql="",
                exec_success=False, execution_accuracy=False, valid_model_run=False,
                failure_stage="runner_error", error_type=type(exc).__name__,
                latency_ms=0.0,
            )
        results.append(r)
        flag = "OK " if r.execution_accuracy else ("EXEC" if r.exec_success else "FAIL")
        print(
            f"[{idx:>2}/{len(p20)}] {r.eval_id} {flag} "
            f"ex={r.execution_accuracy} exec={r.exec_success} "
            f"stage={r.failure_stage} err={r.error_type} "
            f"{time.perf_counter() - t0:.1f}s",
            flush=True,
        )
        # 每题落盘一次（中断不丢结果）
        (out_dir / "rbq_audit_results.json").write_text(
            json.dumps(
                {"meta": {"dataset": str(DATASET_PATH), "ran_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                 "results": [asdict(x) for x in results]},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    trap_results = []
    for idx, item in enumerate(traps, 1):
        t0 = time.perf_counter()
        # 陷阱题不走 eval 判定（无 gold），直接调用真实 Agent 保留完整响应
        try:
            agent_res = run_agent(item["question"])
            trap_results.append({
                "id": item["id"],
                "question": item["question"],
                "business_rule": item.get("business_rule", ""),
                "expected_behavior": item.get("expected_business_intent", ""),
                "success": bool(agent_res.success),
                "generated_sql": agent_res.generated_sql,
                "repaired_sql": agent_res.repaired_sql,
                "execution_result": (
                    {
                        "columns": agent_res.execution_result.columns,
                        "rows": agent_res.execution_result.rows[:10],
                        "row_count": agent_res.execution_result.row_count,
                    }
                    if agent_res.execution_result else None
                ),
                "final_error": agent_res.final_error,
                "execution_error": agent_res.execution_error,
                "repair_count": agent_res.repair_count,
                "total_time_ms": agent_res.total_time_ms,
                "latency_s": round(time.perf_counter() - t0, 1),
            })
        except Exception as exc:  # noqa: BLE001
            trap_results.append({
                "id": item["id"], "question": item["question"],
                "success": False, "final_error": f"{type(exc).__name__}: {exc}",
                "latency_s": round(time.perf_counter() - t0, 1),
            })
        print(
            f"[TRAP {idx}/{len(traps)}] {item['id']} success={trap_results[-1].get('success')} "
            f"{trap_results[-1].get('latency_s')}s",
            flush=True,
        )
        (out_dir / "rbq_trap_results.json").write_text(
            json.dumps({"results": trap_results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 汇总
    n = len(results)
    ex = sum(1 for r in results if r.execution_accuracy)
    execd = sum(1 for r in results if r.exec_success)
    lat = sorted(r.latency_ms for r in results)
    print("\n==== SUMMARY ====")
    print(f"P20: {n} 题 | EX={ex}/{n} ({ex / n * 100:.1f}%) | ExecSuccess={execd}/{n} ({execd / n * 100:.1f}%)")
    if lat:
        p50 = lat[len(lat) // 2]
        p95 = lat[int(len(lat) * 0.95) - 1] if len(lat) > 1 else lat[-1]
        print(f"Latency avg={sum(lat) / len(lat):.0f}ms p50={p50:.0f}ms p95={p95:.0f}ms")
    stages = {}
    for r in results:
        if not r.execution_accuracy:
            stages.setdefault(str(r.failure_stage), []).append(r.eval_id)
    for stage, ids in sorted(stages.items()):
        print(f"  {stage}: {len(ids)} -> {','.join(ids)}")


if __name__ == "__main__":
    main()
