#!/usr/bin/env python
"""Task 21：FANOUT_RECHECK_HINT ON 组评测 Runner（独立实验脚本，不修改正式 run_eval.py）。

*************************************************************************
Task21 historical frozen experiment (E3). Do not change this historical
experiment implementation. Hint text SHA256 must remain:
    5f13e7cc66e306325cb8987f62ef401fb01c89cbcf9c30dd40e3bad13704dd69
(This text duplicates backend/app/experiments/fanout_hint.py by design;
both are frozen and must stay byte-identical for Task 20/21 reproducibility.)
*************************************************************************

流程（每题）：
    question
      → schema_link（正式组件）→ fewshot（正式组件）→ SQLGenerator.generate (initial_sql)
      → analyze_fanout(initial_sql)
          ├─ false → final = initial（零干预，与 OFF 的 prompt 完全一致）
          └─ true  → 追加 FANOUT_RECHECK_HINT → 同一 provider temperature=0 重新生成一次
                      （且仅一次；失败则回落 initial 并记录 regen_error）
      → SQL Validation（复用正式 validate_output） → 执行 final → EX 判定

约束：
- 最多一次 regeneration；无 repair / AST rewrite / 第二 Agent / 多轮；
- hint 不进 detector=false 样本；
- 不修改任何正式文件。

输出：
- {out_dir}/eval_{run_id}.json（含每 case intervention 记录）
- {out_dir}/interventions.json
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

from app.fewshot.models import FewShotQuery  # noqa: E402
from app.schemas.schema_link import SchemaLinkResult  # noqa: E402
from app.sqlgen.generator import SQLGenerator  # noqa: E402
from app.sqlgen.validator import parse_llm_output, validate_output  # noqa: E402
from app.sqlgen.prompt import SYSTEM_PROMPT, build_prompt  # noqa: E402
from app.llm.provider import get_llm_provider  # noqa: E402
from app.schema.metadata import SchemaCatalog  # noqa: E402

from evaluation import runner as ev_runner  # noqa: E402
from evaluation import report as ev_report  # noqa: E402
from evaluation.normalization import compare_results, normalize_result  # noqa: E402
from evaluation.models import EvalCaseResult  # noqa: E402

FEWSHOT_TOP_K = 3

FANOUT_HINT = """【Fan-out 自检提示】
检测到当前 SQL 存在潜在 1:N Join 粒度风险（orders × order_items）。
请重新检查 SQL 中 orders 与 order_items 的 Join 粒度：

- 如果聚合函数作用于 orders 级字段（例如 orders.total_amount、订单数），请确认
  是否会因 order_items 的多行展开导致重复累加 / 重复计数；
- 不要修改查询需求的业务语义；
- 优先通过订单级预聚合（先按订单分组后聚合）、独立聚合后再按维度 JOIN、或使用
  EXISTS / 去重等方式避免重复累计；
- 注意：item-level 指标（例如 order_items.subtotal、order_items.quantity）不受本提示影响，
  请勿因本提示改写 item 级聚合。

请基于上述提示与题目原始需求，重新生成唯一一条只读 SQLite SQL。"""


# ---------------- 额外一次 regeneration ----------------

def regenerate_with_hint(
    question: str,
    link_result: SchemaLinkResult,
    prompt: str,
    provider: Any,
    tables: list[str],
) -> str:
    """追加 hint 后调用 provider 重新生成（仅一次）。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
        {"role": "user", "content": FANOUT_HINT},
    ]
    raw = provider.generate(messages, temperature=0.0)
    data = parse_llm_output(raw)
    catalog = SchemaCatalog.from_database()
    validated = validate_output(data, tables, catalog)
    return validated["sql"]


def _norm(exec_result, item: dict):
    s = item.get("answer_slots") or {}
    return normalize_result(
        exec_result.columns, exec_result.rows,
        value_type=str(s.get("value_type", "")),
        tolerance=float(s.get("tolerance") or 0.0),
        order_sensitive=bool(s.get("order_sensitive", False)),
        expected_empty=bool(s.get("expected_empty", False)),
    )


