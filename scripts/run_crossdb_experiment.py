#!/usr/bin/env python
"""Phase 13 跨数据库迁移验证实验入口。

三组实验（同一 24 题统一问题集，同一 LLM Provider / 模型 / Prompt flag）：
- Experiment A：Database A（ecommerce.db） + Profile A（基线）；
- Experiment B：Database B（ecommerce_v2.db） + Profile A 的业务知识
  （Schema 白名单放开为全表内省、无业务描述、口径/Few-shot/词表仍是 A 的，
  Few-shot 不做跨库复核）——度量「换库但只做最低限度工程适配」的损失；
  另附 B0（确定性，不调 LLM）：连接直接切到 B 库且 A 的表白名单原样生效
  → 白名单过滤后无任何表 → 结构不可用；
- Experiment C：Database B + Profile B（完整 B Profile）——验证适配层恢复能力。

指标：EX / Exec Rate / Pass@1（复用 evaluation.metrics.aggregate），
错误类型二分：schema_error（引用了目标库不存在的表/字段）vs
semantic_error（结构合法但结果/口径错误；细分 borrowed_semantics = 把
A 的业务口径搬到了 B 库上）。

用法：
    python scripts/run_crossdb_experiment.py                    # 全部三组
    python scripts/run_crossdb_experiment.py --experiments A,C  # 指定组
    python scripts/run_crossdb_experiment.py --limit 2          # 冒烟
    python scripts/run_crossdb_experiment.py --timeout 90

结果写入 reports/phase13/experiment_{A,B,C}.json 与 experiments_summary.md。
全程只读：不修改任何数据库与冻结资产。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from evaluation import metrics as ev_metrics  # noqa: E402
from evaluation.runner import EvalConfig, eval_single_item  # noqa: E402
from app.agent.graph import run_agent  # noqa: E402
from app.core import config  # noqa: E402
from app.dbprofile.adapter import DatabaseAdapter, components_for_profile  # noqa: E402
from app.dbprofile.models import SchemaProfile  # noqa: E402
from app.dbprofile.profiles import resolve_profile  # noqa: E402
from app.sqlgen.prompt import BUSINESS_RULES  # noqa: E402

QUESTION_SET_PATH = PROJECT_ROOT / "data" / "eval" / "crossdb_unified_v1.json"
DEFAULT_OUT_DIR = PROJECT_ROOT / "reports" / "phase13"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 13 跨数据库迁移实验 Runner")
    p.add_argument("--experiments", type=str, default="A,B,C",
                   help="要运行的实验组（逗号分隔，如 A,B,C）")
    p.add_argument("--limit", type=int, default=None, help="只跑前 N 题（冒烟用）")
    p.add_argument("--ids", type=str, default=None, help="逗号分隔的题号，如 X-001,X-006")
    p.add_argument("--timeout", type=float, default=60.0, help="单题最大时长（秒）")
    p.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR))
    return p.parse_args(argv)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_questions() -> list[dict[str, Any]]:
    data = json.loads(QUESTION_SET_PATH.read_text(encoding="utf-8"))
    return data["items"]


def select_items(items: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        return [i for i in items if i["id"] in wanted]
    if args.limit:
        return items[: args.limit]
    return items


def build_experiment_profiles() -> dict[str, dict[str, Any]]:
    """三组实验的 Profile 配置（B 组 = A 的业务知识 + B 的库）。"""
    profile_a = resolve_profile("ecommerce_A")
    profile_b_full = resolve_profile("ecommerce_B")

    # Experiment B：换库但只做最低限度工程适配——
    # 表白名单放开（否则 B 的表全部被 A 白名单过滤，结构不可用，见 B0），
    # 无业务描述；口径文本 / Few-shot / 检索词表仍是 A 的。
    profile_a_on_b = profile_a.with_overrides(
        profile_id="ecommerce_A_on_B",
        db_path=profile_b_full.db_path,
        schema=SchemaProfile(
            table_names=None,  # 全表内省（最低限度适配）
            table_descriptions={},
            column_descriptions={},
        ),
    )

    return {
        "A": {
            "profile": profile_a,
            "gold_side": "gold_sql_a",
            "validate_fewshot": True,
            "label": "A库 + A Profile（基线）",
        },
        "B": {
            "profile": profile_a_on_b,
            "gold_side": "gold_sql_b",
            "validate_fewshot": False,  # A 的 Few-shot 引用 A 库表，不做跨库复核
            "label": "B库 + A 业务知识（最低限度适配）",
        },
        "C": {
            "profile": profile_b_full,
            "gold_side": "gold_sql_b",
            "validate_fewshot": True,
            "label": "B库 + B Profile（完整适配）",
        },
    }


def deterministic_b0_check() -> dict[str, Any]:
    """B0（确定性，不调 LLM）：仅换连接、A 白名单原样生效时的结构可用性。"""
    profile_a = resolve_profile("ecommerce_A")
    profile_b = resolve_profile("ecommerce_B")
    adapter = profile_a.with_overrides(
        profile_id="ecommerce_A_on_B_zero_adaptation",
        db_path=profile_b.db_path,
    )
    tables = DatabaseAdapter(adapter).build_catalog().table_names
    return {
        "scenario": "B0 仅换数据库连接（A 的 Schema 白名单原样生效）",
        "visible_tables": list(tables),
        "structurally_available": bool(tables),
        "conclusion": (
            "白名单过滤后无任何业务表，Schema Linking 无表可链，系统结构不可用。"
            "换库必须至少放开/更新 Schema 白名单。"
        )
        if not tables
        else "可见表: " + ", ".join(tables),
    }


def _run_one_with_timeout(item: dict[str, Any], eval_cfg: EvalConfig,
                          timeout_s: float) -> Any:
    result_holder: dict[str, Any] = {}
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
        return {
            "eval_id": item["id"], "timeout": True,
        }
    if "e" in error_holder:
        return {"eval_id": item["id"], "exception": repr(error_holder["e"])[:300]}
    return result_holder["r"]


# ---------------- 错误类型细分（实验层，不改 Runner） ----------------

_SQL_MARKERS_BORROWED_FROM_A = (
    "cancelled",          # A 的取消状态（B 库为 voided）
    "order_items",        # A 的表名
    "subtotal",           # A 的明细金额字段
    "total_amount",       # A 的实付字段
    "discount_amount",    # A 的优惠字段
    "users.",             # A 的用户表
    "products.",          # A 的商品表
    "categories.",        # A 的类目表
    "on_sale",            # A 的商品状态
    "'active'",           # A 的用户状态文本枚举
    ".region",            # A 的订单地区冗余列（B 必须JOIN members.city）
)


def _extract_table_names(sql: str) -> set[str]:
    """用 sqlglot 提取 SQL 引用的表名（解析失败返回空集）。"""
    try:
        import sqlglot

        tables: set[str] = set()
        for table in sqlglot.parse(sql, read="sqlite"):
            if table is None:
                continue
            for node in table.walk():
                if isinstance(node, sqlglot.exp.Table):
                    tables.add(node.name.lower())
        return tables
    except Exception:  # noqa: BLE001
        return set()


def _extract_column_refs(sql: str) -> set[tuple[str, str]]:
    """用 sqlglot 提取 (table, column) 限定引用（解析失败返回空集）。"""
    try:
        import sqlglot

        refs: set[tuple[str, str]] = set()
        for parsed in sqlglot.parse(sql, read="sqlite"):
            if parsed is None:
                continue
            for node in parsed.walk():
                if isinstance(node, sqlglot.exp.Column) and node.table:
                    refs.add((node.table.lower(), node.name.lower()))
        return refs
    except Exception:  # noqa: BLE001
        return set()


def classify_pred_failure(result: Any, adapter: DatabaseAdapter,
                          target_is_db_b: bool = False) -> str:
    """exec 成功但 EX 失败时，细分 schema_error / semantic_error。

    - schema_error：pred SQL 引用了目标库不存在的表或表.字段（结构层失败）；
    - semantic_error(borrowed)：SQL 正常执行、结构合法，但携带 A 库业务口径
      标记（如 cancelled/subtotal/region）——仅在目标库为 B 时判定
      （同样的标记在 A 库上是合法标识符，不算移植）；
    - semantic_error：其余「执行成功但结果不匹配」。
    """
    pred_sql = getattr(result, "pred_sql", "") or ""
    catalog = adapter.get_cached_catalog()
    valid_tables = {t.lower() for t in catalog.table_names}
    referenced = _extract_table_names(pred_sql)
    if referenced and referenced - valid_tables:
        return "schema_error"
    bad_cols = [
        (t, c)
        for t, c in _extract_column_refs(pred_sql)
        if t in valid_tables and not catalog.has_column(t, c)
    ]
    if bad_cols:
        return "schema_error"
    if target_is_db_b:
        low = pred_sql.lower()
        if any(marker in low for marker in _SQL_MARKERS_BORROWED_FROM_A):
            return "semantic_error(borrowed)"
    return "semantic_error"


# ---------------- 单组实验 ----------------


def run_experiment(name: str, spec: dict[str, Any], questions: list[dict[str, Any]],
                   args: argparse.Namespace) -> dict[str, Any]:
    profile = spec["profile"]
    gold_side = spec["gold_side"]
    adapter = DatabaseAdapter(profile)
    provider = get_provider()
    components = components_for_profile(
        profile, provider=provider, validate_fewshot=spec["validate_fewshot"]
    )
    executor = adapter.sql_executor()

    items = [
        {**q, "gold_sql": q[gold_side]}
        for q in questions
    ]

    eval_cfg = EvalConfig(
        db_path=profile.db_path,
        dataset_path=QUESTION_SET_PATH,
        timeout_s=args.timeout,
        max_retries=0,
        enable_gold_hash_gate=False,  # 迁移实验集无冻结 hash；gold 由本脚本实际执行
        agent_runner=lambda q: run_agent(q, components=components),
        sql_executor=executor,
    )

    print(f"\n=== Experiment {name}: {spec['label']} ===", flush=True)
    print(f"    db={profile.db_path.name} tables={adapter.get_cached_catalog().table_names}",
          flush=True)
    results = []
    t0 = time.perf_counter()
    for idx, item in enumerate(items, 1):
        start = time.perf_counter()
        r = _run_one_with_timeout(item, eval_cfg, args.timeout)
        elapsed = (time.perf_counter() - start) * 1000.0
        if isinstance(r, dict):  # timeout / exception 占位
            results.append(r)
            print(f"  [{idx:>2}/{len(items)}] {item['id']} RUNNER-{list(r)[1].upper()}",
                  flush=True)
            continue
        r.latency_ms = round(r.latency_ms or elapsed, 2)
        results.append(r)
        status = "EX✓" if r.execution_accuracy else ("EX✗" if r.exec_success else "FAIL")
        print(
            f"  [{idx:>2}/{len(items)}] {r.eval_id} [{item['category']:<6}] {status} "
            f"stage={r.failure_stage or '-'} err={r.error_type or '-'} "
            f"latency={r.latency_ms:.0f}ms",
            flush=True,
        )
    wall_s = round(time.perf_counter() - t0, 1)

    # 汇总（复用正式评测的指标实现）
    clean = [r for r in results if not isinstance(r, dict)]
    runner_breaks = [r for r in results if isinstance(r, dict)]
    summary = ev_metrics.aggregate(clean)
    summary["overall"]["total"] = len(clean)
    summary["runner_breaks"] = len(runner_breaks)

    # 错误类型细分
    taxonomy: dict[str, int] = {}
    for r in clean:
        if r.execution_accuracy:
            key = "correct"
        elif not r.exec_success:
            key = f"failed:{r.failure_stage or 'unknown'}"
        else:
            key = classify_pred_failure(
                r, adapter, target_is_db_b=(gold_side == "gold_sql_b")
            )
        taxonomy[key] = taxonomy.get(key, 0) + 1

    # 分类别 EX
    by_category: dict[str, dict[str, Any]] = {}
    for r, item in zip(clean, items):
        cat = item["category"]
        bucket = by_category.setdefault(cat, {"count": 0, "ex": 0, "exec": 0})
        bucket["count"] += 1
        bucket["ex"] += 1 if r.execution_accuracy else 0
        bucket["exec"] += 1 if r.exec_success else 0

    meta = {
        "experiment": name,
        "label": spec["label"],
        "profile_id": profile.profile_id,
        "gold_side": gold_side,
        "db_path": str(profile.db_path),
        "db_sha256": _sha256_file(profile.db_path),
        "database_info": adapter.database_info(),
        "fewshot_path": str(profile.fewshot.dataset_path),
        "fewshot_sha256": _sha256_file(profile.fewshot.dataset_path),
        "fewshot_validated": spec["validate_fewshot"],
        "generation_rules_sha256": _sha256_text(profile.business_rules.generation_rules),
        "baseline_business_rules_sha256": _sha256_text(BUSINESS_RULES),
        "sqlgen_extra_rules_env": config.__dict__.get("SQLGEN_EXTRA_RULES", "") or "",
        "provider": provider.name,
        "model": provider.model,
        "llm_provider_env": config.LLM_PROVIDER,
        "question_set": QUESTION_SET_PATH.name,
        "question_set_sha256": _sha256_file(QUESTION_SET_PATH),
        "items": len(items),
        "per_item_timeout_s": args.timeout,
        "wall_seconds": wall_s,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "runner_breaks": runner_breaks,
    }
    return {"meta": meta, "summary": summary, "taxonomy": taxonomy,
            "by_category": by_category,
            "items": [r.to_dict() for r in clean]}


_provider_cache: dict[str, Any] = {}


def get_provider():
    from app.llm.provider import get_llm_provider

    key = config.LLM_PROVIDER
    if key not in _provider_cache:
        _provider_cache[key] = get_llm_provider()
    return _provider_cache[key]


def render_summary_md(out: dict[str, Any]) -> str:
    lines = ["# Phase 13 跨数据库迁移实验汇总", "",
             f"生成时间：{datetime.now().isoformat(timespec='seconds')}", ""]
    b0 = out.get("b0")
    if b0:
        lines += ["## B0（确定性检查，不调用 LLM）", "",
                  f"- 场景：{b0['scenario']}",
                  f"- 可见表：{b0['visible_tables'] or '（无）'}",
                  f"- 结论：{b0['conclusion']}", ""]
    lines += [
        "| 指标 | " + " | ".join(f"Exp {k}" for k in out["experiments"]) + " |",
        "|---|" + "---|" * len(out["experiments"]),
    ]
    rows = [
        ("EX", "ex"), ("Exec Rate", "exec_rate"), ("Pass@1", "pass_at_1"),
        ("Conditional EX", "conditional_ex"), ("Repair Trigger Rate", "repair_trigger_rate"),
    ]
    for label, key in rows:
        lines.append(
            f"| {label} | " + " | ".join(
                f"{out['experiments'][k]['summary']['overall'].get(key, '-')}%"
                for k in out["experiments"]
            ) + " |"
        )
    lines += ["", "## 错误类型细分", ""]
    for k in out["experiments"]:
        exp = out["experiments"][k]
        lines.append(f"**Experiment {k}（{exp['meta']['label']}）**")
        for key, count in sorted(exp["taxonomy"].items()):
            lines.append(f"- {key}: {count}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    wanted = [e.strip().upper() for e in args.experiments.split(",") if e.strip()]
    profiles = build_experiment_profiles()
    for w in wanted:
        if w not in profiles:
            print(f"[FATAL] 未知实验组: {w}（可选 A/B/C）")
            return 1

    questions = select_items(load_questions(), args)
    print(f"统一问题集：{QUESTION_SET_PATH.name}（本次 {len(questions)} 题）", flush=True)
    print(f"Provider：{config.LLM_PROVIDER}，SQLGEN_EXTRA_RULES："
          f"{__import__('os').getenv('SQLGEN_EXTRA_RULES', '') or '（空，与冻结基线一致）'}",
          flush=True)

    out: dict[str, Any] = {"experiments": {}}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 子集运行（--limit / --ids）写独立文件名，防止覆盖全量实验产物
    subset = args.limit is not None or args.ids is not None
    suffix = "_smoke" if subset else ""

    if "B" in wanted and len(questions) == 24:
        out["b0"] = deterministic_b0_check()
        print(f"\n[B0] {out['b0']['conclusion']}", flush=True)

    for name in wanted:
        exp = run_experiment(name, profiles[name], questions, args)
        out["experiments"][name] = exp
        (out_dir / f"experiment_{name}{suffix}.json").write_text(
            json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        s = exp["summary"]["overall"]
        print(f"--- Exp {name}: EX={s['ex']}% Exec={s['exec_rate']}% "
              f"Pass@1={s['pass_at_1']}% ---", flush=True)

    if not subset:
        (out_dir / "experiments_summary.md").write_text(
            render_summary_md(out), encoding="utf-8"
        )
    print(f"\n结果已写入 {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
