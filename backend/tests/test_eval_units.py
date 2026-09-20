"""evaluation 包单元测试（离线，不依赖真实 Mimo）。

覆盖：
- normalization：scalar / 多行多列 / NULL / float tolerance / empty / Top-N /
  order_sensitive / 列顺序与行顺序不敏感 / 并列容忍
- metrics：Exec Rate / EX / Pass@1 / Repair / Latency / 难度聚合
- runner failure 分类：provider / timeout / sql_execution / result mismatch
- metrics 无网络依赖
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from evaluation.metrics import aggregate  # noqa: E402
from evaluation.models import EvalCaseResult  # noqa: E402
from evaluation.normalization import (  # noqa: E402
    compare_results,
    normalize_result,
)
from evaluation.runner import (  # noqa: E402
    EvalConfig,
    EvalCaseResult as _ECR,
    classify_failure,
    select_items,
)


# ---------------- Normalization ----------------


def test_norm_scalar():
    g = normalize_result(["region"], [["广东"]])
    p = normalize_result(["reg"], [["广东"]])
    assert compare_results(g, p).match is True
    p2 = normalize_result(["region"], [["北京"]])
    assert compare_results(g, p2).match is False


def test_norm_multirow_multicol_reorder():
    g = normalize_result(["region", "cnt"], [["广东", 246], ["北京", 246]])
    p = normalize_result(
        ["cnt", "region"], [[246, "北京"], [246, "广东"]]
    )
    assert compare_results(g, p).match is True


def test_norm_value_change():
    g = normalize_result(["region", "cnt"], [["广东", 246]])
    p = normalize_result(["region", "cnt"], [["广东", 999]])
    assert compare_results(g, p).match is False


def test_norm_null_not_zero():
    g = normalize_result(["v"], [[None]])
    p = normalize_result(["v"], [[0]])
    assert compare_results(g, p).match is False


def test_norm_float_tolerance_currency():
    g = normalize_result(["x"], [[24.97]], value_type="currency", tolerance=0.01)
    p = normalize_result(["x"], [[25.0]], value_type="currency", tolerance=0.01)
    assert compare_results(g, p, value_type="currency", tolerance=0.01).match is True
    far = normalize_result(["x"], [[30.0]], value_type="currency", tolerance=0.01)
    assert (
        compare_results(g, far, value_type="currency", tolerance=0.01).match is False
    )


def test_norm_empty_handling():
    g_empty = normalize_result(["v"], [], expected_empty=True)
    p_empty = normalize_result(["v"], [], expected_empty=True)
    assert compare_results(g_empty, p_empty).match is True
    p_non = normalize_result(["v"], [[1]])
    assert compare_results(g_empty, p_non).match is False


def test_norm_column_count_mismatch():
    g = normalize_result(["region"], [["广东"]])
    p = normalize_result(["region", "x"], [["广东", 1]])
    assert compare_results(g, p).match is False


def test_norm_topn_order_sensitive():
    g = normalize_result(
        ["name", "sold"], [["A", 10], ["B", 9]], order_sensitive=True
    )
    # 列序交换但名次键一致 → 通过
    p_ok = normalize_result(
        ["sold", "name"], [[10, "A"], [9, "B"]], order_sensitive=True
    )
    assert compare_results(g, p_ok, order_sensitive=True).match is True
    # 名次错位 → 失败
    p_bad = normalize_result(
        ["name", "sold"], [["B", 9], ["A", 10]], order_sensitive=True
    )
    assert compare_results(g, p_bad, order_sensitive=True).match is False


def test_norm_topn_tie_ignore_internal_order():
    g = normalize_result(
        ["name", "sold"], [["A", 5], ["B", 5]], order_sensitive=True
    )
    p = normalize_result(
        ["name", "sold"], [["B", 5], ["A", 5]], order_sensitive=True
    )
    assert compare_results(g, p, order_sensitive=True).match is True


# ---------------- Metrics ----------------

def _mk(eid, *, exec_success=True, ex=True, repair_triggered=False,
        repair_count=0, valid=True, latency=10.0,
        difficulty="easy", err_type=None, stage=None,
        error_type=None):
    return EvalCaseResult(
        eval_id=eid,
        question="q",
        difficulty=difficulty,
        scenario="sales_analysis",
        operators=["join"],
        gold_sql="SELECT 1",
        pred_sql="SELECT 1",
        exec_success=exec_success,
        execution_accuracy=ex,
        repair_triggered=repair_triggered,
        repair_count=repair_count,
        repair_success=bool(repair_triggered and ex),
        failure_stage=stage,
        error_type=error_type,
        latency_ms=latency,
        valid_model_run=valid,
    )


def test_metrics_basic():
    results = [
        _mk("E-0001", exec_success=True, ex=True, latency=10.0),
        _mk("E-0002", exec_success=True, ex=False, stage="result", error_type="result_mismatch", latency=20.0),
        _mk("E-0003", exec_success=False, ex=False, valid=False,
            stage="provider", error_type="LLMError", latency=5.0),
    ]
    agg = aggregate(results)
    o = agg["overall"]
    assert o["total"] == 3
    assert o["exec_rate"] == round(2 * 100 / 3, 2)
    assert o["ex"] == round(1 * 100 / 3, 2)
    assert o["conditional_ex"] == round(1 * 100 / 2, 2)
    assert o["valid_model_runs"] == 2
    assert o["provider_failures"] == 1
    assert o["pass_at_1"] == round(1 * 100 / 3, 2)


def test_metrics_repair():
    results = [
        _mk("E-0001", repair_triggered=True, repair_count=1, ex=True),
        _mk("E-0002", repair_triggered=True, repair_count=1, ex=False, stage="sql_repair", error_type="x"),
        _mk("E-0003", exec_success=False, ex=False, valid=False, stage="provider", error_type="LLMError"),
    ]
    agg = aggregate(results)
    o = agg["overall"]
    assert o["repair_trigger_rate"] == round(2 * 100 / 3, 2)
    assert o["repair_success_rate"] == round(1 * 100 / 2, 2)


def test_metrics_latency():
    results = [_mk(f"E-{i:04d}", latency=float(i)) for i in (1, 2, 3, 4, 5)]
    agg = aggregate(results)
    p50 = agg["overall"]["latency_ms"]["p50"]
    p95 = agg["overall"]["latency_ms"]["p95"]
    assert p50 == 3.0
    assert p95 == 5.0


def test_metrics_by_difficulty():
    results = [
        _mk("E-0001", difficulty="easy", ex=True),
        _mk("E-0002", difficulty="medium", ex=False, stage="result", error_type="result_mismatch"),
        _mk("E-0003", difficulty="hard", ex=False, stage="result", error_type="result_mismatch"),
    ]
    agg = aggregate(results)
    assert agg["by_difficulty"]["easy"]["ex"] == 100.0
    assert agg["by_difficulty"]["medium"]["ex"] == 0.0


# ---------------- Runner helpers ----------------


class _SimpleAgentResult:
    def __init__(self, **kw):
        self.success = kw.get("success", True)
        self.generated_sql = kw.get("generated_sql", "SELECT 1")
        self.repaired_sql = kw.get("repaired_sql", "")
        self.execution_result = kw.get("execution_result")
        self.execution_error = kw.get("execution_error", "")
        self.repair_reason = kw.get("repair_reason", "")
        self.repair_error = kw.get("repair_error", "")
        self.execute_count = kw.get("execute_count", 1)
        self.repair_count = kw.get("repair_count", 0)
        self.final_error = kw.get("final_error", "")
        self.trace = kw.get("trace", [])
        self.total_time_ms = kw.get("total_time_ms", 50.0)
        self.http_status = kw.get("http_status")
        self.error_type = kw.get("error_type", "")


def test_failure_classification_provider():
    r = _SimpleAgentResult(success=False, error_type="LLMError", final_error="API timeout")
    stage, err = classify_failure(r)
    assert stage == "provider"
    assert err == "LLMError"


def test_failure_classification_safety():
    r = _SimpleAgentResult(success=False, final_error="SQL Safety Rejected: ...")
    stage, err = classify_failure(r)
    assert stage == "sql_safety"


def test_failure_classification_repair():
    r = _SimpleAgentResult(success=False, repair_count=1, execution_error="no such table")
    stage, err = classify_failure(r)
    assert stage == "sql_repair"


def test_failure_classification_execute():
    r = _SimpleAgentResult(success=False, execution_error="syntax error")
    stage, err = classify_failure(r)
    assert stage == "sql_execute"


def test_select_items():
    items = [
        {"id": "E-0001", "difficulty": "easy"},
        {"id": "E-0002", "difficulty": "medium"},
        {"id": "E-0003", "difficulty": "easy"},
    ]
    assert [i["id"] for i in select_items(items, ids=["E-0002"])] == ["E-0002"]
    assert [i["id"] for i in select_items(items, difficulties=["easy"])] == ["E-0001", "E-0003"]
    assert len(select_items(items, limit=2)) == 2


def test_classes_importable():
    from evaluation import metrics as m
    from evaluation import report as r
    from evaluation import runner
    assert m is not None and r is not None and runner is not None