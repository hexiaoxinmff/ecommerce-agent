"""评测指标聚合（Task 13 唯一实现；对应 evaluation-plan §2）。

指标定义：
- Exec Rate = 最终 SQL 成功执行题数 / 总题数
- EX = 最终执行结果与 Gold 等价题数 / 总题数
- Conditional EX = 仅对 valid_model_runs（provider 成功返回模型输出）计算
- Pass@1 (初始) = repair_count==0 且结果正确题数 / 总题数
- Final EX = EX（含 repair，语义等价于 EX）
- Repair Trigger Rate = repair_triggered / total
- Repair Success Rate = repair_triggered 中最终正确数 / repair_triggered
- Latency：all / success / failure 三组，P50/P95/Avg/Min/Max

聚合维度：difficulty / scenario / operator（XX/清单形式可读）。
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

from evaluation.models import EvalCaseResult


def _pct(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(part * 100.0 / total, 2)


def _latency_stats(latencies: list[float]) -> dict[str, float]:
    if not latencies:
        return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    latencies = sorted(latencies)
    return {
        "count": len(latencies),
        "avg": round(statistics.mean(latencies), 2),
        "p50": round(latencies[len(latencies) * 50 // 100], 2),
        "p95": round(latencies[min(len(latencies) - 1, len(latencies) * 95 // 100)], 2),
        "min": round(latencies[0], 2),
        "max": round(latencies[-1], 2),
    }


def _group_stats(rows: list[EvalCaseResult]) -> dict[str, Any]:
    total = len(rows)
    exec_ok = sum(1 for r in rows if r.exec_success)
    ex = sum(1 for r in rows if r.execution_accuracy)
    valid = sum(1 for r in rows if r.valid_model_run)
    p1 = sum(1 for r in rows if r.repair_count == 0 and r.execution_accuracy)
    repair_triggered = sum(1 for r in rows if r.repair_triggered)
    repair_ok = sum(
        1 for r in rows if r.repair_triggered and r.execution_accuracy
    )
    return {
        "count": total,
        "valid_model_runs": valid,
        "provider_failures": sum(1 for r in rows if not r.valid_model_run),
        "timeouts": sum(1 for r in rows if r.error_type == "timeout"),
        "exec_rate": _pct(exec_ok, total),
        "ex": _pct(ex, total),
        "conditional_ex": _pct(ex, valid),
        "pass_at_1": _pct(p1, total),
        "repair_trigger_rate": _pct(repair_triggered, total),
        "repair_success_rate": (
            _pct(repair_ok, repair_triggered) if repair_triggered else 0.0
        ),
        "latency_ms": _latency_stats([r.latency_ms for r in rows]),
    }


def aggregate(
    results: list[EvalCaseResult],
) -> dict[str, Any]:
    """返回总体 + 按难度/场景/operator + 失败分布。"""
    total = len(results)
    valid = sum(1 for r in results if r.valid_model_run)
    exec_ok = sum(1 for r in results if r.exec_success)
    ex = sum(1 for r in results if r.execution_accuracy)
    p1 = sum(1 for r in results if r.repair_count == 0 and r.execution_accuracy)
    repair_triggered = sum(1 for r in results if r.repair_triggered)
    repair_ok = sum(
        1 for r in results if r.repair_triggered and r.execution_accuracy
    )

    by_difficulty: dict[str, list[EvalCaseResult]] = defaultdict(list)
    by_scenario: dict[str, list[EvalCaseResult]] = defaultdict(list)
    by_operator: dict[str, list[EvalCaseResult]] = defaultdict(list)
    for r in results:
        by_difficulty[r.difficulty].append(r)
        by_scenario[r.scenario].append(r)
        for op in r.operators:
            by_operator[op].append(r)

    return {
        "overall": {
            "total": total,
            "valid_model_runs": valid,
            "provider_failures": sum(1 for r in results if not r.valid_model_run),
            "timeouts": sum(1 for r in results if r.error_type == "timeout"),
            "exec_rate": _pct(exec_ok, total),
            # Exec Rate 双口径（Task 14.3 起，与 evaluation-plan §2 对齐）：
            # overall_exec_rate = 全部题中最终成功执行比例（分母=total）
            # valid_run_exec_rate = 有效模型运行中成功执行比例（分母=valid_model_runs）
            "overall_exec_rate": _pct(exec_ok, total),
            "valid_run_exec_rate": _pct(exec_ok, valid),
            "ex": _pct(ex, total),
            "conditional_ex": _pct(ex, valid),
            "pass_at_1": _pct(p1, total),
            "final_ex": _pct(ex, total),
            "repair_trigger_rate": _pct(repair_triggered, total),
            "repair_success_rate": (
                _pct(repair_ok, repair_triggered) if repair_triggered else 0.0
            ),
            "latency_ms": _latency_stats([r.latency_ms for r in results]),
            "latency_ms_all": _latency_stats([r.latency_ms for r in results]),
            "latency_ms_success": _latency_stats(
                [r.latency_ms for r in results if r.exec_success]
            ),
            "latency_ms_failure": _latency_stats(
                [r.latency_ms for r in results if not r.exec_success]
            ),
        },
        "by_difficulty": {
            d: _group_stats(rows) for d, rows in sorted(by_difficulty.items())
        },
        "by_scenario": {
            s: _group_stats(rows) for s, rows in sorted(by_scenario.items())
        },
        "by_operator": {
            op: _group_stats(rows) for op, rows in sorted(by_operator.items())
        },
        "failure_stages": dict(
            sorted(Counter(r.failure_stage or "none" for r in results).items())
        ),
        "error_types": dict(sorted(Counter(r.error_type or "none" for r in results).items())),
    }


def summarize_for_report(agg: dict[str, Any]) -> dict[str, Any]:
    """把 aggregate() 输出整理成报告友好的扁平摘要（供 report.py 使用）。"""
    return agg