def _ex_of_sql(sql: str, item: dict, config: ev_runner.EvalConfig) -> tuple[bool, bool, str, int]:
    """执行 sql 并判断 EX。返回 (exec_success, ex, reason, row_count)。"""
    s = item.get("answer_slots") or {}
    vt = str(s.get("value_type", ""))
    tol = float(s.get("tolerance") or 0.0)
    os_ = bool(s.get("order_sensitive", False))
    try:
        gold_res = config.sql_executor(item["gold_sql"])
        gold_norm = _norm(gold_res, item)
    except Exception as exc:  # noqa: BLE001
        return False, False, f"gold error: {exc}", 0
    try:
        pred_res = config.sql_executor(sql)
    except Exception as exc:  # noqa: BLE001
        return False, False, f"{type(exc).__name__}: {exc}", 0
    pred_norm = _norm(pred_res, item)
    outcome = compare_results(gold_norm, pred_norm, value_type=vt, tolerance=tol, order_sensitive=os_)
    return True, outcome.match, outcome.reason, pred_res.row_count


# ---------------- 单题 ON ----------------

def eval_on_single(
    item: dict[str, Any],
    config: ev_runner.EvalConfig,
    generator: SQLGenerator,
    provider: Any,
) -> EvalCaseResult:
    schema_key = {"case_id": item["id"], "detector_alarm": None, "hint_injected": None,
                  "regeneration_count": 0, "initial_sql": "", "regenerated_sql": "",
                  "final_sql": "", "initial_ex": None, "final_ex": None, "regen_error": ""}
    s = item.get("answer_slots") or {}
    vt = str(s.get("value_type", ""))
    tol = float(s.get("tolerance") or 0.0)
    os_ = bool(s.get("order_sensitive", False))

    try:
        gold_res = config.sql_executor(item["gold_sql"])
        gold_norm = _norm(gold_res, item)
    except Exception as exc:  # noqa: BLE001
        return EvalCaseResult(item["id"], item["question"], item["difficulty"], item["scenario"],
                              list(item.get("operators", [])), item["gold_sql"], "", False, False,
                              valid_model_run=True, failure_stage="gold_execute",
                              error_type=f"gold error: {exc}", latency_ms=0.0, trace_summary="gold 执行失败")

    t0 = time.perf_counter()
    try:
        link = generator._schema_linker.link(item["question"])
        fs = generator._fewshot_retriever.retrieve(FewShotQuery(
            question=item["question"], tables=link.tables, columns=link.columns, top_k=FEWSHOT_TOP_K))
        initial = generator.generate_with_context(item["question"], link, fs)
        initial_sql = initial.sql
    except Exception as exc:  # noqa: BLE001
        latency = (time.perf_counter() - t0) * 1000.0
        is_provider, tag = ev_runner.classify_provider_failure(type(exc).__name__, str(exc))
        return EvalCaseResult(item["id"], item["question"], item["difficulty"], item["scenario"],
                              list(item.get("operators", [])), item["gold_sql"], "", False, False,
                              valid_model_run=not is_provider, failure_stage="provider" if is_provider else "sql_generate",
                              error_type=tag or type(exc).__name__, latency_ms=round(latency, 2),
                              trace_summary=f"generate failed: {exc}")

    schema_key["initial_sql"] = initial_sql

    # initial EX（供修复率统计）
    _, init_ex, _, _ = _ex_of_sql(initial_sql, item, config)
    schema_key["initial_ex"] = init_ex

    # detector
    from app.sqlcheck.fanout_detector import analyze_fanout
    diag = analyze_fanout(initial_sql)
    schema_key["detector_alarm"] = diag.fan_out_suspected

    if diag.fan_out_suspected:
        try:
            final_sql = regenerate_with_hint(item["question"], link, build_prompt(item["question"], link, fs),
                                             provider, link.tables)
            schema_key["regeneration_count"] = 1
            schema_key["regenerated_sql"] = final_sql
        except Exception as exc:  # noqa: BLE001
            schema_key["regen_error"] = f"{type(exc).__name__}: {exc}"
            final_sql = initial_sql  # 回落
        schema_key["hint_injected"] = True
    else:
        final_sql = initial_sql
        schema_key["hint_injected"] = False

    schema_key["final_sql"] = final_sql

    exec_ok, ex, reason, row_count = _ex_of_sql(final_sql, item, config)
    schema_key["final_ex"] = ex
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    failure_stage = None
    error_type = None
    if not exec_ok:
        failure_stage = "sql_execute"
        error_type = reason
    elif not ex:
        failure_stage = "result"
        error_type = "result_mismatch"

    result = EvalCaseResult(
        eval_id=item["id"], question=item["question"], difficulty=item["difficulty"],
        scenario=item["scenario"], operators=list(item.get("operators", [])),
        gold_sql=item["gold_sql"], pred_sql=final_sql, initial_sql=initial_sql, final_sql=final_sql,
        exec_success=exec_ok, execution_accuracy=ex, repair_triggered=False, repair_count=0,
        repair_success=False, failure_stage=failure_stage, error_type=error_type,
        latency_ms=latency_ms, valid_model_run=True, trace_summary="",
    )
    # 附加干预记录
    setattr(result, "intervention", schema_key)
    return result


