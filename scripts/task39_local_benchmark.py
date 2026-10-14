#!/usr/bin/env python
"""Task 39-L：本地大模型 E2E Benchmark（engineering benchmark，非生产链路）。

定位
----
    Local LLM result  !=  Mimo production result

本脚本是一条**独立的本地测试线路**，用于在 Mimo provider 不可用期间验证
Text2SQL 流水线是否端到端可跑，并测量：

    EX / Exec / SQL Execution Accuracy
    mean / P50 / P95 / min / max E2E latency
    provider latency（模型推理）
    agent non-LLM latency（Agent 自身开销）

生产隔离（硬约束）
------------------
- **不修改** ``scripts/run_eval.py``（冻结语义原样保留）；
- **不修改** ``get_llm_provider()`` / ``mimo.py`` / 生产 Prompt / Few-shot
  / Benchmark / DB / Candidate A / Task 36 / Task 38；
- provider 通过 **组件注入**（``AgentComponents``）直接进入 Agent，
  完全绕过 ``get_llm_provider()``；
- 结果写 ``reports/task39_local_llm_e2e.{json,md}``，与冻结基线目录分离。

用法
----
    .venv/Scripts/python.exe scripts/task39_local_benchmark.py --limit 3
    .venv/Scripts/python.exe scripts/task39_local_benchmark.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.agent.graph import build_agent  # noqa: E402
from app.agent.models import AgentResult  # noqa: E402
from app.agent.nodes import AgentComponents, build_agent_result  # noqa: E402
from app.fewshot.retriever import FewShotRetriever  # noqa: E402
from app.llm.local_provider import (  # noqa: E402
    DEFAULT_BASE_URL,
    LocalProvider,
    is_embedding_model,
    list_models,
)
from app.schema.linker import SchemaLinker  # noqa: E402
from app.sqlgen.generator import SQLGenerator  # noqa: E402
from app.sqlrepair.repairer import SQLRepairer  # noqa: E402
from app.sqlexec.executor import execute as executor_execute  # noqa: E402

from evaluation.models import EvalCaseResult  # noqa: E402
from evaluation.runner import (  # noqa: E402
    EvalConfig,
    GoldHashGateError,
    compute_gold_hash_gate,
    database_file_hash,
    eval_single_item,
)

FROZEN_BASELINE = {
    "run_id": "20260916_09876",
    "prompt_sha256": "10583478b3a7d972865050501cd6e4b9062531503f1c3852cdd79cbf66f796d5",
    "fewshot_sha256": "ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee",
    "dataset_sha256": "dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a",
    "ex": 90.0,
    "exec_rate": 99.0,
    "avg_latency_ms": 10876.08,
    "p50_latency_ms": 10488.92,
    "p95_latency_ms": 15440.79,
}

EIGHT_SECOND_TARGET_MS = 8000.0


# ---------------- provider 注入 ----------------

class LocalAgentRunner:
    """把 LocalProvider 注入 Agent 图，并按题记录 E2E 耗时。

    图只编译一次（``build_agent`` 实测约 29 ms），与生产路径
    ``get_default_graph()`` 的进程级缓存语义一致，避免把编译开销
    计入每题的 E2E 延迟。
    """

    def __init__(self, provider: LocalProvider, components: AgentComponents) -> None:
        self.provider = provider
        self.components = components
        self.graph = build_agent(components)
        # 每次 invoke 追加一条记录。**账目必须记在 runner 内部**：
        # 单题超时后线程会被放弃，若在外部用「前后差值」记账，
        # 被放弃请求的 provider 调用会落到下一题头上（实测污染出
        # non_llm_ms = -300014 这种负数）。
        self.records: list[dict[str, Any]] = []

    def __call__(self, question: str) -> AgentResult:
        calls_before = self.provider.stats.calls
        ms_before = self.provider.stats.total_ms
        start = time.perf_counter()
        final_state = self.graph.invoke({"question": question})
        total_ms = round((time.perf_counter() - start) * 1000.0, 2)
        data = build_agent_result(final_state)
        data["total_time_ms"] = total_ms
        self.records.append(
            {
                "question": question,
                "total_e2e_ms": total_ms,
                "provider_calls": self.provider.stats.calls - calls_before,
                "provider_ms": round(self.provider.stats.total_ms - ms_before, 2),
                "success": data.get("success", False),
            }
        )
        return AgentResult(**data)


def build_local_components(provider: LocalProvider) -> AgentComponents:
    """用本地 provider 装配 Agent 组件（不触碰生产工厂）。"""
    schema_linker = SchemaLinker(provider=provider)
    fewshot_retriever = FewShotRetriever()
    sql_generator = SQLGenerator(
        provider=provider,
        schema_linker=schema_linker,
        fewshot_retriever=fewshot_retriever,
    )
    sql_repairer = SQLRepairer(provider=provider, fewshot_retriever=fewshot_retriever)
    return AgentComponents(
        schema_linker=schema_linker,
        fewshot_retriever=fewshot_retriever,
        sql_generator=sql_generator,
        sql_executor=executor_execute,
        sql_repairer=sql_repairer,
    )


# ---------------- 单题（带超时保护，与 run_eval.py 同构） ----------------

def run_one(
    item: dict[str, Any],
    cfg: EvalConfig,
    timeout_s: float,
    *,
    abandon_wait_s: float = 900.0,
) -> tuple[EvalCaseResult, bool, bool]:
    """跑单题；返回 (结果, 是否超时, 放弃线程是否仍未结束)。

    超时后**必须等被放弃的线程真正结束**再进入下一题：Ollama 默认
    ``OLLAMA_NUM_PARALLEL=1``，残留请求会独占推理槽位，既拖慢下一题，
    也会把它的 provider 调用算到下一题账上。
    """
    holder: dict[str, Any] = {}

    def _wrapped() -> None:
        try:
            holder["r"] = eval_single_item(item, cfg)
        except Exception as exc:  # noqa: BLE001
            holder["e"] = exc

    thread = threading.Thread(target=_wrapped, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)
    timed_out = thread.is_alive()
    if timed_out:
        # 放弃结果，但等它收尾，保证后续测量不被污染
        thread.join(timeout=abandon_wait_s)
        return (
            EvalCaseResult(
                eval_id=item["id"],
                question=item["question"],
                difficulty=item["difficulty"],
                scenario=item["scenario"],
                operators=list(item.get("operators", [])),
                gold_sql=item["gold_sql"],
                exec_success=False,
                execution_accuracy=False,
                valid_model_run=False,
                failure_stage="provider",
                error_type="timeout",
                latency_ms=timeout_s * 1000.0,
                trace_summary="timeout",
            ),
            True,
            thread.is_alive(),
        )
    if "e" in holder:
        exc = holder["e"]
        return (
            EvalCaseResult(
                eval_id=item["id"],
                question=item["question"],
                difficulty=item["difficulty"],
                scenario=item["scenario"],
                operators=list(item.get("operators", [])),
                gold_sql=item["gold_sql"],
                exec_success=False,
                execution_accuracy=False,
                valid_model_run=False,
                failure_stage="provider",
                error_type=type(exc).__name__,
                latency_ms=0.0,
                trace_summary=str(exc)[:200],
            ),
            False,
            False,
        )
    return holder["r"], False, False


# ---------------- 统计 ----------------

def _pct(part: int, total: int) -> float:
    return round(part * 100.0 / total, 2) if total else 0.0


def _lat_stats(values: list[float]) -> dict[str, float]:
    """分位数口径与冻结基线一致：sorted[n*q//100]（非插值）。"""
    if not values:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(statistics.mean(ordered), 2),
        "p50": round(ordered[len(ordered) * 50 // 100], 2),
        "p95": round(ordered[min(len(ordered) - 1, len(ordered) * 95 // 100)], 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
    }


def summarize(
    results: list[EvalCaseResult],
    per_item: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(results)
    exec_ok = sum(1 for r in results if r.exec_success)
    ex = sum(1 for r in results if r.execution_accuracy)
    valid = sum(1 for r in results if r.valid_model_run)
    repair_total = sum(r.repair_count for r in results)
    repair_triggered = sum(1 for r in results if r.repair_triggered)

    e2e = [float(p["total_e2e_ms"]) for p in per_item]
    prov = [float(p["provider_ms"]) for p in per_item if p["provider_ms"] is not None]
    non_llm = [float(p["non_llm_ms"]) for p in per_item if p["non_llm_ms"] is not None]

    return {
        "n": total,
        "success": exec_ok,
        "failed": total - exec_ok,
        "provider_failures": total - valid,
        "valid_model_runs": valid,
        "timeouts": sum(1 for r in results if r.error_type == "timeout"),
        "ex": _pct(ex, total),
        "conditional_ex": _pct(ex, valid),
        "exec_rate": _pct(exec_ok, total),
        "sql_execution_accuracy": _pct(ex, total),
        "repair_count": repair_total,
        "repair_triggered_items": repair_triggered,
        "provider_calls": sum(int(p["provider_calls"]) for p in per_item if p["provider_calls"] is not None),
        "e2e_latency_ms": _lat_stats(e2e),
        "provider_latency_ms": _lat_stats(prov),
        "non_llm_latency_ms": _lat_stats(non_llm),
    }


# ---------------- 主流程 ----------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Task 39-L local LLM E2E benchmark")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--model", default="", help="留空 = 按 provider 列表顺序自动选择第一个非 embedding 模型")
    p.add_argument("--ids", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--skip-hash-gate", action="store_true")
    p.add_argument("--out-json", default=str(PROJECT_ROOT / "reports" / "task39_local_llm_e2e.json"))
    p.add_argument("--out-md", default=str(PROJECT_ROOT / "reports" / "task39_local_llm_e2e.md"))
    p.add_argument("--write-report", action="store_true", help="写出 JSON/MD 报告")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # ---- 1) 本地 provider 发现（不调用 chat completion） ----
    print("=== Local provider discovery ===", flush=True)
    try:
        model_ids = list_models(args.base_url, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        print(f"[LOCAL_PROVIDER_UNAVAILABLE] {type(exc).__name__}: {exc}", flush=True)
        return 5
    print(f"endpoint      : {args.base_url}", flush=True)
    print(f"models        : {model_ids}", flush=True)

    chosen = args.model or ""
    if not chosen:
        for model_id in model_ids:
            if not is_embedding_model(model_id):
                chosen = model_id
                break
    if not chosen:
        print("[LOCAL_PROVIDER_UNAVAILABLE] 无可用非 embedding 模型", flush=True)
        return 5
    print(f"selected model: {chosen}", flush=True)

    provider = LocalProvider(base_url=args.base_url, model=chosen)
    components = build_local_components(provider)
    runner = LocalAgentRunner(provider, components)

    # ---- 2) 数据集 + 冻结闸门 ----
    cfg = EvalConfig(timeout_s=args.timeout, max_retries=1, enable_gold_hash_gate=False)
    cfg.agent_runner = runner
    items = json.loads(cfg.dataset_path.read_text(encoding="utf-8"))["items"]

    from scripts.check_benchmark_leakage import check_leakage  # noqa: PLC0415

    fewshot_items = json.loads(
        (PROJECT_ROOT / "data" / "fewshot" / "ecommerce_examples.json").read_text(encoding="utf-8")
    )
    leak = check_leakage(fewshot_items, items)
    if leak:
        print("[FATAL] Benchmark Leakage Gate 失败", flush=True)
        return 4
    print("Benchmark Leakage Gate: PASS", flush=True)

    if not args.skip_hash_gate:
        try:
            compute_gold_hash_gate(items, cfg)
            print("Gold Hash Gate: PASS (100/100)", flush=True)
        except GoldHashGateError as exc:
            print(f"[FATAL] {exc}", flush=True)
            return 2

    sel = items
    if args.ids:
        wanted = {i for i in args.ids.split(",") if i}
        sel = [i for i in sel if i["id"] in wanted]
    if args.limit:
        sel = sel[: args.limit]

    # ---- 3) 串行执行 ----
    db_before = database_file_hash(cfg)
    results: list[EvalCaseResult] = []
    per_item: list[dict[str, Any]] = []
    compromised = 0
    t0 = time.perf_counter()
    for idx, item in enumerate(sel, 1):
        rec_before = len(runner.records)
        result, timed_out, abandoned = run_one(item, cfg, args.timeout)
        rec = runner.records[rec_before] if len(runner.records) > rec_before else None
        if rec is None:
            # 放弃线程在等待窗口内仍未结束：本题的 provider 耗时不可知
            compromised += 1
            calls, prov_ms = None, None
            e2e_ms = round(float(result.latency_ms or 0.0), 2)
            non_llm = None
        else:
            calls = rec["provider_calls"]
            prov_ms = rec["provider_ms"]
            e2e_ms = rec["total_e2e_ms"]
            non_llm = round(e2e_ms - prov_ms, 2)
        results.append(result)
        per_item.append(
            {
                "eval_id": result.eval_id,
                "provider_calls": calls,
                "provider_ms": prov_ms,
                "non_llm_ms": non_llm,
                "total_e2e_ms": e2e_ms,
                "timed_out": timed_out,
                "exec_success": result.exec_success,
                "ex": result.execution_accuracy,
                "repair_count": result.repair_count,
                "failure_stage": result.failure_stage,
                "error_type": result.error_type,
                "trace": result.trace,
            }
        )
        status = "EX✓" if result.execution_accuracy else ("EX✗" if result.exec_success else "FAIL")
        prov_txt = "n/a" if prov_ms is None else f"{prov_ms:.0f}ms"
        non_txt = "n/a" if non_llm is None else f"{non_llm:.0f}ms"
        print(
            f"[{idx:>3}/{len(sel)}] {result.eval_id} {status} "
            f"calls={calls} provider={prov_txt} non_llm={non_txt} "
            f"e2e={e2e_ms:.0f}ms stage={result.failure_stage or '-'} err={result.error_type or '-'}",
            flush=True,
        )
    elapsed = time.perf_counter() - t0
    db_after = database_file_hash(cfg)
    if db_before != db_after:
        print("[FATAL] 数据库在评测期间发生变化", flush=True)
        return 3

    summary = summarize(results, per_item)
    summary["wall_clock_s"] = round(elapsed, 1)
    summary["db_unchanged"] = True
    summary["measurement_compromised_items"] = compromised
    summary["local_eight_second_target"] = (
        "PASS" if summary["e2e_latency_ms"]["mean"] <= EIGHT_SECOND_TARGET_MS else "FAIL"
    )

    print("\n=== Summary ===", flush=True)
    for key in (
        "n", "success", "failed", "provider_failures", "ex", "conditional_ex",
        "exec_rate", "repair_count", "provider_calls",
    ):
        print(f"{key:24}: {summary[key]}", flush=True)
    for key in ("e2e_latency_ms", "provider_latency_ms", "non_llm_latency_ms"):
        print(f"{key:24}: {summary[key]}", flush=True)
    print(f"{'local 8s target':24}: {summary['local_eight_second_target']}", flush=True)

    if args.write_report:
        payload = {
            "task": "Task 39-L",
            "kind": "local_llm_engineering_benchmark",
            "disclaimer": "Local LLM result != Mimo production result",
            "provider": {
                "name": provider.name,
                "endpoint": args.base_url,
                "model": chosen,
                "available_models": model_ids,
                "api_key_required": False,
            },
            "frozen_baseline_reference": FROZEN_BASELINE,
            "summary": summary,
            "per_item": per_item,
            "results": [r.to_dict() for r in results],
        }
        Path(args.out_json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON: {args.out_json}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
