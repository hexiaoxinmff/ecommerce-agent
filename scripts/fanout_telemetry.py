"""Fan-out Detector telemetry 工具（Task 18）。

从已保存的评测 eval JSON 中读取每条 pred_sql（final_sql，缺失回退 initial_sql），
调用 analyze_fanout 生成只读 telemetry 记录，并原样附带该样本的 outcome 字段。

关键性质（只读、非干预）：
- analyze_fanout(sql) 是确定性纯函数，输入仅 pred_sql；
- 本模块不修改 eval JSON、不触发 repair、不反馈 LLM；
- telemetry JSON 中 outcome 字段（exec_ok / ex / timeout / ...）仅为关联分析复制粘贴，
  不参与 detector 判定。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.sqlcheck.fanout_detector import analyze_fanout, to_dict  # noqa: E402


def build_telemetry(eval_dict: dict) -> list[dict]:
    """对 eval JSON 的每个 result 生成 telemetry 条目。"""
    out: list[dict] = []
    meta = eval_dict.get("meta", {})
    for r in eval_dict.get("results", []):
        sql = (r.get("final_sql") or "").strip() or (r.get("initial_sql") or "").strip()
        diag = analyze_fanout(sql)
        entry = to_dict(diag, case_id=r["eval_id"])
        entry["sql_source"] = "final_sql" if (r.get("final_sql") or "").strip() else "initial_sql"
        # outcome 复制（仅关联分析用，不影响 detector）
        entry["exec_ok"] = bool(r.get("exec_success"))
        entry["ex"] = bool(r.get("execution_accuracy"))
        entry["timeout"] = r.get("error_type") == "timeout"
        entry["provider_failure"] = not bool(r.get("valid_model_run", True))
        entry["model_failure"] = bool(r.get("failure_stage")) and r.get("failure_stage") in (
            "sql_generate", "sql_repair"
        ) and not bool(r.get("valid_model_run", True)) is False
        entry["repair_triggered"] = bool(r.get("repair_triggered"))
        entry["failure_stage"] = r.get("failure_stage")
        entry["error_type"] = r.get("error_type")
        entry["latency_ms"] = r.get("latency_ms")
        entry["meta"] = {
            "run_id": meta.get("run_id"),
            "experiment": meta.get("experiment"),
            "prompt_version": meta.get("prompt_version"),
            "fewshot_version": meta.get("fewshot_version"),
        }
        out.append(entry)
    return out


def write_telemetry(eval_path: Path, out_path: Path) -> int:
    eval_dict = json.loads(eval_path.read_text(encoding="utf-8"))
    tele = build_telemetry(eval_dict)
    payload = {
        "generator": "scripts/fanout_telemetry.py -> app.sqlcheck.fanout_detector.analyze_fanout",
        "gold_independent": True,
        "read_only": True,
        "notes": "telemetry 从已保存 pred_sql 离线补算；outcome 仅关联分析用途，detector 未参与判定",
        "items": tele,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(tele)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Fan-out telemetry generator")
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    n = write_telemetry(args.eval.resolve(), args.out.resolve())
    print(f"telemetry items: {n}")