def _run_one_with_timeout(item, config, generator, provider, timeout_s):
    holder, err_holder = {}, {}
    def wrapped():
        try:
            holder["r"] = eval_on_single(item, config, generator, provider)
        except Exception as exc:  # noqa: BLE001
            err_holder["e"] = exc
    t = threading.Thread(target=wrapped, daemon=True)
    t.start(); t.join(timeout=timeout_s)
    if t.is_alive():
        return EvalCaseResult(item["id"], item["question"], item["difficulty"], item["scenario"],
                              list(item.get("operators", [])), item["gold_sql"], "", False, False,
                              valid_model_run=False, failure_stage="provider", error_type="timeout",
                              latency_ms=timeout_s * 1000.0, trace_summary="timeout")
    if "e" in err_holder:
        return EvalCaseResult(item["id"], item["question"], item["difficulty"], item["scenario"],
                              list(item.get("operators", [])), item["gold_sql"], "", False, False,
                              valid_model_run=False, failure_stage="provider",
                              error_type=type(err_holder["e"]).__name__, latency_ms=0.0,
                              trace_summary=str(err_holder["e"])[:200])
    return holder["r"]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--out-dir", type=str, default=str(PROJECT_ROOT / "reports/eval/task21_e3_hint_intervention/run_on"))
    p.add_argument("--experiment", type=str, default="task21_e3_hint_intervention_run_on")
    p.add_argument("--ids", type=str, default=None)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    config = ev_runner.EvalConfig(timeout_s=args.timeout, max_retries=1)
    items = ev_runner._read_dataset(config.dataset_path)

    # Gate 复用正式逻辑（Leakage + Gold Hash）
    from scripts.check_benchmark_leakage import check_leakage
    from app.core import config as app_config
    try:
        fewshot_items = json.loads((PROJECT_ROOT / "data/fewshot/ecommerce_examples.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        fewshot_items = []
    problems = check_leakage(fewshot_items, items)
    if problems:
        print("[FATAL] Leakage Gate failed"); return 4
    print("Leakage Gate: PASS", flush=True)
    ev_runner.compute_gold_hash_gate(items, config)
    print("Gold Hash Gate: PASS", flush=True)

    sel = ev_runner.select_items(items, ids=[i for i in (args.ids.split(",") if args.ids else []) if i], limit=args.limit)
    print(f"ON 评测 {len(sel)} 条，串行，timeout={args.timeout}s", flush=True)

    generator = SQLGenerator()
    provider = get_llm_provider()
    results = []
    t0 = time.perf_counter()
    for idx, item in enumerate(sel, 1):
        r = _run_one_with_timeout(item, config, generator, provider, args.timeout)
        results.append(r)
        iv = getattr(r, "intervention", None)
        alarm = iv["detector_alarm"] if iv else None
        status = "EX✓" if r.execution_accuracy else ("EX✗" if r.exec_success else "FAIL")
        print(f"[{idx:>3}/{len(sel)}] {r.eval_id} {r.difficulty:<11} {status} stage={r.failure_stage or '-'} "
              f"err={r.error_type or '-'} alarm={alarm} exec={r.exec_success} lat={r.latency_ms:.0f}ms", flush=True)

    db_before = ev_runner.database_file_hash(config)
    db_after = ev_runner.database_file_hash(config)
    if db_before != db_after:
        print("[FATAL] DB 变化"); return 3

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{time.strftime('%Y%m%d')}_{int(time.time()) % 86400:05d}"
    meta = ev_report.build_meta(
        dataset_version="1.1", database_version="dev-2026-09-14", schema_version="1.0",
        seed=20260914, model=app_config.MIMO_MODEL or "mimo-v2.5-pro",
        provider=app_config.LLM_PROVIDER or "mimo",
        base_url=app_config.MIMO_BASE_URL or "(default)",
        run_id=run_id, mode="full", per_item_timeout_s=args.timeout,
        prompt_version="SQLGENERATOR_PROMPT_V1.3", fewshot_version="FEWSHOT_V3",
        experiment=args.experiment,
    )
    # 指纹（与正式 run_eval 对齐）
    import hashlib
    from app.sqlgen.prompt import BUSINESS_RULES
    meta.prompt_sha256 = hashlib.sha256(BUSINESS_RULES.encode()).hexdigest()
    meta.fewshot_sha256 = hashlib.sha256((PROJECT_ROOT / "data/fewshot/ecommerce_examples.json").read_bytes()).hexdigest()
    meta.fewshot_path = str(PROJECT_ROOT / "data/fewshot/ecommerce_examples.json")
    meta.dataset_sha256 = hashlib.sha256(config.dataset_path.read_bytes()).hexdigest()
    import sqlite3
    from contextlib import closing
    counts = {}
    with closing(sqlite3.connect(r"file:db/ecommerce.db?mode=ro", uri=True)) as c:
        for t in ("users", "categories", "products", "orders", "order_items"):
            counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    meta.db_table_counts = json.dumps(counts, ensure_ascii=False)

    summary = ev_report.build_summary(results, meta)
    meta.total_items = len(sel)
    # 先写基础 report，再加入 intervention 字段（不改正式 report.write_report_json）
    ev_report.write_report_json(out_dir / "eval.json", meta, results, summary)
    payload = json.loads((out_dir / "eval.json").read_text(encoding="utf-8"))
    for res_dict, r in zip(payload["results"], results):
        res_dict["intervention"] = getattr(r, "intervention", {})
    payload["interventions_summary"] = {"mode": "FANOUT_RECHECK_HINT", "max_regeneration": 1}
    (out_dir / "eval.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"eval_{run_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(ev_report.render_markdown(results, summary, meta), encoding="utf-8")

    interventions = [
        {**(getattr(r, "intervention", {})), "exec_ok": r.exec_success, "execution_accuracy": r.execution_accuracy}
        for r in results
    ]
    (out_dir / "interventions.json").write_text(json.dumps(interventions, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n总体"); o = summary
    print(f"Total: {o.total} | Valid: {o.valid_model_runs} | Provider: {o.provider_failures} | Timeout: {o.timeouts}")
    print(f"Overall EX: {o.ex}% | Conditional EX: {o.conditional_ex}% | Exec Rate: {o.exec_rate}% | Pass@1: {o.pass_at_1}%")
    print(f"Avg Latency: {o.avg_latency_ms} ms (P50 {o.p50_latency_ms} / P95 {o.p95_latency_ms})")
    print(f"JSON: {out_dir / 'eval.json'} | interventions: {out_dir / 'interventions.json'}")
    print(f"数据库未修改: {'PASS' if db_before == db_after else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())