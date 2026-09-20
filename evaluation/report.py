"""评测报告生成：JSON + Markdown 双输出，含难度/场景/Operator/失败分布表。

Bad Case 沉淀：EX=false 的条目写入 data/eval/bad_cases/{case_id}.json
（结构对齐 bad_cases/README.md），供 Task 14 直接使用。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.models import EvalCaseResult, EvalRunMeta, EvalRunSummary
from evaluation import metrics as ev_metrics


def build_meta(*, dataset_version: str, database_version: str, schema_version: str,
               seed: int, model: str, provider: str, base_url: str, run_id: str | None = None,
               mode: str = "full", per_item_timeout_s: float = 60.0,
               prompt_version: str = "", fewshot_version: str = "",
               experiment: str = "", prompt_sha256: str = "",
               fewshot_sha256: str = "", fewshot_path: str = "",
               dataset_sha256: str = "", db_table_counts: str = "") -> EvalRunMeta:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return EvalRunMeta(
        run_id=run_id or f"{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}",
        timestamp=ts,
        dataset_version=dataset_version,
        database_version=database_version,
        schema_version=schema_version,
        seed=seed,
        model=model,
        provider=provider,
        base_url=base_url,
        prompt_version=prompt_version,
        randomness="provider API controlled randomness unavailable",
        per_item_timeout_s=per_item_timeout_s,
        total_items=0,
        mode=mode,
        experiment=experiment,
        fewshot_version=fewshot_version,
        prompt_sha256=prompt_sha256,
        fewshot_sha256=fewshot_sha256,
        fewshot_path=fewshot_path,
        dataset_sha256=dataset_sha256,
        db_table_counts=db_table_counts,
    )


def build_summary(results: list[EvalCaseResult], meta: EvalRunMeta) -> EvalRunSummary:
    agg = ev_metrics.aggregate(results)
    o = agg["overall"]
    return EvalRunSummary(
        meta=meta,
        total=o["total"],
        valid_model_runs=o["valid_model_runs"],
        provider_failures=o["provider_failures"],
        timeouts=o["timeouts"],
        exec_rate=o["exec_rate"],
        ex=o["ex"],
        conditional_ex=o["conditional_ex"],
        pass_at_1=o["pass_at_1"],
        final_ex=o["final_ex"],
        repair_trigger_rate=o["repair_trigger_rate"],
        repair_success_rate=o["repair_success_rate"],
        avg_latency_ms=o["latency_ms"]["avg"],
        p50_latency_ms=o["latency_ms"]["p50"],
        p95_latency_ms=o["latency_ms"]["p95"],
        by_difficulty=agg["by_difficulty"],
        by_scenario=agg["by_scenario"],
        by_operator=agg["by_operator"],
        failure_stages=agg["failure_stages"],
        error_types=agg["error_types"],
    )


def write_case_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    """结果明细（不含 trace 敏感内容）转可序列化 dict 列表。"""
    return [r.to_dict() for r in results]


def write_bad_cases(results: list[EvalCaseResult], out_dir: Path, base: int = 0) -> int:
    """将 EX=false 的条目写入 out_dir/{case_id}.json，返回生成条数。

    case_id 从 B-{1000:04d} 起始递增（避免与既有示例/历史冲突由调用方传 base）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = [r for r in results if not r.execution_accuracy]
    counter = base
    for case in failed:
        counter += 1
        case_id = f"B-{counter:04d}"
        payload = {
            "case_id": case_id,
            "eval_id": case.eval_id,
            "question": case.question,
            "difficulty": case.difficulty,
            "scenario": case.scenario,
            "operators": case.operators,
            "gold_sql": case.gold_sql,
            "pred_sql": case.pred_sql,
            "initial_sql": case.initial_sql,
            "final_sql": case.final_sql,
            "exec_success": case.exec_success,
            "failure_stage": case.failure_stage,
            "error_type": case.error_type,
            "latency_ms": case.latency_ms,
            "repair_count": case.repair_count,
            "trace": case.trace_summary,
            "notes": "Task 13 评测失败自动沉淀；供 Task 14 分析",
        }
        (out_dir / f"{case_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return counter - base


def fail_summary_for_report(summary: EvalRunSummary) -> dict[str, Any]:
    return {
        "run_id": summary.meta.run_id,
        "timestamp": summary.meta.timestamp,
        "total": summary.total,
        "valid_model_runs": summary.valid_model_runs,
        "provider_failures": summary.provider_failures,
        "timeouts": summary.timeouts,
        "exec_rate": summary.exec_rate,
        "ex": summary.ex,
        "conditional_ex": summary.conditional_ex,
        "pass_at_1": summary.pass_at_1,
        "final_ex": summary.final_ex,
        "repair_trigger_rate": summary.repair_trigger_rate,
        "repair_success_rate": summary.repair_success_rate,
        "avg_latency_ms": summary.avg_latency_ms,
        "p50_latency_ms": summary.p50_latency_ms,
        "p95_latency_ms": summary.p95_latency_ms,
    }


def render_markdown(
    results: list[EvalCaseResult],
    summary: EvalRunSummary,
    meta: EvalRunMeta,
) -> str:
    o = summary
    lines: list[str] = []
    lines.append(f"# ECO-SQL-Bench 评测报告 · run {meta.run_id}")
    lines.append("")
    lines.append(f"- 时间：{meta.timestamp}")
    lines.append(f"- 模式：{meta.mode}")
    lines.append(f"- 数据集：{meta.dataset_version} / DB {meta.database_version} / Schema {meta.schema_version} / seed {meta.seed}")
    lines.append(f"- 模型：{meta.provider} / {meta.model}（base_url {meta.base_url}）")
    lines.append(f"- 随机性：{meta.randomness}")
    lines.append("")
    lines.append("## 总体")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| Total | {o.total} |")
    lines.append(f"| Valid Model Runs | {o.valid_model_runs} |")
    lines.append(f"| Provider Failures | {o.provider_failures} |")
    lines.append(f"| Timeouts | {o.timeouts} |")
    lines.append(f"| Exec Rate | {o.exec_rate}% |")
    lines.append(f"| Overall EX | {o.ex}% |")
    lines.append(f"| Conditional EX | {o.conditional_ex}% |")
    lines.append(f"| Pass@1(初始) | {o.pass_at_1}% |")
    lines.append(f"| Final EX(含Repair) | {o.final_ex}% |")
    lines.append(f"| Repair Trigger Rate | {o.repair_trigger_rate}% |")
    lines.append(f"| Repair Success Rate | {o.repair_success_rate}% |")
    lines.append(f"| Avg Latency | {o.avg_latency_ms} ms |")
    lines.append(f"| P50 Latency | {o.p50_latency_ms} ms |")
    lines.append(f"| P95 Latency | {o.p95_latency_ms} ms |")
    lines.append("")
    lines.append("## 按难度")
    lines.append("")
    lines.append("| difficulty | count | exec_rate% | EX% |")
    lines.append("|---|---:|---:|---:|")
    for d in ("easy", "medium", "hard", "extra_hard"):
        g = o.by_difficulty.get(d)
        if g:
            lines.append(f"| {d} | {g['count']} | {g['exec_rate']} | {g['ex']} |")
    lines.append("")
    lines.append("## 按场景")
    lines.append("")
    lines.append("| scenario | count | exec_rate% | EX% |")
    lines.append("|---|---:|---:|---:|")
    for s, g in o.by_scenario.items():
        lines.append(f"| {s} | {g['count']} | {g['exec_rate']} | {g['ex']} |")
    lines.append("")
    lines.append("## 按 Operator")
    lines.append("")
    lines.append("| operator | count | EX% |")
    lines.append("|---|---:|---:|")
    for op, g in o.by_operator.items():
        lines.append(f"| {op} | {g['count']} | {g['ex']} |")
    lines.append("")
    lines.append("## 失败分布")
    lines.append("")
    lines.append("| failure_stage | count |")
    lines.append("|---|---:|")
    for stage, cnt in o.failure_stages.items():
        lines.append(f"| {stage} | {cnt} |")
    lines.append("")
    lines.append("| error_type | count |")
    lines.append("|---|---:|")
    for et, cnt in o.error_types.items():
        lines.append(f"| {et} | {cnt} |")
    lines.append("")
    return "\n".join(lines)


def write_report_json(
    path: Path,
    meta: EvalRunMeta,
    results: list[EvalCaseResult],
    summary: EvalRunSummary,
) -> None:
    payload = {
        "meta": {
            **{
                k: getattr(meta, k)
                for k in ("run_id", "timestamp", "dataset_version", "database_version",
                          "schema_version", "seed", "model", "provider", "base_url",
                          "prompt_version", "fewshot_version", "experiment",
                          "randomness", "mode", "per_item_timeout_s", "total_items",
                          "prompt_sha256", "fewshot_sha256", "fewshot_path",
                          "dataset_sha256", "db_table_counts")
            },
        },
        "summary": fail_summary_for_report(summary),
        "results": write_case_results(results),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")