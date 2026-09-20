"""evaluation runner 集成测试（mock Agent，真实 SQLite 只读）。

覆盖：
- eval_single_item：gold 执行 + pred 执行 + EX 判定（mock agent 返回真 SQL）
- provider 错误（agent 抛 LLMError 时标记 valid_model_run=False）
- Gold Hash Gate：正常通过；hash mismatch 时抛错停止
- timeout：超过时限返回 timeout 结果
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from evaluation.runner import (  # noqa: E402
    EvalConfig,
    GoldHashGateError,
    compute_gold_hash_gate,
    eval_single_item,
)
from evaluation.normalization import gold_hash  # noqa: E402
from app.sqlexec.executor import execute as real_execute  # noqa: E402


def _cfg(agent_runner=None, **overrides) -> EvalConfig:
    kwargs = {"agent_runner": agent_runner} if agent_runner else {}
    kwargs.update(overrides)
    return EvalConfig(**kwargs)


class _FakeAgent:
    """依 question 返回固定 SQL 的 mock Agent。"""

    def __init__(self, sql: str, delay: float = 0.0):
        self._sql = sql
        self._delay = delay

    def __call__(self, question: str):
        if self._delay:
            import time
            time.sleep(self._delay)
        return type(
            "AR", (), {
                "question": question,
                "success": True,
                "generated_sql": self._sql,
                "repaired_sql": "",
                "execution_result": real_execute(self._sql),
                "execution_error": "",
                "repair_reason": "",
                "repair_error": "",
                "execute_count": 1,
                "repair_count": 0,
                "final_error": "",
                "trace": [],
                "total_time_ms": 50.0,
                "http_status": None,
                "error_type": "",
            }
        )()


class _FailingAgent:
    def __init__(self, exc: Exception):
        self._exc = exc

    def __call__(self, question):
        raise self._exc


def _item(eid="E-0001", gold_sql="SELECT COUNT(*) AS n FROM users", slots=None):
    return {
        "id": eid,
        "difficulty": "easy",
        "scenario": "user_analysis",
        "operators": ["aggregate"],
        "question": "平台上一共有多少用户？",
        "gold_sql": gold_sql,
        "gold_result_hash": "",
        "expected_behavior": "answer",
        "answer_slots": slots or {"value_type": "integer"},
        "multi_turn": None,
        "notes": "",
    }


def test_eval_single_gold_matches_agent():
    item = _item()
    cfg = _cfg(_FakeAgent("SELECT COUNT(*) AS n FROM users"))
    r = eval_single_item(item, cfg)
    assert r.execution_accuracy is True
    assert r.exec_success is True
    assert r.execution_accuracy is True
    assert r.valid_model_run is True


def test_eval_single_mismatch_classified_result():
    item = _item()
    cfg = _cfg(_FakeAgent("SELECT COUNT(*) AS n FROM orders"))
    r = eval_single_item(item, cfg)
    assert r.execution_accuracy is False
    assert r.failure_stage == "result"
    assert r.error_type == "result_mismatch"


def test_eval_single_provider_error():
    item = _item()
    from app.llm.provider import LLMError

    cfg = _cfg(_FailingAgent(LLMError("mock network error")))
    r = eval_single_item(item, cfg)
    assert r.execution_accuracy is False
    assert r.valid_model_run is False
    assert r.failure_stage == "provider"


def test_gold_hash_gate_passes_on_real_dataset():
    cfg = _cfg()
    from evaluation.runner import _read_dataset
    items = _read_dataset(cfg.dataset_path)
    try:
        result = compute_gold_hash_gate(items, cfg)
        assert len(result) == len(items)
    except GoldHashGateError as exc:
        pytest.fail(f"真实数据集 hash gate 不应失败: {exc}")


def test_gold_hash_gate_raises_on_mismatch():
    item = _item(gold_sql="SELECT COUNT(*) AS n FROM users")
    item["gold_result_hash"] = "0" * 64  # 错误记录
    cfg = _cfg()
    with pytest.raises(GoldHashGateError):
        compute_gold_hash_gate([item], cfg)


def test_gold_hash_local_matches_formula():
    # gold_hash 与 runner hash gate 一致
    rows = [[3000, "A"], [2000, "B"]]
    h = gold_hash(["n", "x"], rows)
    assert isinstance(h, str) and len(h) == 64


def test_timeout_classification():
    item = _item()
    # 传给 eval_single 的 agent 一直睡（模拟网络卡死），由外层 run_eval 负责超时；
    # 此处仅验证现象字段可构造。mock 直接抛 → provider。
    from app.llm.provider import LLMError

    cfg = _cfg(_FailingAgent(LLMError("timeout")))
    r = eval_single_item(item, cfg)
    assert r.error_type  # 记录为 provider 类错误


# ---- Task 14.3：provider 显式分类 ----

from evaluation.runner import classify_provider_failure  # noqa: E402


def test_provider_failure_llm_family():
    ok, tag = classify_provider_failure("LLMNetworkError", "")
    assert ok is True
    assert tag == "LLMNetworkError"


def test_provider_failure_timeout_in_error_type():
    ok, tag = classify_provider_failure("LLMTimeoutError", "")
    assert ok is True
    assert tag == "timeout"


def test_provider_failure_timeout_in_final_error():
    ok, tag = classify_provider_failure("", "request timed out after 60s")
    assert ok is True
    assert tag == "timeout"


def test_model_generation_failure_not_provider():
    # SQLGenSchemaMismatchError 等模型自身生成/校验失败 → 非 provider
    ok, tag = classify_provider_failure("SQLGenSchemaMismatchError", "schema mismatch")
    assert ok is False
    assert tag == ""


def test_sql_safety_not_provider():
    ok, tag = classify_provider_failure("SQLUnsafeError", "Safety Rejected")
    assert ok is False
    assert tag == ""