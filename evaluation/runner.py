"""评测 Runner 核心：Gold Hash Gate → 逐题调用真实 Agent → EX 判定 → Bad Case 沉淀。

设计要点：
- 直接调用 app.agent.graph.run_agent(question)（真实 Agent，不含 HTTP 开销）；
- Pred SQL 选择（任务书 §12）：repair_count==0 → generated_sql；
  repair_count>0 且最终成功执行 → repaired_sql；否则回落 generated_sql；
- Gold Result 由 gold_sql 在真实只读库上执行 + 规范化得到（与 spec §D 一致）；
- EX 判定：归一化后值比较（compare_results），绝不用 gold_result_hash 判定正确；
  gold_result_hash 仅用于 Hash Gate（防漂移）；
- 失败归因：基于 AgentResult.error_type / final_error / execution_error 推断
  failure_stage + error_type，绝不统一 agent_error；
- 串行执行；单题超时判定由外部（run_eval.py）用线程/信号包裹，本模块记录 timeout；
- Provider 网络类失败单独标记 valid_model_run=False；
- 本模块不做 LLM token 统计（Agent 未暴露），报告标记 not available。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.agent.graph import run_agent
from app.core import config
from app.sqlexec.executor import execute as safe_execute
from app.sqlexec.models import SQLExecutionResult

from evaluation.models import EvalCaseResult, EvalRunMeta
from evaluation.normalization import compare_results, gold_hash, normalize_result

TIMEOUT_TAG = "timeout"
# Runner 级 retry 只针对明显的网络瞬态错误（由运行入口触发 retry 回调）
PROVIDER_ERROR_HINTS = (
    "ConnectionError",
    "APIConnectionError",
    "Timeout",
    "ConnectTimeout",
    "ReadTimeout",
    "APITimeoutError",
)

# 真正的 provider / infrastructure 失败（LLM 层异常；节点包装器将 error_type 写为异常类名）
PROVIDER_ERROR_NAMES = frozenset(
    {
        "LLMError",
        "LLMApiKeyNotConfiguredError",
        "LLMAuthenticationError",
        "LLMInsufficientBalanceError",
        "LLMRateLimitError",
        "LLMServiceUnavailableError",
        "LLMTimeoutError",
        "LLMNetworkError",
        "LLMProviderNotConfiguredError",
    }
)


def classify_provider_failure(err_type: str, final_error: str) -> tuple[bool, str]:
    """显式区分 provider / infrastructure 失败。

    Returns (is_provider_failure, failure_tag)：
    - 超时（error_type 含 timeout，或 final_error 含 timeout/timed out）→ provider + timeout；
    - LLM 族异常（网络/认证/限流/5xx/Key 未配置）→ provider_failure；
    - 其余（模型生成/校验/安全/执行错误）→ 非 provider（计入模型自身能力分母）。
    """
    low_type = (err_type or "").lower()
    low_final = (final_error or "").lower()
    if "timeout" in low_type or "timeout" in low_final or "timed out" in low_final:
        return True, TIMEOUT_TAG
    if err_type in PROVIDER_ERROR_NAMES:
        return True, err_type
    return False, ""


class GoldHashGateError(Exception):
    """Gold Hash Gate 失败（数据漂移），禁止继续评测。"""


@dataclass
class EvalConfig:
    db_path: Path = config.DB_PATH
    dataset_path: Path = Path("data/eval/ecommerce_eval_v1.json")
    timeout_s: float = 60.0
    max_retries: int = 1
    enable_gold_hash_gate: bool = True
    agent_runner: Callable[[str], Any] = run_agent
    sql_executor: Callable[[str], SQLExecutionResult] = safe_execute

    def __post_init__(self):
        if self.dataset_path is not None and not Path(self.dataset_path).is_absolute():
            self.dataset_path = Path(self.dataset_path)
        if not self.db_path.is_absolute():
            self.db_path = Path(self.db_path)


def _read_dataset(path: Path) -> list[dict[str, Any]]:
    import json

    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["items"]


def select_items(
    items: list[dict[str, Any]],
    *,
    ids: list[str] | None = None,
    difficulties: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """按参数筛选条目（ids 优先；否则 difficulties；最后 limit 截断）。"""
    if ids:
        wanted = set(ids)
        return [i for i in items if i["id"] in wanted]
    if difficulties:
        wanted = set(difficulties)
        out = [i for i in items if i["difficulty"] in wanted]
    else:
        out = list(items)
    if limit is not None and limit > 0:
        out = out[:limit]
    return out


# ---------------- Gold Hash Gate ----------------


def compute_gold_hash_gate(
    items: list[dict[str, Any]], config: EvalConfig
) -> dict[str, str]:
    """重新计算全部条目 gold_result_hash 并与记录比对；不匹配抛 GoldHashGateError。"""
    mismatches: list[str] = []
    recomputed: dict[str, str] = {}
    uri = f"file:{config.db_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        for item in items:
            try:
                cur = conn.execute(item["gold_sql"])
                h = gold_hash(
                    [col[0] for col in cur.description],
                    [list(r) for r in cur.fetchall()],
                )
            except Exception as exc:  # noqa: BLE001
                mismatches.append(f"{item['id']}: gold_sql 执行失败 {exc}")
                continue
            recomputed[item["id"]] = h
            if h != item.get("gold_result_hash"):
                mismatches.append(
                    f"{item['id']}: hash 不一致（记录 {str(item.get('gold_result_hash',''))[:12]} vs 实际 {h[:12]}）"
                )
    if mismatches:
        raise GoldHashGateError(
            "Gold Hash Gate 失败：存在 hash 漂移，禁止评测。\n" + "\n".join(mismatches)
        )
    return recomputed


# ---------------- 规范化辅助 ----------------


def _slots(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("answer_slots") or {}


def _gold_normalized(config: EvalConfig, item: dict[str, Any]):
    s = _slots(item)
    result = config.sql_executor(item["gold_sql"])
    return normalize_result(
        result.columns,
        result.rows,
        value_type=str(s.get("value_type", "")),
        tolerance=float(s.get("tolerance") or 0.0),
        order_sensitive=bool(s.get("order_sensitive", False)),
        expected_empty=bool(s.get("expected_empty", False)),
    )


def _pred_normalized(exec_result: SQLExecutionResult, item: dict[str, Any]):
    s = _slots(item)
    return normalize_result(
        exec_result.columns,
        exec_result.rows,
        value_type=str(s.get("value_type", "")),
        tolerance=float(s.get("tolerance") or 0.0),
        order_sensitive=bool(s.get("order_sensitive", False)),
        expected_empty=bool(s.get("expected_empty", False)),
    )


# ---------------- 失败归因 ----------------


def classify_failure(result: Any) -> tuple[str | None, str | None]:
    """根据 AgentResult 推断 (failure_stage, error_type)；执行成功返回 (None, None)。

    Provider 级错误（error_type 非空 = 节点层异常）单独标记，
    与 SQL 逻辑错误严格区分。
    """
    error_type = getattr(result, "error_type", "") or ""
    final_error = getattr(result, "final_error", "") or ""
    execution_error = getattr(result, "execution_error", "") or ""
    repair_count = getattr(result, "repair_count", 0) or 0
    success = bool(getattr(result, "success", False))

    # Provider / 网络 / 认证 等节点异常（error_type 由节点包装器写入）
    if error_type:
        if any(hint in error_type for hint in ("Timeout", "Connection", "APIError")):
            return "provider", error_type
        return "provider", error_type

    # SQL Safety 拒绝（生成阶段或执行阶段）
    if not success and "Safety" in final_error:
        return "sql_safety", final_error[:120]

    # Repair 失败
    if repair_count > 0 and not success:
        return "sql_repair", (execution_error or repair_error_of(result))[:120]

    # 执行失败（数据库错误）
    if not success and execution_error:
        return "sql_execute", execution_error[:120]

    # 生成失败（无 SQL）
    if not success:
        return "sql_generate", final_error[:120]

    return None, None


def repair_error_of(result: Any) -> str:
    return getattr(result, "repair_error", "") or ""


def _pick_pred_sql(result: Any) -> str:
    """按任务书 §12 选择 Pred SQL。"""
    generated = getattr(result, "generated_sql", "") or ""
    repaired = getattr(result, "repaired_sql", "") or ""
    success = bool(getattr(result, "success", False))
    repair_count = getattr(result, "repair_count", 0) or 0
    if repair_count > 0 and success and repaired:
        return repaired
    return generated


def _sanitize_trace(trace: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in trace or []:
        if isinstance(event, dict):
            item = event
        else:
            item = getattr(event, "model_dump", lambda: {})() or {}
        out.append(
            {
                "node": item.get("node", ""),
                "status": item.get("status", ""),
                "duration_ms": item.get("duration_ms", 0),
                "message": str(item.get("message", ""))[:300],
                "output_summary": item.get("output_summary", {}),
            }
        )
    return out


def _trace_summary(trace: list[Any]) -> str:
    return ";".join(
        f"{e['node']}:{e['status']}" for e in _sanitize_trace(trace)
    ) or ""


# ---------------- 单题评测 ----------------


def eval_single_item(
    item: dict[str, Any],
    config: EvalConfig,
) -> EvalCaseResult:
    """对单条评测条目执行完整流程，返回 EvalCaseResult。"""
    s = _slots(item)
    value_type = str(s.get("value_type", ""))
    tolerance = float(s.get("tolerance") or 0.0)
    order_sensitive = bool(s.get("order_sensitive", False))

    # 1) Gold 规范化结果
    try:
        gold_result = config.sql_executor(item["gold_sql"])
        gold_norm = normalize_result(
            gold_result.columns,
            gold_result.rows,
            value_type=value_type,
            tolerance=tolerance,
            order_sensitive=order_sensitive,
            expected_empty=bool(s.get("expected_empty", False)),
        )
    except Exception as exc:  # noqa: BLE001
        # Gold 本身执行失败：基准异常
        return EvalCaseResult(
            eval_id=item["id"],
            question=item["question"],
            difficulty=item["difficulty"],
            scenario=item["scenario"],
            operators=list(item.get("operators", [])),
            gold_sql=item["gold_sql"],
            pred_sql="",
            exec_success=False,
            execution_accuracy=False,
            valid_model_run=True,
            failure_stage="gold_execute",
            error_type=f"gold_sql error: {exc}",
            latency_ms=0.0,
            trace_summary="gold 执行失败",
        )

    # 2) 调用 Agent（Runner-level 有限重试：仅网络瞬态，≤1 次）
    result = None
    last_exc: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            result = config.agent_runner(item["question"])
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            result = None
            if attempt >= config.max_retries:
                break

    latency_ms = float(getattr(result, "total_time_ms", 0.0) or 0.0)
    if result is None:
        # Agent 整体调用失败（网络贯穿全部重试）
        return EvalCaseResult(
            eval_id=item["id"],
            question=item["question"],
            difficulty=item["difficulty"],
            scenario=item["scenario"],
            operators=list(item.get("operators", [])),
            gold_sql=item["gold_sql"],
            pred_sql="",
            initial_sql="",
            final_sql="",
            exec_success=False,
            execution_accuracy=False,
            valid_model_run=False,
            failure_stage="provider",
            error_type=(type(last_exc).__name__ if last_exc else "provider_error"),
            latency_ms=latency_ms,
            trace_summary=f"agent call failed: {last_exc}" if last_exc else "",
        )

    success = bool(getattr(result, "success", False))
    exec_result = getattr(result, "execution_result", None)
    repair_count = int(getattr(result, "repair_count", 0) or 0)
    generated_sql = getattr(result, "generated_sql", "") or ""
    repaired_sql = getattr(result, "repaired_sql", "") or ""
    pred_sql = _pick_pred_sql(result)

    # 3) Provider / infrastructure 级失败判定（显式分类：仅 LLM 族异常与超时）
    err_type = getattr(result, "error_type", "") or ""
    final_err_text = str(getattr(result, "final_error", "")) or ""
    is_provider_failure, provider_tag = classify_provider_failure(err_type, final_err_text)
    is_timeout = provider_tag == TIMEOUT_TAG

    exec_success = bool(success and exec_result is not None)

    # 4) EX 判定
    ex = False
    failure_stage: str | None = None
    error_type_val: str | None = None

    if exec_success and not is_provider_failure:
        pred_norm = _pred_normalized(exec_result, item)
        outcome = compare_results(
            gold_norm,
            pred_norm,
            value_type=value_type,
            tolerance=tolerance,
            order_sensitive=order_sensitive,
        )
        ex = outcome.match
        if not ex:
            failure_stage = "result"
            error_type_val = "result_mismatch"
    else:
        failure_stage, error_type_val = classify_failure(result)
        if is_provider_failure:
            failure_stage = "provider"
            error_type_val = provider_tag
        elif failure_stage in (None, "provider") and err_type:
            # 模型生成/校验类失败（如 SQLGenSchemaMismatchError）→ 归为模型自身失败，
            # 不是 provider / infrastructure 失败（计入 Conditional EX 分母）
            failure_stage = "sql_generation"
            error_type_val = err_type

    final_sql = repaired_sql if repair_count > 0 else generated_sql
    if exec_success and not final_sql:
        final_sql = pred_sql

    return EvalCaseResult(
        eval_id=item["id"],
        question=item["question"],
        difficulty=item["difficulty"],
        scenario=item["scenario"],
        operators=list(item.get("operators", [])),
        gold_sql=item["gold_sql"],
        pred_sql=pred_sql,
        initial_sql=generated_sql,
        final_sql=final_sql,
        exec_success=exec_success,
        execution_accuracy=ex,
        repair_triggered=repair_count > 0,
        repair_count=repair_count,
        repair_success=bool(repair_count > 0 and ex),
        failure_stage=failure_stage,
        error_type=error_type_val,
        latency_ms=latency_ms,
        valid_model_run=not is_provider_failure,
        trace_summary=_trace_summary(getattr(result, "trace", [])),
        trace=_sanitize_trace(getattr(result, "trace", [])),
    )


def database_file_hash(config: EvalConfig) -> str:
    import hashlib

    return hashlib.sha256(config.db_path.read_bytes()).hexdigest()