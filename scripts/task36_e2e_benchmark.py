"""Task 36 — 真实 E2E 性能 Benchmark Harness（固定题集 / 固定模型 / 可重复）。

设计目标（任务书 §七 / §八 / §九）：
- 固定题集：默认读取**现有冻结** Benchmark（`data/eval/ecommerce_eval_v1.json`），
  不创建任何新题集；
- 固定模型：默认 `mimo-v2.5-pro`；
- 固定配置：脚本内**显式记录** timeout / max_retries / temperature / model /
  endpoint identifier（**绝不记录 API key**）；
- 至少区分三种 latency：provider latency / agent non-LLM latency / total E2E latency，
  并报告 mean / median / P50 / P95 / min / max；
- provider 不可用（当前 402 余额不足）时仍能**正常结束并输出统计**，
  不得把 402 当作 timeout。

用法：
    python scripts/task36_e2e_benchmark.py                 # 默认 5 题 smoke
    python scripts/task36_e2e_benchmark.py --limit 100     # 全量
    python scripts/task36_e2e_benchmark.py --dry-run       # 只做预检，不发请求
    python scripts/task36_e2e_benchmark.py --out reports/e2e/run.json

⚠️ 纪律：本脚本只**测量**，不宣称任何性能提升。
本文件**不属于** `backend/tests`，不会被 `pytest backend/tests` 执行。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# --- 固定配置（任务书 §七：必须显式记录，且绝不记录 API key）-----------------
FIXED_MODEL = "mimo-v2.5-pro"
FIXED_TEMPERATURE = 0.0
FIXED_SDK_MAX_RETRIES = 0          # 与 MimoProvider._get_client() 一致
FIXED_DATASET = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"

DEFAULT_LIMIT = 5
DEFAULT_TIMEOUT_S = 60.0


def _endpoint_identifier(base_url: str | None) -> str:
    """endpoint 标识：只保留 host，绝不包含 key 或完整 query。"""
    if not base_url:
        return "(provider default)"
    try:
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else "(configured)"
    except Exception:
        return "(configured)"


def _percentile(sorted_values: list[float], q: int) -> float | None:
    """与项目冻结口径一致：sorted[n*q//100]（非插值）。"""
    if not sorted_values:
        return None
    return sorted_values[len(sorted_values) * q // 100]


def _latency_stats(values: list[float]) -> dict[str, Any]:
    """mean / median / P50 / P95 / min / max（全部四舍五入到 2 位）。"""
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "p50": round(_percentile(ordered, 50), 2),
        "p95": round(_percentile(ordered, 95), 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
    }


def _load_items(dataset_path: Path, limit: int | None, ids: list[str] | None) -> list[dict]:
    with dataset_path.open(encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]
    if ids:
        wanted = set(ids)
        items = [i for i in items if i["id"] in wanted]
    if limit is not None and limit > 0:
        items = items[:limit]
    return items


# --- Provider latency 采集 ---------------------------------------------------
#
# Agent 内部不暴露「LLM 调用耗时」字段，因此本脚本用**计时装饰器**包裹
# LLMProvider.generate，累计一次 Agent Run 内的 provider 调用耗时。
# 这样无需改动任何 Agent / Provider 生产代码（任务书 §十三：Candidate A 不变）。


class _ProviderLatencyProbe:
    """统计单次 run 内的 provider 调用次数与累计耗时（毫秒）。"""

    def __init__(self) -> None:
        self.calls = 0
        self.total_ms = 0.0
        self.last_exception_class: str | None = None
        self.last_http_status: int | None = None

    def reset(self) -> None:
        self.calls = 0
        self.total_ms = 0.0
        self.last_exception_class = None
        self.last_http_status = None


def _install_probe(probe: _ProviderLatencyProbe) -> None:
    """给 MimoProvider.generate 打计时补丁（只在本进程生效）。"""
    from app.llm.mimo import MimoProvider

    original = MimoProvider.generate

    def timed_generate(self, messages, *, temperature=0.0):
        start = time.perf_counter()
        try:
            return original(self, messages, temperature=temperature)
        except Exception as exc:  # noqa: BLE001 — 记录后原样抛出
            probe.last_exception_class = type(exc).__name__
            probe.last_http_status = getattr(exc, "http_status", None)
            raise
        finally:
            probe.calls += 1
            probe.total_ms += (time.perf_counter() - start) * 1000.0

    MimoProvider.generate = timed_generate


def _run_one(
    item: dict,
    probe: _ProviderLatencyProbe,
    timeout_s: float,
) -> dict[str, Any]:
    """跑单题并返回任务书 §七 规定的固定输出字段。"""
    from app.agent.graph import run_agent

    probe.reset()
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    row: dict[str, Any] = {
        "eval_id": item["id"],
        "start_time": started.isoformat(),
        "end_time": None,
        "total_latency_ms": None,
        "provider_latency_ms": None,
        "success": False,
        "exception_class": None,
        "http_status": None,
        "upstream_http_status": None,
        "sql_success": False,
        "repair_triggered": False,
    }

    try:
        result = run_agent(item["question"])
        row["success"] = bool(getattr(result, "success", False))
        row["sql_success"] = bool(getattr(result, "success", False))
        repair_count = getattr(result, "repair_count", 0) or 0
        row["repair_triggered"] = repair_count > 0
        row["error_type"] = getattr(result, "error_type", None)
        row["final_error"] = (getattr(result, "final_error", "") or "")[:200] or None
        if row["error_type"]:
            row["exception_class"] = row["error_type"]
    except Exception as exc:  # noqa: BLE001 — provider/网络异常在此被记录
        row["exception_class"] = type(exc).__name__
        row["error_type"] = type(exc).__name__
        row["final_error"] = str(exc)[:200]
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        row["total_latency_ms"] = round(elapsed_ms, 2)
        row["provider_latency_ms"] = round(probe.total_ms, 2)
        row["provider_calls"] = probe.calls
        row["end_time"] = datetime.now(timezone.utc).isoformat()
        # agent 非 LLM 耗时 = 总耗时 - provider 耗时（不得为负）
        row["agent_non_llm_latency_ms"] = round(
            max(elapsed_ms - probe.total_ms, 0.0), 2
        )

    if row["exception_class"] is None and not row["success"]:
        row["exception_class"] = row.get("error_type")

    # http_status 口径：优先使用 **上游真实 status**（probe 在 Provider 层捕获），
    # 而非 AgentResult.http_status —— 后者是按异常类型映射的**客户端**状态
    # （如 402 -> 503），会把上游 402 掩盖成 503。
    row["http_status"] = probe.last_http_status
    row["upstream_http_status"] = probe.last_http_status
    return row


def _classify_run(rows: list[dict]) -> dict[str, Any]:
    """判定本次 benchmark 的整体可用性（区分 DRY / UNAVAILABLE / MEASURED）。"""
    if not rows:
        return {"mode": "EMPTY", "reason": "no items selected"}

    exc_classes = {r.get("exception_class") for r in rows if r.get("exception_class")}
    statuses = {r.get("http_status") for r in rows if r.get("http_status")}
    ok = sum(1 for r in rows if r.get("success"))

    if ok == len(rows):
        return {"mode": "MEASURED", "reason": "all items succeeded"}

    if "LLMInsufficientBalanceError" in exc_classes or 402 in statuses:
        return {
            "mode": "UNAVAILABLE",
            "reason": "provider returned HTTP 402 Insufficient account balance",
            "provider_unavailable": True,
            "headline": "E2E measurement unavailable due to provider 402",
        }

    if all(r.get("exception_class") == "LLMTimeoutError" for r in rows):
        return {"mode": "UNAVAILABLE", "reason": "all items timed out"}

    return {
        "mode": "PARTIAL",
        "reason": f"{ok}/{len(rows)} items succeeded; failures are not a single provider cause",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Task 36 — 真实 E2E 性能 Benchmark（固定题集/固定模型，可重复）"
    )
    parser.add_argument("--dataset", type=Path, default=FIXED_DATASET)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="限制题目数（默认 5，smoke 用；0 表示全量）")
    parser.add_argument("--ids", nargs="*", default=None, help="指定 eval_id")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--dry-run", action="store_true",
                        help="只做预检与配置打印，不发任何请求")
    parser.add_argument("--out", type=Path, default=None, help="结果 JSON 输出路径")
    args = parser.parse_args(argv)

    from app.core import config

    items = _load_items(args.dataset, args.limit or None, args.ids)

    run_meta = {
        "task": "Task 36 — E2E Benchmark",
        "script": "scripts/task36_e2e_benchmark.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frozen_dataset": str(args.dataset.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "item_count": len(items),
        "item_ids": [i["id"] for i in items],
        "fixed_config": {
            "model": FIXED_MODEL,
            "configured_model": config.MIMO_MODEL,
            "temperature": FIXED_TEMPERATURE,
            "timeout_s": args.timeout,
            "sdk_max_retries": FIXED_SDK_MAX_RETRIES,
            "provider": config.LLM_PROVIDER,
            "endpoint_identifier": _endpoint_identifier(config.MIMO_BASE_URL),
            "api_key_recorded": False,
        },
        "latency_definitions": {
            "provider_latency_ms": "LLMProvider.generate 累计墙钟耗时（可能含多次调用）",
            "agent_non_llm_latency_ms": "total_latency_ms - provider_latency_ms",
            "total_e2e_latency_ms": "run_agent() 端到端墙钟耗时（不含进程/图编译预热）",
        },
    }

    print("=" * 72)
    print("Task 36 — E2E Benchmark")
    print("=" * 72)
    print(f"dataset        : {run_meta['frozen_dataset']}  ({len(items)} items)")
    print(f"model          : {FIXED_MODEL}  (configured: {config.MIMO_MODEL})")
    print(f"timeout        : {args.timeout}s    temperature: {FIXED_TEMPERATURE}")
    print(f"max_retries    : {FIXED_SDK_MAX_RETRIES} (SDK layer)")
    print(f"provider       : {config.LLM_PROVIDER}")
    print(f"endpoint       : {run_meta['fixed_config']['endpoint_identifier']}")
    print(f"api key        : {'SET (not recorded)' if config.MIMO_API_KEY else 'NOT SET'}")
    print("=" * 72)

    if args.dry_run:
        print("DRY-RUN: 未发起任何请求。")
        payload = {"meta": run_meta, "mode": "DRY", "rows": [], "summary": None}
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"written: {args.out}")
        return 0

    probe = _ProviderLatencyProbe()
    _install_probe(probe)

    rows: list[dict] = []
    for idx, item in enumerate(items, 1):
        row = _run_one(item, probe, args.timeout)
        rows.append(row)
        print(
            f"[{idx}/{len(items)}] {row['eval_id']:<8} "
            f"total={row['total_latency_ms']:>9.2f}ms  "
            f"provider={row['provider_latency_ms']:>9.2f}ms  "
            f"nonllm={row['agent_non_llm_latency_ms']:>8.2f}ms  "
            f"ok={row['success']}  "
            f"exc={row['exception_class'] or '-'}  "
            f"upstream_http={row['upstream_http_status'] or '-'}"
        )

    ok_rows = [r for r in rows if r.get("success")]

    summary = {
        "total_e2e_latency_ms": _latency_stats(
            [r["total_latency_ms"] for r in rows if r["total_latency_ms"] is not None]
        ),
        "provider_latency_ms": _latency_stats(
            [r["provider_latency_ms"] for r in ok_rows if r["provider_latency_ms"] is not None]
        ),
        "agent_non_llm_latency_ms": _latency_stats(
            [r["agent_non_llm_latency_ms"] for r in ok_rows
             if r["agent_non_llm_latency_ms"] is not None]
        ),
        "success_count": len(ok_rows),
        "failure_count": len(rows) - len(ok_rows),
        "provider_calls_total": sum(r.get("provider_calls", 0) for r in rows),
    }

    classification = _classify_run(rows)
    summary["classification"] = classification

    print("-" * 72)
    print(f"mode           : {classification['mode']}")
    print(f"reason         : {classification['reason']}")
    print(f"success        : {summary['success_count']}/{len(rows)}")
    print(f"provider calls : {summary['provider_calls_total']}")
    for key in ("total_e2e_latency_ms", "provider_latency_ms", "agent_non_llm_latency_ms"):
        s = summary[key]
        print(
            f"{key:<26} n={s['count']:<4} "
            f"mean={s['mean']} median={s['median']} "
            f"p50={s['p50']} p95={s['p95']} "
            f"min={s['min']} max={s['max']}"
        )
    if classification.get("provider_unavailable"):
        print("-" * 72)
        print("E2E measurement unavailable due to provider 402")
        print("（未对本次运行作任何性能结论）")
    print("-" * 72)

    payload = {"meta": run_meta, "mode": classification["mode"],
               "classification": classification, "rows": rows, "summary": summary}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
