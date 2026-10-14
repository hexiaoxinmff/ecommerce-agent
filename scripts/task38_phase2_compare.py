"""Task 38 第二阶段：冻结 100 题 OFF / ON 对照分析。

输入：
- ON  臂：reports/eval/task38_phase2_on/  （SQLGEN_EXTRA_RULES=E8）
- OFF 臂：reports/eval/task38_phase2_off/ （无 E8，或直接复用冻结基线）

说明：OFF 臂优先复用**冻结 Clean Baseline**，因为 ON 尚未合入 master，
      baseline 就是严格意义上的 OFF（Prompt 已证明逐字节相同）。
      若本地另有 OFF 重跑，一并对比以排除时间漂移。

输出：reports/eval/task38_phase2/compare.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGET_ID = "E-0057"


def _load(directory: Path) -> list[dict]:
    """从目录里找唯一的 eval_*.json 并返回 results。"""
    files = sorted(directory.glob("eval_*.json"))
    if not files:
        return []
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return data.get("results", data.get("items", []))


def _index(rows: list[dict]) -> dict[str, dict]:
    return {(r.get("eval_id") or r.get("id")): r for r in rows}


def _pct(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return round(100.0 * sum(1 for r in rows if r.get("execution_accuracy")) / len(rows), 2)


def _latency(rows: list[dict]) -> dict:
    vals = sorted(r.get("latency_ms", 0.0) for r in rows if r.get("latency_ms"))
    if not vals:
        return {}
    n = len(vals)
    return {
        "mean": round(sum(vals) / n, 2),
        "p50": round(vals[n * 50 // 100], 2),
        "p95": round(vals[n * 95 // 100], 2),
    }


def _provider_failures(rows: list[dict]) -> int:
    names = {"LLMTimeoutError", "LLMNetworkError", "LLMServiceUnavailableError",
             "LLMRateLimitError", "LLMAuthenticationError",
             "LLMInsufficientBalanceError", "LLMProviderNotConfiguredError"}
    return sum(1 for r in rows if (r.get("error_type") or "") in names
               or not r.get("valid_model_run", True))


def _exec_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return round(100.0 * sum(1 for r in rows if r.get("exec_success")) / len(rows), 2)


def main() -> int:
    on_rows = _load(ROOT / "reports" / "eval" / "task38_phase2_on")
    if not on_rows:
        print("未找到 ON 臂结果。")
        return 2

    baseline_path = (ROOT / "reports" / "eval" / "clean_baseline_v1_1"
                     / "eval_clean_baseline_v1_1.json")
    baseline_rows = json.loads(baseline_path.read_text(encoding="utf-8"))["results"]

    off_rows_local = _load(ROOT / "reports" / "eval" / "task38_phase2_off")

    on = _index(on_rows)
    base = _index(baseline_rows)

    print("=" * 76)
    print("Task 38 第二阶段 — 冻结 100 题 OFF / ON 对照")
    print("=" * 76)

    def report(name: str, rows: list[dict], idx: dict[str, dict]) -> dict:
        ex = _pct(rows)
        exr = _exec_rate(rows)
        lat = _latency(rows)
        pf = _provider_failures(rows)
        tgt = idx.get(TARGET_ID, {})
        print(f"\n[{name}]  n={len(rows)}")
        print(f"    Overall EX   = {ex}%")
        print(f"    Exec         = {exr}%")
        print(f"    {TARGET_ID} EX     = {tgt.get('execution_accuracy')}")
        print(f"    provider fail= {pf}")
        print(f"    latency      = {lat}")
        return {"n": len(rows), "ex": ex, "exec": exr, "latency": lat,
                "provider_failures": pf, "target_ex": tgt.get("execution_accuracy")}

    res_on = report("ON (E8 条件性统计实体约束)", on_rows, on)
    res_off = report("OFF (冻结 Clean Baseline)", baseline_rows, base)

    # ---- 逐题回归检测 ----
    regressions = []
    fixes = []
    for qid, brow in base.items():
        orow = on.get(qid)
        if orow is None:
            continue
        b_ok = bool(brow.get("execution_accuracy"))
        o_ok = bool(orow.get("execution_accuracy"))
        if b_ok and not o_ok:
            regressions.append({
                "id": qid,
                "baseline_error": brow.get("error_type"),
                "on_error": orow.get("error_type"),
                "on_pred": (orow.get("pred_sql") or "")[:120],
            })
        elif not b_ok and o_ok:
            fixes.append(qid)

    print(f"\n{'='*76}")
    print("逐题变化")
    print(f"{'='*76}")
    print(f"  新增修复 (FAIL->PASS) : {len(fixes)}  {fixes}")
    print(f"  新增回归 (PASS->FAIL) : {len(regressions)}")
    for r in regressions:
        print(f"      {r['id']}: {r['baseline_error']} -> {r['on_error']}")

    # ---- 失败结构变化 ----
    print(f"\n{'='*76}")
    print("失败结构对比")
    print(f"{'='*76}")
    for qid in sorted(set(base) | set(on)):
        b_ok = bool(base.get(qid, {}).get("execution_accuracy"))
        o_ok = bool(on.get(qid, {}).get("execution_accuracy"))
        if b_ok != o_ok:
            print(f"  {qid}: baseline={'PASS' if b_ok else 'FAIL'} -> "
                  f"on={'PASS' if o_ok else 'FAIL'}")

    payload = {
        "target": TARGET_ID,
        "single_variable": "SQLGEN_EXTRA_RULES=E8 (条件性统计实体/驱动表约束)",
        "off": res_off,
        "on": res_on,
        "new_fixes": fixes,
        "regressions": regressions,
        "gate": {
            "target_flipped_fail_to_pass": bool(
                not base.get(TARGET_ID, {}).get("execution_accuracy")
                and on.get(TARGET_ID, {}).get("execution_accuracy")
            ),
            "no_new_regressions": len(regressions) == 0,
            "exec_not_decreased": res_on["exec"] >= res_off["exec"],
            "provider_failure_delta": res_on["provider_failures"] - res_off["provider_failures"],
        },
    }
    out = ROOT / "reports" / "eval" / "task38_phase2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n结果已写入: {out / 'compare.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
