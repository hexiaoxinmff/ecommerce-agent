#!/usr/bin/env python
"""ECO-SQL-Bench v1 自动化 Benchmark Runner 入口（Task 13）。

用法：
    python scripts/run_eval.py                       # 跑完整 100 条（串行）
    python scripts/run_eval.py --limit 10            # 前 10 条
    python scripts/run_eval.py --ids E-0001,E-0012,E-0026,E-0056,E-0086
    python scripts/run_eval.py --difficulty easy     # 按难度
    python scripts/run_eval.py --timeout 60
    python scripts/run_eval.py --bad-cases-dir data/eval/bad_cases

行为约定：
- 默认串行；单题超时由线程包一层（timeout → error_type=timeout，继续下一题）；
- 启动时先跑 Gold Hash Gate（E-0001~E-0100 全部重算比对），漂移即整体停止；
- Provider 网络错误最多重试 1 次（Runner-level），与 Agent 内部 Repair 严格区分；
- 结果写入 reports/eval/eval_{run_id}.json / .md；Bad Case 写入 bad_cases 目录；
- 全部 SQL 只读执行（app.sqlexec.executor 与 Agent 共用），不修改数据库。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core import config  # noqa: E402

from evaluation import metrics as ev_metrics  # noqa: E402
from evaluation import report as ev_report  # noqa: E402
from evaluation import runner as ev_runner  # noqa: E402
from evaluation.models import EvalCaseResult  # noqa: E402
from evaluation.runner import EvalConfig  # noqa: E402
from evaluation.runner import eval_single_item  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ECO-SQL-Bench v1 Runner")
    p.add_argument("--ids", type=str, default=None, help="逗号分隔的题号，如 E-0001,E-0002")
    p.add_argument("--limit", type=int, default=None, help="只跑前 N 条（默认全量）")
    p.add_argument("--difficulty", type=str, default=None, help="筛选难度（easy/medium/hard/extra_hard）")
    p.add_argument("--timeout", type=float, default=60.0, help="单题最大时长（秒）")
    p.add_argument("--bad-cases-dir", type=str, default=str(
        PROJECT_ROOT / "data" / "eval" / "bad_cases"))
    p.add_argument("--out-dir", type=str, default=str(PROJECT_ROOT / "reports" / "eval"))
    p.add_argument("--skip-hash-gate", action="store_true", help="跳过 Gold Hash Gate（调试用）")
    p.add_argument("--no-retry", action="store_true", help="关闭 Runner-level 重试")
    p.add_argument("--experiment", type=str, default="", help="实验名（写入 meta.experiment，如 e1_semantics_v1）")
    p.add_argument("--prompt-version", type=str, default="", help="Prompt 版本（写入 meta，如 SQLGENERATOR_PROMPT_V1.1）")
    p.add_argument("--fewshot-version", type=str, default="", help="Few-shot 版本（写入 meta，如 FEWSHOT_V2）")
    return p.parse_args(argv)


def _run_one_with_timeout(
    item: dict[str, Any], eval_cfg: EvalConfig, timeout_s: float
) -> EvalCaseResult:
    """带单题超时保护的单题评测。"""
    result_holder: dict[str, EvalCaseResult] = {}
    error_holder: dict[str, Exception] = {}

    def _wrapped() -> None:
        try:
            result_holder["r"] = eval_single_item(item, eval_cfg)
        except Exception as exc:  # noqa: BLE001
            error_holder["e"] = exc

    t = threading.Thread(target=_wrapped, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
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
            valid_model_run=False,
            failure_stage="provider",
            error_type="timeout",
            latency_ms=timeout_s * 1000.0,
            trace_summary="timeout",
        )
    if "e" in error_holder:
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
            valid_model_run=False,
            failure_stage="provider",
            error_type=type(error_holder["e"]).__name__,
            latency_ms=0.0,
            trace_summary=str(error_holder["e"])[:200],
        )
    return result_holder["r"]


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt_sha256() -> str:
    """当前实际生效的 Prompt BUSINESS_RULES 哈希（可复现性元数据）。"""
    import hashlib

    from app.sqlgen.prompt import BUSINESS_RULES  # noqa: PLC0415

    return hashlib.sha256(BUSINESS_RULES.encode("utf-8")).hexdigest()


def _db_counts() -> dict[str, int]:
    import sqlite3
    from contextlib import closing

    counts: dict[str, int] = {}
    with closing(sqlite3.connect(r"file:db/ecommerce.db?mode=ro", uri=True)) as c:
        for t in ("users", "categories", "products", "orders", "order_items"):
            counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return counts


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 数据集 & 配置
    eval_cfg = EvalConfig(
        timeout_s=args.timeout,
        max_retries=0 if args.no_retry else 1,
        enable_gold_hash_gate=not args.skip_hash_gate,
    )
    items = ev_runner._read_dataset(eval_cfg.dataset_path)

    # Leakage Gate（默认开启，禁止用泄漏 Few-shot 集做实验）
    from scripts.check_benchmark_leakage import check_leakage  # noqa: PLC0415

    try:
        fewshot_items = json.loads(
            (PROJECT_ROOT / "data" / "fewshot" / "ecommerce_examples.json").read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001
        fewshot_items = []
    leak_problems = check_leakage(fewshot_items, items)
    if leak_problems:
        print("[FATAL] Benchmark Leakage Gate 失败：Few-shot 与 Benchmark 存在泄漏，禁止评测。", flush=True)
        for p in leak_problems[:20]:
            print(f"  ✗ {p}", flush=True)
        return 4
    print("Benchmark Leakage Gate：PASS（无泄漏）", flush=True)

    # Hash Gate（默认开启）
    if eval_cfg.enable_gold_hash_gate:
        print("正在执行 Gold Hash Gate（E-0001~E-0100 重算比对）...", flush=True)
        try:
            ev_runner.compute_gold_hash_gate(items, eval_cfg)
            print("Gold Hash Gate 通过：100/100 一致。", flush=True)
        except ev_runner.GoldHashGateError as exc:
            print(f"\n[FATAL] {exc}", flush=True)
            print("评测中止。请先排查数据漂移（勿拿漂移 Gold 评测）。", flush=True)
            return 2

    # 筛选
    difficulties = [args.difficulty] if args.difficulty else None
    sel = ev_runner.select_items(
        items, ids=[i for i in (args.ids.split(",") if args.ids else []) if i], difficulties=difficulties, limit=args.limit
    )

    print(f"评测题数：{len(sel)}（总 {len(items)}）串行执行，超时 {args.timeout}s/题", flush=True)
    results: list[EvalCaseResult] = []
    db_hash_before = ev_runner.database_file_hash(eval_cfg)
    t0 = time.perf_counter()
    for idx, item in enumerate(sel, 1):
        start = time.perf_counter()
        r = _run_one_with_timeout(item, eval_cfg, args.timeout)
        elapsed = (time.perf_counter() - start) * 1000.0
        r.latency_ms = round(r.latency_ms or elapsed, 2)
        results.append(r)
        status = "EX✓" if r.execution_accuracy else ("EX✗" if r.exec_success else "FAIL")
        print(
            f"[{idx:>3}/{len(sel)}] {r.eval_id} {r.difficulty:<11} {status} "
            f"stage={r.failure_stage or '-'} err={r.error_type or '-'} "
            f"exec={r.exec_success} latency={r.latency_ms:.0f}ms",
            flush=True,
        )
    elapsed_total = (time.perf_counter() - t0) * 1000.0
    db_hash_after = ev_runner.database_file_hash(eval_cfg)
    if db_hash_before != db_hash_after:
        print("[FATAL] 检测到数据库文件在评测期间发生变化，异常中止（不得写入报告）。", flush=True)
        return 3

    # 汇总与报告
    db_info = _db_counts()
    meta = ev_report.build_meta(
        dataset_version="1.1",
        database_version="dev-2026-09-14",
        schema_version="1.0",
        seed=20260914,
        model=config.MIMO_MODEL or "mimo-v2.5-pro",
        provider=config.LLM_PROVIDER or "mimo",
        base_url=config.MIMO_BASE_URL or "(default)",
        run_id=f"{time.strftime('%Y%m%d')}_{int(time.time()) % 86400:05d}",
        mode="full" if not args.ids and not args.difficulty and args.limit is None else "subset",
        per_item_timeout_s=args.timeout,
        prompt_version=args.prompt_version,
        fewshot_version=args.fewshot_version,
        experiment=args.experiment,
        prompt_sha256=_prompt_sha256(),
        fewshot_sha256=_sha256_file(PROJECT_ROOT / "data" / "fewshot" / "ecommerce_examples.json"),
        fewshot_path=str(PROJECT_ROOT / "data" / "fewshot" / "ecommerce_examples.json"),
        dataset_sha256=_sha256_file(eval_cfg.dataset_path),
        db_table_counts=json.dumps(db_info, ensure_ascii=False),
    )
    summary = ev_report.build_summary(results, meta)
    meta.total_items = len(sel)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"eval_{meta.run_id}.json"
    md_path = out_dir / f"eval_{meta.run_id}.md"
    ev_report.write_report_json(json_path, meta, results, summary)
    md_path.write_text(ev_report.render_markdown(results, summary, meta), encoding="utf-8")

    # Bad Case
    bad_dir = Path(args.bad_cases_dir)
    n_bad = ev_report.write_bad_cases(results, bad_dir, base=_existing_bad_base(bad_dir))

    print("\n==============================================")
    print("总体")
    o = summary
    print(f"Total: {o.total}")
    print(f"Valid Model Runs: {o.valid_model_runs}")
    print(f"Provider Failures: {o.provider_failures}")
    print(f"Timeout: {o.timeouts}")
    print(f"Overall EX: {o.ex}%")
    print(f"Conditional EX: {o.conditional_ex}%")
    print(f"Exec Rate: {o.exec_rate}%")
    print(f"Pass@1(初始): {o.pass_at_1}%")
    print(f"Repair Trigger Rate: {o.repair_trigger_rate}%")
    print(f"Repair Success Rate: {o.repair_success_rate}%")
    print(f"Avg Latency: {o.avg_latency_ms} ms (P50 {o.p50_latency_ms} / P95 {o.p95_latency_ms})")
    print(f"总耗时: {elapsed_total / 1000.0:.1f}s")
    print(f"\nJSON: {json_path}")
    print(f"MD  : {md_path}")
    print(f"Bad Cases: {n_bad}（{bad_dir}）")
    print(f"数据库未修改: {'PASS' if db_hash_before == db_hash_after else 'FAIL'}")
    return 0


def _existing_bad_base(bad_dir: Path) -> int:
    """从现有 bad_cases 目录推断下一个 B- 编号下限（避免覆盖）。"""
    if not bad_dir.exists():
        return 1000
    mx = 1000
    for f in bad_dir.glob("B-*.json"):
        try:
            case_id = f.stem  # e.g. B-1001
            num = int(case_id.split("-")[1])
            mx = max(mx, num)
        except (IndexError, ValueError):
            continue
    return mx


if __name__ == "__main__":
    sys.exit(main())