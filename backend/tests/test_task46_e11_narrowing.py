"""Task 46：E11 规则收窄的离线回归测试（A~F）。

全部为**离线 deterministic** 测试：不调用任何 LLM / 网络，只做
① 规则文本契约断言 ② sqlglot 结构增量检查（E11 只允许改 ORDER BY）③ 真实只读库复算
④ gold 原样重放（identity replay）。

## 背景（Task 45 的真实回归）

E11（Top-N 确定性破平键）在真实 Bailian 链路上：
- `E-0098`：OFF 无破平键 EX✗ → ON 加 `p.id ASC` EX✓（真实收益）；
- `E-0042`：ON 把 `orders.id` 写进 **GROUP BY** ⇒ 聚合粒度从「按地区」变成「按行」，EX✓→EX✗；
- `E-0074`：ON 把日期过滤从 `order_date >= '2025-10-01' AND < '2026-01-01'` 改写成
  `substr(order_date,1,7) = '2025-10'`（Q4 → 单月），EX✓→EX✗。

Task 46 把 E11 注入文本收窄为「**只允许在 ORDER BY 追加破平键**」，并显式禁止四类误用。

## 核心不变量（本文件用 sqlglot 强制）

> E11 开关前后，SQL 的差异**只允许**出现在 ORDER BY（含窗口 ORDER BY）的新增键上。
> SELECT 输出列数、GROUP BY 列集合、WHERE/HAVING 的日期谓词**必须完全一致**。

## 结构

| 段 | 内容 |
|---|---|
| §0 | gold identity replay（100 题，探针自检，必须先成立） |
| §1 | Test A —— Top-N 正常破平键（E-0098 是**允许**的增量） |
| §2 | Test B —— GROUP BY 粒度保护（E-0042 的真实回归必须被检出） |
| §3 | Test C —— SELECT 契约保护 |
| §4 | Test D —— 时间过滤保护（E-0074 的真实回归必须被检出） |
| §5 | Test E —— 标量 Top-1 继续保持不触发 |
| §6 | 规则文本收窄契约（4 条禁止 + 「唯一作用」声明） |
| §7 | 触发面不变 + 开关契约（默认关闭逐字节不变） |
| §8 | 检查器自身有效性（正例干净 / 负例报警，防「检查器永远返回空」） |
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.sqlgen.prompt import (  # noqa: E402
    build_prompt,
    ranking_tiebreak_block,
    semantic_contract_block,
)
from app.sqlgen.semantic_contracts import detect_ranking_tiebreak  # noqa: E402
from app.sqlexec.executor import execute  # noqa: E402
from evaluation.normalization import (  # noqa: E402
    compare_results,
    gold_hash,
    normalize_result,
)

DATASET = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
_ITEMS = json.loads(DATASET.read_text(encoding="utf-8"))["items"]
ITEMS = {it["id"]: it for it in _ITEMS}

Q98 = ITEMS["E-0098"]["question"]

# ---------------------------------------------------------------- 结构增量检查器


def _sql(e: exp.Expression) -> str:
    return e.sql(dialect="sqlite", normalize=True)


def _tree(sql: str) -> exp.Expression:
    return sqlglot.parse_one(sql, read="sqlite")


def final_select_column_count(sql: str) -> int:
    """最外层 SELECT 的输出列数（结果列契约的核心指标）。"""
    return len(_tree(sql).expressions)


def group_by_keys(sql: str) -> list[str]:
    """**整棵树**（含 CTE）中所有 GROUP BY 表达式的规范化文本。"""
    return sorted({_sql(e) for g in _tree(sql).find_all(exp.Group) for e in g.expressions})


def order_by_keys(sql: str) -> list[str]:
    """最外层 ORDER BY + 所有窗口函数 ORDER BY 的规范化文本。"""
    t = _tree(sql)
    keys: list[str] = []
    top = t.args.get("order")
    if top:
        keys += [_sql(e) for e in top.expressions]
    for w in t.find_all(exp.Window):
        wo = w.args.get("order")
        if wo:
            keys += [_sql(e) for e in wo.expressions]
    return keys


_DATE_TOKENS = ("order_date", "strftime", "substr", "julianday", "date(", "month", "year")


def date_predicates(sql: str) -> set[str]:
    """整棵树中「涉及日期 / 时间」的比较谓词（规范化文本集合）。"""
    out: set[str] = set()
    for n in _tree(sql).find_all(exp.Binary):
        if isinstance(n, (exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.NEQ)):
            s = _sql(n)
            if any(tok in s.lower() for tok in _DATE_TOKENS):
                out.add(s)
    return out


def e11_delta(off_sql: str, on_sql: str) -> dict:
    """E11 开关前后（OFF, ON）的结构增量。"""
    off_g, on_g = set(group_by_keys(off_sql)), set(group_by_keys(on_sql))
    off_d, on_d = date_predicates(off_sql), date_predicates(on_sql)
    off_o, on_o = set(order_by_keys(off_sql)), set(order_by_keys(on_sql))
    return {
        "select_column_count_off": final_select_column_count(off_sql),
        "select_column_count_on": final_select_column_count(on_sql),
        "select_column_count_changed": (
            final_select_column_count(off_sql) != final_select_column_count(on_sql)
        ),
        "group_by_added": sorted(on_g - off_g),
        "group_by_removed": sorted(off_g - on_g),
        "date_predicates_added": sorted(on_d - off_d),
        "date_predicates_removed": sorted(off_d - on_d),
        "date_predicates_changed": off_d != on_d,
        "order_by_added": sorted(on_o - off_o),
        "order_by_removed": sorted(off_o - on_o),
    }


def e11_violations(delta: dict) -> list[str]:
    """把结构增量翻译成 E11 不变量违例码。"""
    v: list[str] = []
    if delta["select_column_count_changed"]:
        v.append("SELECT_COLUMN_COUNT_CHANGED")
    if delta["group_by_added"] or delta["group_by_removed"]:
        v.append("GROUP_BY_GRANULARITY_CHANGED")
    if delta["date_predicates_changed"]:
        v.append("DATE_FILTER_REWRITTEN")
    if delta["order_by_removed"]:
        v.append("ORDER_BY_KEY_REMOVED")
    return v


# ---------------------------------------------------------------- Task 45 真实产物（逐字嵌入）
# 来源：F:/task45_semantic_contract_validation/raw_results.json（Task 45 真实 Bailian 运行）
T45_E0042_OFF = (
    "SELECT o.region, ROUND(SUM(o.total_amount), 2) AS total_sales FROM orders o "
    "WHERE o.status != 'cancelled' GROUP BY o.region ORDER BY total_sales DESC LIMIT 10"
)
T45_E0042_ON = (
    "SELECT o.region AS region_name, ROUND(SUM(o.total_amount), 2) AS total_sales FROM orders o "
    "WHERE o.status != 'cancelled' GROUP BY o.id, o.region "
    "ORDER BY total_sales DESC, o.region ASC LIMIT 10"
)
T45_E0074_OFF = (
    "SELECT c.name AS category_name, SUM(oi.quantity) AS total_sold FROM order_items oi "
    "JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id "
    "JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' "
    "AND o.order_date >= '2025-10-01' AND o.order_date < '2026-01-01' "
    "GROUP BY c.id ORDER BY total_sold DESC LIMIT 3"
)
T45_E0074_ON = (
    "SELECT c.name AS category_name, SUM(oi.quantity) AS total_sold FROM order_items oi "
    "JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id "
    "JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' "
    "AND substr(o.order_date, 1, 7) = '2025-10' "
    "GROUP BY c.id ORDER BY total_sold DESC, c.id LIMIT 3"
)
T45_E0098_OFF = (
    "WITH RankedProducts AS (SELECT c.name AS category_name, p.name AS product_name, "
    "SUM(oi.quantity) AS total_sold, ROW_NUMBER() OVER (PARTITION BY c.id "
    "ORDER BY SUM(oi.quantity) DESC) as rn FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id "
    "WHERE o.status != 'cancelled' GROUP BY c.id, p.id HAVING SUM(oi.quantity) > 50) "
    "SELECT category_name, product_name, total_sold FROM RankedProducts WHERE rn <= 3 "
    "ORDER BY category_name, rn"
)
T45_E0098_ON = (
    "WITH cat_product_sales AS (SELECT c.name AS category_name, p.name AS product_name, "
    "SUM(oi.quantity) AS total_sold, ROW_NUMBER() OVER (PARTITION BY c.id "
    "ORDER BY SUM(oi.quantity) DESC, p.id ASC) AS rn FROM order_items oi "
    "JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id "
    "JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' "
    "GROUP BY c.id, p.id HAVING total_sold > 50) "
    "SELECT category_name, product_name, total_sold FROM cat_product_sales WHERE rn <= 3 "
    "ORDER BY category_name, rn"
)


def _run(sql: str):
    res = execute(sql)
    return list(res.columns), [list(r) for r in res.rows]


def _hash(sql: str) -> str:
    cols, rows = _run(sql)
    return gold_hash(cols, rows)


def _matches_gold(qid: str, sql: str) -> bool:
    """用**评测框架自己的判等口径**比较 sql 与 gold（与 Task 45 harness 逐字一致）。

    注意：不能用裸 `gold_hash` 等值代替 —— `normalize_result` / `compare_results`
    会做归一化（忽略列名、排序、容差），比裸 hash 宽松。Task 45 的 `gold_match`
    就是这样算出来的，此处必须复刻同一口径，否则会得到与 Task 45 相反的结论。
    """
    item = ITEMS[qid]
    slots = item.get("answer_slots") or {}
    value_type = str(slots.get("value_type", ""))
    tolerance = float(slots.get("tolerance") or 0.0)
    order_sensitive = bool(slots.get("order_sensitive", False))
    expected_empty = bool(slots.get("expected_empty", False))

    def _norm(sql_: str):
        cols, rows = _run(sql_)
        return normalize_result(cols, rows, value_type=value_type, tolerance=tolerance,
                                order_sensitive=order_sensitive, expected_empty=expected_empty)

    return bool(compare_results(_norm(item["gold_sql"]), _norm(sql), value_type=value_type,
                                tolerance=tolerance, order_sensitive=order_sensitive).match)


# ================================================================ §0 identity replay
def test_F_gold_identity_replay_all_100_pass():
    """§0 + Test F：100 题 gold 两次重放一致且等于冻结 gold_result_hash。

    探针自检不成立 ⇒ 后续所有结构断言都不可信，故放在最前。
    """
    bad = []
    for it in _ITEMS:
        h1 = _hash(it["gold_sql"])
        h2 = _hash(it["gold_sql"])
        if not (h1 == h2 == it["gold_result_hash"]):
            bad.append(it["id"])
    assert not bad, f"identity replay 失败：{bad}"
    assert len(_ITEMS) == 100


# ================================================================ §1 Test A
def test_A_topn_normal_tiebreak_is_an_orderby_only_change():
    """Test A：E-0098 的 ON 是**允许**的增量 —— 只多了一个 ORDER BY 破平键。"""
    d = e11_delta(T45_E0098_OFF, T45_E0098_ON)
    assert d["order_by_added"] == ["p.id ASC"], d
    assert d["order_by_removed"] == [], d
    assert d["select_column_count_changed"] is False, d
    assert d["group_by_added"] == [] and d["group_by_removed"] == [], d
    assert d["date_predicates_changed"] is False, d
    assert e11_violations(d) == [], e11_violations(d)


def test_A_topn_on_actually_fixes_the_result_offline():
    """Test A（机制侧）：ON 的 SQL 与 gold 判等一致，OFF 的不一致。"""
    assert _matches_gold("E-0098", T45_E0098_ON) is True
    assert _matches_gold("E-0098", T45_E0098_OFF) is False


def test_A_gold_ranking_clause_uses_orderby_tiebreak_only():
    """gold 自身也只在窗口 ORDER BY 里放破平键，最终输出仍是 3 列。"""
    gold = ITEMS["E-0098"]["gold_sql"]
    assert final_select_column_count(gold) == 3
    d = e11_delta(gold, gold)
    assert e11_violations(d) == []
    # 破平键只出现在窗口 ORDER BY 中
    assert "ORDER BY sold DESC, prod_id" in gold
    assert "GROUP BY c.id, p.id, p.name" in gold


# ================================================================ §2 Test B
def test_B_groupby_granularity_regression_is_detected():
    """Test B：Task 45 的真实回归（E-0042 把 o.id 写进 GROUP BY）必须被检查器检出。"""
    d = e11_delta(T45_E0042_OFF, T45_E0042_ON)
    assert d["group_by_added"] == ["o.id"], d
    assert "GROUP_BY_GRANULARITY_CHANGED" in e11_violations(d)
    # 该 ON 确实把正确答案改坏了（离线复算，用评测框架判等口径）
    assert _matches_gold("E-0042", T45_E0042_OFF) is True
    assert _matches_gold("E-0042", T45_E0042_ON) is False


def test_B_groupby_guard_is_not_vacuous_on_clean_sql():
    """反方向：干净的 SQL（只加 ORDER BY 键）不得被误报 GROUP BY 违例。"""
    d = e11_delta(T45_E0098_OFF, T45_E0098_ON)
    assert d["group_by_added"] == []
    assert "GROUP_BY_GRANULARITY_CHANGED" not in e11_violations(d)


def test_B_rule_text_explicitly_forbids_groupby():
    """规则文本必须**显式**禁止把破平键写进 GROUP BY（旧文本完全没提 GROUP BY）。"""
    block = _block()
    assert "禁止把破平键写进 GROUP BY" in block
    assert "GROUP BY …, p.id" in block
    assert "聚合粒度" in block


def _group_by_pk_cols(sql: str) -> set[str]:
    """GROUP BY 中的主键列（本项目约定列名 `id`）—— 聚合粒度的判据。

    与 harness 的 `e11_guard.py` 用同一判据：不比较 GROUP BY 的**精确列集合**，
    因为 `GROUP BY c.id, p.id` 与 `GROUP BY c.id, p.id, p.name` 是同一粒度
    （`p.name` 函数依赖于 `p.id`），精确比较会误报。
    """
    t = _tree(sql)
    cols = {c.name.lower() for g in t.find_all(exp.Group) for e in g.expressions
            for c in e.find_all(exp.Column)}
    return {c for c in cols if c == "id"}


def test_B_grain_criterion_catches_the_real_regression():
    """粒度判据必须能检出 E-0042 的真实回归（`o.id` 被塞进 GROUP BY）。"""
    assert _group_by_pk_cols(T45_E0042_OFF) == set()
    assert _group_by_pk_cols(T45_E0042_ON) == {"id"}  # 粒度被改变


def test_B_grain_criterion_does_not_false_positive_on_dependent_columns():
    """反方向：`GROUP BY c.id, p.id` vs `GROUP BY c.id, p.id, p.name` 是同一粒度，不得误报。"""
    assert _group_by_pk_cols(T45_E0098_OFF) == {"id"}
    assert _group_by_pk_cols(T45_E0098_ON) == {"id"}
    assert _group_by_pk_cols(ITEMS["E-0098"]["gold_sql"]) == {"id"}


# ================================================================ §3 Test C
def test_C_select_column_count_guard():
    """Test C：把破平键写进 SELECT 会增加输出列数 ⇒ 必须被检出。"""
    bad = (
        "SELECT o.region, ROUND(SUM(o.total_amount), 2) AS total_sales, o.id FROM orders o "
        "WHERE o.status != 'cancelled' GROUP BY o.region "
        "ORDER BY total_sales DESC, o.id ASC LIMIT 10"
    )
    d = e11_delta(T45_E0042_OFF, bad)
    assert d["select_column_count_off"] == 2
    assert d["select_column_count_on"] == 3
    assert d["select_column_count_changed"] is True
    assert "SELECT_COLUMN_COUNT_CHANGED" in e11_violations(d)


def test_C_rule_text_explicitly_forbids_select_with_question_exception():
    """规则文本必须禁止写进 SELECT，同时保留「原问题明确要求该字段」的例外。"""
    block = _block()
    assert "禁止把破平键写进 SELECT" in block
    assert "除非原问题本身明确要求输出该字段" in block


# ================================================================ §4 Test D
def test_D_time_filter_rewrite_regression_is_detected():
    """Test D：Task 45 的真实回归（E-0074 把 Q4 区间改写成单月）必须被检出。"""
    d = e11_delta(T45_E0074_OFF, T45_E0074_ON)
    assert d["date_predicates_changed"] is True, d
    assert "DATE_FILTER_REWRITTEN" in e11_violations(d)
    # 离线复算：ON 改坏了正确结果（用评测框架判等口径）
    assert _matches_gold("E-0074", T45_E0074_OFF) is True
    assert _matches_gold("E-0074", T45_E0074_ON) is False


def test_D_date_guard_is_not_vacuous_on_clean_sql():
    """反方向：不含日期条件的 SQL 不得被误报日期违例。"""
    d = e11_delta(T45_E0098_OFF, T45_E0098_ON)
    assert d["date_predicates_changed"] is False
    assert "DATE_FILTER_REWRITTEN" not in e11_violations(d)


def test_D_rule_text_explicitly_forbids_touching_time_filters():
    block = _block()
    assert "禁止因为本契约改动 WHERE / HAVING" in block
    assert "substr(order_date, 1, 7) = '2025-10'" in block  # 显式反例


# ================================================================ §5 Test E
def test_E_scalar_top1_still_not_triggered():
    """Test E：标量 Top-1（只问指标值）继续保持 E11 不触发。"""
    scalars = ["E-0009", "E-0010", "E-0015", "E-0032", "E-0038"]
    for qid in scalars:
        assert detect_ranking_tiebreak(ITEMS[qid]["question"]) is None, qid
    # 这些题在 E11 开启时也不得被注入
    import os

    prev = os.environ.get("SQLGEN_EXTRA_RULES")
    os.environ["SQLGEN_EXTRA_RULES"] = "E11"
    try:
        for qid in scalars:
            assert ranking_tiebreak_block(ITEMS[qid]["question"]) == "", qid
    finally:
        if prev is None:
            os.environ.pop("SQLGEN_EXTRA_RULES", None)
        else:
            os.environ["SQLGEN_EXTRA_RULES"] = prev


# ================================================================ §6 规则文本契约
def _block() -> str:
    import os

    prev = os.environ.get("SQLGEN_EXTRA_RULES")
    os.environ["SQLGEN_EXTRA_RULES"] = "E11"
    try:
        return ranking_tiebreak_block(Q98)
    finally:
        if prev is None:
            os.environ.pop("SQLGEN_EXTRA_RULES", None)
        else:
            os.environ["SQLGEN_EXTRA_RULES"] = prev


def test_rule_text_declares_the_single_allowed_effect():
    """收窄的核心：文本必须声明「唯一作用是追加 ORDER BY 破平键」。"""
    block = _block()
    assert "append-only ORDER BY contract" in block
    assert "唯一允许的改动" in block
    assert "末尾追加" in block
    assert "除排序外" in block


def test_rule_text_contains_all_four_prohibitions():
    block = _block()
    for anchor in (
        "禁止把破平键写进 GROUP BY",
        "禁止把破平键写进 SELECT",
        "禁止因为本契约改动 WHERE / HAVING",
        "禁止因为本契约改变原有聚合粒度",
    ):
        assert anchor in block, anchor


def test_rule_text_still_keeps_primary_key_preference():
    block = _block()
    assert "orders.id" in block and "products.id" in block and "categories.id" in block
    assert "ORDER BY 指标 DESC, p.id ASC" in block


# ================================================================ §7 触发面 / 开关
def test_trigger_face_unchanged_at_25_questions():
    """收窄只改文本，不改 detector ⇒ 触发面必须仍是 25 题。"""
    trig = [it["id"] for it in _ITEMS if detect_ranking_tiebreak(it["question"])]
    assert len(trig) == 25, trig
    assert "E-0098" in trig and "E-0042" in trig and "E-0074" in trig


def test_e11_off_is_byte_identical_to_baseline():
    """默认关闭 ⇒ semantic 段为空 ⇒ Prompt 与冻结基线逐字节相同。"""
    import os

    from app.fewshot.models import FewShotResult
    from app.schemas.schema_link import SchemaLinkResult

    link = SchemaLinkResult(question="q", tables=["orders"], columns=["orders.id"],
                            reasons=[], confidence=0.9)
    fs = FewShotResult(question="q", matches=[])
    prev = os.environ.get("SQLGEN_EXTRA_RULES")
    os.environ.pop("SQLGEN_EXTRA_RULES", None)
    try:
        off_prompt = build_prompt(Q98, link, fs)
        assert semantic_contract_block(Q98) == ""
    finally:
        if prev is not None:
            os.environ["SQLGEN_EXTRA_RULES"] = prev
    os.environ["SQLGEN_EXTRA_RULES"] = "E11"
    try:
        on_prompt = build_prompt(Q98, link, fs)
    finally:
        if prev is None:
            os.environ.pop("SQLGEN_EXTRA_RULES", None)
        else:
            os.environ["SQLGEN_EXTRA_RULES"] = prev
    assert on_prompt != off_prompt
    assert _block() in on_prompt


def test_other_flags_do_not_leak_into_e11_block():
    """只开 E11 时，E9 / E10 的段落不得出现。"""
    block = _block()
    assert "全局口径 / 参照基准约束" not in block
    assert "比值方向契约" not in block


# ================================================================ §8 检查器自检
@pytest.mark.parametrize(
    "off_sql,on_sql,expected",
    [
        # 纯 ORDER BY 追加 ⇒ 无违例
        ("SELECT a, b FROM t ORDER BY b DESC",
         "SELECT a, b FROM t ORDER BY b DESC, a ASC", []),
        # GROUP BY 追加 ⇒ 违例
        ("SELECT a, SUM(b) FROM t GROUP BY a ORDER BY SUM(b) DESC",
         "SELECT a, SUM(b) FROM t GROUP BY a, a.id ORDER BY SUM(b) DESC", ["GROUP_BY_GRANULARITY_CHANGED"]),
        # SELECT 多一列 ⇒ 违例
        ("SELECT a, b FROM t ORDER BY b DESC",
         "SELECT a, b, a.id FROM t ORDER BY b DESC", ["SELECT_COLUMN_COUNT_CHANGED"]),
        # 日期过滤被改写 ⇒ 违例
        ("SELECT a FROM t WHERE t.order_date >= '2025-10-01' AND t.order_date < '2026-01-01'",
         "SELECT a FROM t WHERE substr(t.order_date, 1, 7) = '2025-10'", ["DATE_FILTER_REWRITTEN"]),
        # ORDER BY 键被删 ⇒ 违例
        ("SELECT a, b FROM t ORDER BY b DESC, a ASC",
         "SELECT a, b FROM t ORDER BY b DESC", ["ORDER_BY_KEY_REMOVED"]),
    ],
)
def test_checker_is_not_vacuous(off_sql, on_sql, expected):
    """§8：检查器必须能区分「允许的增量」与「四类误用」，不能永远返回空。"""
    assert e11_violations(e11_delta(off_sql, on_sql)) == expected
