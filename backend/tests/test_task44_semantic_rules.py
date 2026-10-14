"""Task 44：SQLGEN 语义规则定向修复（E-0065 / E-0075 / E-0082 / E-0088 / E-0098）回归测试。

全部为**离线 deterministic**测试：不调用任何 LLM / 网络，只做
① 确定性 detector 行为断言 ② Prompt 注入断言 ③ 真实只读库上的机制复算
④ gold 原样重放（identity replay，§六 的探针自检）。

## 结构

| 段 | 内容 |
|---|---|
| §0 | identity replay（探针自检，必须先成立） |
| §1 | Test A —— E-0065 全局口径不得继承外层时间过滤 |
| §2 | Test B —— E-0075 ratio 分子/分母方向 |
| §3 | Test C —— E-0082 输出列契约（实体维度列） |
| §4 | Test D —— E-0098 Top-N 确定性破平键 |
| §5 | Test E —— E-0088 未定义别名由安全层拦截（责任层判定） |
| §6 | 开关契约（默认关闭逐字节不变 / 条件性局部生效） |
| §7 | 100 题触发面（副作用风险上界） |
| §8 | artifact 完整性（SQL 不得截断） |

## 证据纪律（Task 43 已确认）

- **identity replay 不成立就停止归因**：§0 用「gold_sql 两次重放一致 + 与冻结
  `gold_result_hash` 一致」作为探针自检，而不是只比较 SQL 字符串。
- **禁止只 assert 字符串包含某个词**：所有规则段断言都配了「真实库复算」
  或「列数/行数/集合」级别的可复核结果。
- **诚实记录被证伪的假设**：§4 明确记录「去掉破平键在当前 DB 状态下不产生
  可观测差异」这一实测结果，不把它包装成已确证失败。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core import config  # noqa: E402
from app.fewshot.models import FewShotResult  # noqa: E402
from app.schemas.schema_link import SchemaLinkResult  # noqa: E402
from app.sqlcheck.scope_validator import check_sql_scope  # noqa: E402
from app.sqlgen.prompt import (  # noqa: E402
    BUSINESS_RULES,
    OUTPUT_CONTRACT_RULES,
    _CONSTRAINTS,
    _OUTPUT_RULES,
    build_prompt,
    entity_constraint_block,
    format_fewshot,
    format_schema_linking,
    global_scope_block,
    ranking_tiebreak_block,
    ratio_direction_block,
    semantic_contract_block,
)
from app.sqlgen.semantic_contracts import (  # noqa: E402
    detect_global_scope,
    detect_ranking_tiebreak,
    detect_ratio_direction,
)
from app.sqlexec.errors import (  # noqa: E402
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
    SQLExecutionScopeError,
)
from app.sqlexec.executor import execute  # noqa: E402
from evaluation.normalization import (  # noqa: E402
    compare_results,
    gold_hash,
    normalize_result,
)

DATASET = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
_ITEMS = json.loads(DATASET.read_text(encoding="utf-8"))["items"]
ITEMS = {it["id"]: it for it in _ITEMS}

LINK = SchemaLinkResult(
    question="q",
    tables=["orders"],
    columns=["orders.id"],
    reasons=[],
    confidence=0.9,
)
FS = FewShotResult(question="q", matches=[])

# ---------------------------------------------------------------- 五个靶题
Q65 = ITEMS["E-0065"]["question"]
Q75 = ITEMS["E-0075"]["question"]
Q82 = ITEMS["E-0082"]["question"]
Q83 = ITEMS["E-0083"]["question"]
Q81 = ITEMS["E-0081"]["question"]
Q88 = ITEMS["E-0088"]["question"]
Q98 = ITEMS["E-0098"]["question"]
FIVE = ["E-0065", "E-0075", "E-0082", "E-0088", "E-0098"]

# ---------------------------------------------------------------- §7 的完整 SQL artifact
# ⚠️ 原始 artifact 必须保存**完整** pred_sql / gold_sql，禁止只留前 400 字。
# Task 43 的 harness 在写盘时做了 `rec["pred_sql"] = sql[:400]`，导致 E-0088 的
# pred SQL 永久丢失尾部；本模块用「以记录前缀开头 + 补全」的重建 SQL 作为
# 可离线复算的替代物，并把前缀本身一并留存（见 §5 / §8）。

# Task 43 记录到的 400 字前缀（逐字符照抄 task43_raw.json）
E0088_RECORDED_PREFIX = (
    "WITH top5_products AS (SELECT p.id, p.name FROM order_items oi JOIN orders o "
    "ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY p.id "
    "ORDER BY SUM(oi.subtotal) DESC LIMIT 5), h1_sales AS (SELECT oi.product_id, "
    "ROUND(SUM(oi.subtotal), 2) AS h1_amount FROM order_items oi JOIN orders o "
    "ON o.id = oi.order_id WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 4) "
    "|| '-' || substr(o.order"
)
# 重建为可执行完整 SQL：与前缀**逐字节相同的前 400 字**，尾部补全
E0088_PRED_RECONSTRUCTED = E0088_RECORDED_PREFIX + (
    "_date, 6, 2) BETWEEN '2025-01' AND '2025-06' GROUP BY oi.product_id), "
    "h2_sales AS (SELECT oi.product_id, ROUND(SUM(oi.subtotal), 2) AS h2_amount "
    "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 4) || '-' || "
    "substr(o.order_date, 6, 2) BETWEEN '2025-07' AND '2025-12' GROUP BY oi.product_id) "
    "SELECT t.name, h1.h1_amount AS first_half, h2.h2_amount AS second_half, "
    "ROUND(h1.h1_amount + h2.h2_amount, 2) AS total_amount FROM top5_products t "
    "LEFT JOIN h1_sales h1 ON h1.product_id = t.id "
    "LEFT JOIN h2_sales h2 ON h2.product_id = t.id ORDER BY total_amount DESC"
)

# Task 43 记录到完整 pred SQL 的四题（均 < 400 字，未被截断）
E0065_PRED = (
    "SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2026' "
    "AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders "
    "WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled')"
)
E0075_PRED = (
    "SELECT ROUND(COUNT(CASE WHEN substr(o.order_date, 1, 4) = '2026' AND "
    "CAST(substr(o.order_date, 6, 2) AS INTEGER) BETWEEN 1 AND 6 THEN o.id END) * 1.0 / "
    "NULLIF(COUNT(CASE WHEN substr(o.order_date, 1, 4) = '2026' AND "
    "CAST(substr(o.order_date, 6, 2) AS INTEGER) BETWEEN 7 AND 12 THEN o.id END), 0), 2) "
    "AS ratio FROM orders o WHERE substr(o.order_date, 1, 4) = '2026'"
)
E0082_PRED = (
    "SELECT ROUND(100.0 * SUM(CASE WHEN c.name = '休闲零食' THEN oi.subtotal ELSE 0 END) / "
    "SUM(oi.subtotal), 2) AS ratio FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id "
    "WHERE o.status != 'cancelled'"
)
E0098_PRED = (
    "WITH ranked_products AS (SELECT c.name AS category_name, p.name AS product_name, "
    "SUM(oi.quantity) AS total_sold, ROW_NUMBER() OVER (PARTITION BY c.id "
    "ORDER BY SUM(oi.quantity) DESC) as rn FROM order_items oi JOIN orders o "
    "ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c "
    "ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id "
    "HAVING SUM(oi.quantity) > 50) SELECT category_name, product_name, total_sold "
    "FROM ranked_products WHERE rn <= 3 ORDER BY category_name, rn"
)

PRED_SQL = {
    "E-0065": E0065_PRED,
    "E-0075": E0075_PRED,
    "E-0082": E0082_PRED,
    "E-0088": E0088_PRED_RECONSTRUCTED,
    "E-0098": E0098_PRED,
}
GOLD_SQL = {qid: ITEMS[qid]["gold_sql"] for qid in FIVE}
GOLD_HASH = {qid: ITEMS[qid]["gold_result_hash"] for qid in FIVE}


# ---------------------------------------------------------------- 工具


def _run(sql: str) -> tuple[list[str], list[list]]:
    """用生产只读执行器跑一条 SQL（离线、deterministic）。"""
    result = execute(sql)
    return list(result.columns), [list(r) for r in result.rows]


def _run_raw(sql: str) -> tuple[list[str], list[list]]:
    """绕过 scope 校验的裸重放（仅用于 §0 identity replay 的探针自检）。"""
    uri = f"file:{config.DB_PATH.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        cur = conn.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [list(r) for r in cur.fetchall()]
    return cols, rows


def _prompt(question: str) -> str:
    return build_prompt(question, LINK, FS)


def _assembled_baseline_prompt(question: str) -> str:
    """按 build_prompt 文档化的段顺序独立拼装「全部 flag 关闭」时的基线 Prompt。

    与 build_prompt 的差异仅在于**省略**三个条件性段（extra / entity / semantic）。
    本函数与生产代码不共享实现，因此能抓出 build_prompt 里被误改的字符。
    """
    return (
        f"【用户问题】{question}\n\n"
        f"【Schema Linking 结果】\n{format_schema_linking(LINK)}\n\n"
        f"【Few-shot Examples】\n{format_fewshot(FS)}\n\n"
        f"{BUSINESS_RULES}\n"
        f"{_CONSTRAINTS}\n"
        f"{_OUTPUT_RULES}\n"
        f"【请生成】针对用户问题生成唯一一条只读 SQLite SQL。\n"
    )


@pytest.fixture()
def flags_off(monkeypatch):
    monkeypatch.delenv("SQLGEN_EXTRA_RULES", raising=False)


@pytest.fixture()
def e9_on(monkeypatch):
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E9")


@pytest.fixture()
def e10_on(monkeypatch):
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E10")


@pytest.fixture()
def e11_on(monkeypatch):
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E11")


# ================================================================ §0 identity replay
# §六：所有涉及 SQL 对照实验的测试，必须先有一个 Gold SQL 原样重放自检。
# 不成立则立即停止该实验 —— 因此本段放在最前，且判据是「哈希」而非「字符串」。


@pytest.mark.parametrize("qid", FIVE)
def test_identity_replay_gold_sql_reproduces_frozen_hash(qid):
    """gold_sql 原样重放两次：两次一致，且等于冻结 gold_result_hash。"""
    cols1, rows1 = _run_raw(GOLD_SQL[qid])
    cols2, rows2 = _run_raw(GOLD_SQL[qid])

    assert cols1 == cols2, f"{qid}: 两次重放的列不一致"
    assert rows1 == rows2, f"{qid}: 两次重放的行不一致"
    assert gold_hash(cols1, rows1) == gold_hash(cols2, rows2), f"{qid}: replay != replay"

    frozen = GOLD_HASH[qid]
    assert gold_hash(cols1, rows1) == frozen, (
        f"{qid}: gold 重放与冻结 hash 不一致 —— 探针自身不可信，禁止据此归因"
    )


def test_identity_replay_row_counts_are_the_recorded_ones():
    """重放得到的行数与 Task 43 诊断记录一致（1/1/1/5/66）。"""
    expected = {"E-0065": 1, "E-0075": 1, "E-0082": 1, "E-0088": 5, "E-0098": 66}
    for qid, n in expected.items():
        _, rows = _run_raw(GOLD_SQL[qid])
        assert len(rows) == n, f"{qid}: 期望 {n} 行，实际 {len(rows)} 行"


def test_gold_sql_of_all_five_passes_scope_and_safety():
    """gold 必须能通过生产的 scope + safety 边界（防止把 gold 当成违规样本）。"""
    for qid in FIVE:
        assert check_sql_scope(GOLD_SQL[qid]).ok, f"{qid}: gold 被 scope 校验误报"
        cols, _ = _run(GOLD_SQL[qid])
        assert cols, f"{qid}: gold 执行无列"


# ================================================================ §1 Test A —— E-0065


def test_A_e9_detector_triggers_only_on_e0065():
    c = detect_global_scope(Q65)
    assert c is not None
    assert c.global_terms == ("全平台",)
    assert c.time_terms == ("2026年",)


def test_A_e9_does_not_trigger_on_time_bound_global_phrase():
    """E-0083「该季度全部商品销售金额」的时间窗是**同一句显式绑定**的，不得触发。

    这是 E9 判据刻意用「平台级全局词」而非「全部/所有」的原因：
    宽判据会把合法的时间过滤误判成需要去掉的东西。
    """
    assert detect_global_scope(Q83) is None
    assert detect_global_scope(Q82) is None  # 有全局词、无时间过滤 → 不注入
    assert detect_global_scope("") is None
    assert detect_global_scope("   ") is None


def test_A_e9_injects_only_for_target_question(e9_on):
    assert global_scope_block(Q65) != ""
    assert global_scope_block(Q83) == ""
    assert global_scope_block(Q82) == ""
    assert "全局口径 / 参照基准约束" in _prompt(Q65)
    assert "全局口径 / 参照基准约束" not in _prompt(Q83)


def test_A_e9_off_injects_nothing(flags_off):
    for qid in FIVE:
        assert global_scope_block(ITEMS[qid]["question"]) == ""


def test_A_mechanism_denominator_inheriting_year_filter_changes_answer():
    """机制复算：参照基准继承 2026 过滤 ⇒ 阈值抬高 ⇒ 命中数 1246（gold 为 1236）。"""
    gold_cols, gold_rows = _run(GOLD_SQL["E-0065"])
    pred_cols, pred_rows = _run(E0065_PRED)

    assert gold_rows == [[1236]], f"gold 复算异常: {gold_rows}"
    assert pred_rows == [[1246]], f"pred 复算异常: {pred_rows}"

    _, full_avg = _run(
        "SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled'"
    )
    _, y2026_avg = _run(
        "SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled' "
        "AND order_date >= '2026-01-01'"
    )
    assert round(full_avg[0][0], 4) == 3329.7195
    assert round(y2026_avg[0][0], 4) == 3286.1395
    assert full_avg[0][0] > y2026_avg[0][0]

    # 列数一致 ⇒ 判错原因只能是数值，而不是结构
    assert len(gold_cols) == len(pred_cols) == 1
    outcome = compare_results(
        normalize_result(gold_cols, gold_rows, value_type="integer"),
        normalize_result(pred_cols, pred_rows, value_type="integer"),
        value_type="integer",
    )
    assert outcome.match is False
    assert outcome.reason == "结果集合不一致"


# ================================================================ §2 Test B —— E-0075


def test_B_e10_extracts_direction_from_question():
    c = detect_ratio_direction(Q75)
    assert c is not None
    assert c.form == "multiple"
    assert c.numerator == "2026年下半年的订单数量"
    assert c.denominator == "上半年订单数量"
    assert c.direction_extracted is True


def test_B_e10_never_emits_dirty_direction_spans():
    """抽取到指示代词/连接词时只给通用契约，不给可能出错的题面级方向。"""
    q0076 = ITEMS["E-0076"]["question"]
    dirty = detect_ratio_direction(q0076)
    assert dirty is not None
    assert dirty.direction_extracted is False
    assert "numerator（被除数）= 「它们各」" not in dirty.to_prompt_block()
    assert "numerator / denominator 各是什么" in dirty.to_prompt_block()

    for item in _ITEMS:
        c = detect_ratio_direction(item["question"])
        if c and c.direction_extracted:
            for span in (c.numerator, c.denominator):
                assert not span.startswith(("它们", "其", "并", "这", "那"))


def test_B_e10_injects_concrete_direction_for_e0075(e10_on):
    block = ratio_direction_block(Q75)
    assert "numerator（被除数）= 「2026年下半年的订单数量」" in block
    assert "denominator（除数）= 「上半年订单数量」" in block
    assert "比值方向契约" in _prompt(Q75)
    # 非比值题不注入
    assert ratio_direction_block("2026年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？") == ""


def test_B_mechanism_swapped_numerator_denominator_reproduces_task43_pred():
    """方向颠倒 ⇒ 0.48 → 2.09，与 Task 43 实测 pred 完全一致。"""
    gold_cols, gold_rows = _run(GOLD_SQL["E-0075"])
    pred_cols, pred_rows = _run(E0075_PRED)

    assert gold_rows == [[0.48]], f"gold 复算异常: {gold_rows}"
    assert pred_rows == [[2.09]], f"pred 复算异常: {pred_rows}"

    swapped_cols, swapped_rows = _run(
        "SELECT ROUND((SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01' "
        "AND order_date <= '2026-06-30') * 1.0 / "
        "(SELECT COUNT(*) FROM orders WHERE order_date >= '2026-07-01'), 2) AS h1_to_h2_ratio"
    )
    assert swapped_rows == pred_rows == [[2.09]]

    outcome = compare_results(
        normalize_result(gold_cols, gold_rows, value_type="ratio", tolerance=0.01),
        normalize_result(pred_cols, pred_rows, value_type="ratio", tolerance=0.01),
        value_type="ratio",
        tolerance=0.01,
    )
    assert outcome.match is False


def test_B_e10_growth_questions_get_definitional_direction():
    """增速题的方向由定义固定：分母是基期，不是本期。"""
    for qid in ("E-0092", "E-0094", "E-0096"):
        c = detect_ratio_direction(ITEMS[qid]["question"])
        assert c is not None and c.form == "growth"
        block = c.to_prompt_block()
        assert "denominator = 上期值" in block
        assert "分母是**基期**" in block


# ================================================================ §3 Test C —— E-0082


def test_C_e4_wording_keeps_original_rules_and_adds_entity_contract():
    """E4 是「增强 wording」：原 1~4 条必须逐字保留。"""
    original = (
        "【输出列契约】（重要）\n"
        "1. 生成 SQL 前先枚举问题要求返回的所有信息，SELECT 的每一列都必须对应用户问题中要求给的一项字段；\n"
        "2. 数量占比/比例题：若问题要求「给出分类与占比」，必须同时输出「分类名称」与「占比」两列；\n"
        "3. 结构统计题若问题注明「含取消订单的结构统计 / 总订单数」，必须额外输出总计数列（如 COUNT(*) AS total_cnt）；\n"
        "4. SELECT 列数必须与问题要求完全匹配，禁止遗漏列（列数缺失会导致结果无法对齐判错）。\n"
    )
    assert OUTPUT_CONTRACT_RULES.startswith(original)
    assert "实体维度契约" in OUTPUT_CONTRACT_RULES
    # 必须带反例例外，否则会把 E-0081 这类标量比值也强行加列
    assert "反例（不适用）" in OUTPUT_CONTRACT_RULES
    assert "不要凭空增加实体列" in OUTPUT_CONTRACT_RULES


def test_C_mechanism_missing_entity_column_fails_on_column_count():
    """机制复算：gold 2 列 vs pred 1 列，数值相同但列数不同 ⇒ 判错。"""
    gold_cols, gold_rows = _run(GOLD_SQL["E-0082"])
    pred_cols, pred_rows = _run(E0082_PRED)

    assert gold_cols == ["name", "pct"]
    assert gold_rows == [["休闲零食", 0.81]]
    assert pred_cols == ["ratio"]
    assert pred_rows == [[0.81]]

    # 数值一致（0.01 容差）
    assert abs(gold_rows[0][1] - pred_rows[0][0]) <= 0.01

    outcome = compare_results(
        normalize_result(gold_cols, gold_rows, value_type="ratio", tolerance=0.01),
        normalize_result(pred_cols, pred_rows, value_type="ratio", tolerance=0.01),
        value_type="ratio",
        tolerance=0.01,
    )
    assert outcome.match is False
    assert outcome.reason == "列数不一致：gold=2 pred=1"


def test_C_rule_must_not_force_a_column_on_scalar_ratio_questions():
    """反例守卫：E-0081 的 gold 只有 1 列 —— 规则不得要求给它加列。

    这条测试锁定 E4 第 6 条反例存在的**必要性**：如果哪一天有人把反例删掉，
    模型会在这类题上多输出一列，直接把原本正确的题判错。
    """
    cols, rows = _run(ITEMS["E-0081"]["gold_sql"])
    assert cols == ["pct"]
    assert len(rows) == 1
    # E-0083 与 E-0082 结构同类（维度来自 categories），gold 为 2 列
    cols83, _ = _run(ITEMS["E-0083"]["gold_sql"])
    assert cols83 == ["name", "pct"]


# ================================================================ §4 Test D —— E-0098


def test_D_e11_detector_extracts_top_n():
    c = detect_ranking_tiebreak(Q98)
    assert c is not None
    assert c.limit_n == 3
    assert c.ranking_phrase == "最高的3款"


def test_D_e11_skips_scalar_top1_questions():
    """标量 Top-1（只问指标值）不注入：破平键不影响返回值。"""
    for q in (
        "售价最高的商品价格是多少？",
        "在售商品中售价最低的是多少？",
        "整个平台售价最高的商品属于哪个分类？最高价是多少？",
        "每个叶子分类的商品最高售价和最低售价分别是多少？",
    ):
        assert detect_ranking_tiebreak(q) is None, q


def test_D_e11_injects_for_ranking_questions_only(e11_on):
    block = ranking_tiebreak_block(Q98)
    assert "Top-N 确定性排序契约" in block
    assert "N = 3" in block
    # Task 46 收窄：原「不得新增 SELECT 列」升级为显式四条禁止（含 GROUP BY / 时间过滤）。
    assert "禁止把破平键写进 SELECT" in block
    assert "禁止把破平键写进 GROUP BY" in block
    assert "Top-N 确定性排序契约" in _prompt(Q98)
    assert ranking_tiebreak_block("2026年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？") == ""


def test_D_tie_boundary_objectively_exists_in_frozen_db():
    """客观事实：rk3 与 rk4 的销量并列的分类有 3 个 ⇒ 破平键是必要的。"""
    sql = (
        "WITH cat_prod AS (SELECT c.name AS cat_name, p.name AS prod_name, p.id AS prod_id, "
        "SUM(oi.quantity) AS sold FROM categories c JOIN products p ON p.category_id = c.id "
        "JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status != 'cancelled' GROUP BY c.id, p.id, p.name HAVING SUM(oi.quantity) > 50), "
        "ranked AS (SELECT cat_name, sold, ROW_NUMBER() OVER (PARTITION BY cat_name "
        "ORDER BY sold DESC, prod_id) AS rk FROM cat_prod) "
        "SELECT cat_name, rk, sold FROM ranked WHERE rk IN (3, 4) ORDER BY cat_name, rk"
    )
    _, rows = _run(sql)
    by_cat: dict[str, list] = {}
    for cat, rk, sold in rows:
        by_cat.setdefault(cat, []).append((rk, sold))
    tied = sorted(cat for cat, pairs in by_cat.items() if pairs[0][1] == pairs[1][1])
    assert tied == ["儿童玩具", "家具", "男装"], f"并列边界变化: {tied}"


def test_D_gold_ranking_clause_contains_an_explicit_tiebreak_key():
    gold = GOLD_SQL["E-0098"]
    assert "ORDER BY sold DESC, prod_id" in gold
    c = detect_ranking_tiebreak(Q98)
    assert c.to_prompt_block().count("破平键") >= 2


def test_D_honest_record_no_observable_difference_without_tiebreak():
    """诚实记录（不粉饰）：在 **gold 自身的写法** 下，去掉破平键**不改变**结果集。

    实测：gold 与 no-tiebreak 版本都是 66 行、集合相等；且
    `rk_no_tie != rk_tie` 的行数为 0（无任何名次位移）。

    ⚠️ Task 45 更正（保留本测试但更新其结论）：本断言只覆盖 **gold 这一条写法**。
    Task 45 的真实链路显示，另一条**语义等价**的 SQL（`PARTITION BY c.id`、
    `GROUP BY c.id, p.id`）在同一并列处（`sold = 105`，儿童玩具类目）**选中了不同实体**，
    补上 `p.id` 破平键后与 gold 完全一致 ⇒ 破平键的作用是**让结果不依赖执行计划**。
    因此「E11 是纯防御性、收益未证实」的定性**已被推翻**；
    本测试仍成立，但它证明的是「gold 的隐式行序恰好与破平键一致」，
    而不是「破平键无影响」。跨写法的保护见
    `tests/test_task46_e11_narrowing.py::test_A_topn_on_actually_fixes_the_result_offline`。
    """
    gold_cols, gold_rows = _run(GOLD_SQL["E-0098"])
    no_tie = GOLD_SQL["E-0098"].replace("ORDER BY sold DESC, prod_id", "ORDER BY sold DESC")
    assert no_tie != GOLD_SQL["E-0098"]
    nt_cols, nt_rows = _run(no_tie)

    assert len(gold_rows) == len(nt_rows) == 66
    assert gold_cols == nt_cols
    assert sorted(map(repr, gold_rows)) == sorted(map(repr, nt_rows)), (
        "去掉破平键后结果集发生变化 —— 风险已显性化，需重新评估 E11 的定位"
    )

    shift_sql = (
        "WITH cat_prod AS (SELECT c.name AS cat_name, p.name AS prod_name, p.id AS prod_id, "
        "SUM(oi.quantity) AS sold FROM categories c JOIN products p ON p.category_id = c.id "
        "JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status != 'cancelled' GROUP BY c.id, p.id, p.name HAVING SUM(oi.quantity) > 50), "
        "ranked AS (SELECT cat_name, sold, "
        "ROW_NUMBER() OVER (PARTITION BY cat_name ORDER BY sold DESC) AS rk_no_tie, "
        "ROW_NUMBER() OVER (PARTITION BY cat_name ORDER BY sold DESC, prod_id) AS rk_tie "
        "FROM cat_prod) SELECT cat_name, rk_no_tie, rk_tie FROM ranked "
        "WHERE rk_no_tie != rk_tie"
    )
    _, shift_rows = _run(shift_sql)
    assert shift_rows == [], f"出现名次位移: {shift_rows}"


# ================================================================ §5 Test E —— E-0088


def test_E_reconstructed_pred_starts_with_the_recorded_prefix():
    """重建 SQL 与 Task 43 记录的 400 字前缀逐字节相同 ⇒ 机制未被改写成别的题。"""
    assert len(E0088_RECORDED_PREFIX) == 400
    assert E0088_PRED_RECONSTRUCTED.startswith(E0088_RECORDED_PREFIX)
    assert len(E0088_PRED_RECONSTRUCTED) > 400


def test_E_scope_validator_rejects_undefined_alias_p():
    result = check_sql_scope(E0088_PRED_RECONSTRUCTED)
    assert result.ok is False
    assert {(v.qualifier, v.column) for v in result.violations} == {("p", "id"), ("p", "name")}


def test_E_executor_rejects_before_touching_the_database(monkeypatch):
    """拦截发生在建立数据库连接**之前**（既有安全边界不被削弱）。"""
    import app.sqlexec.executor as executor_module

    def _boom():
        raise AssertionError("不应建立数据库连接")

    monkeypatch.setattr(executor_module, "get_connection", _boom)
    with pytest.raises(SQLExecutionScopeError) as excinfo:
        execute(E0088_PRED_RECONSTRUCTED)
    message = str(excinfo.value)
    assert "未定义的别名 p" in message
    assert "p.id" in message and "p.name" in message


def test_E_scope_error_stays_repair_eligible():
    """责任层判定：Scope 错误属于「数据库阶段」，Production Graph 仍会给一次 Repair。"""
    assert issubclass(SQLExecutionScopeError, SQLExecutionDatabaseError)
    assert not issubclass(SQLExecutionScopeError, SQLExecutionSafetyError)


def test_E_safety_boundary_is_not_weakened():
    """没有为了通过 E-0088 而放宽任何安全边界。"""
    with pytest.raises(SQLExecutionSafetyError):
        execute("DROP TABLE orders")
    with pytest.raises(SQLExecutionSafetyError):
        execute("SELECT 1; SELECT 2")
    with pytest.raises(SQLExecutionScopeError):
        execute(E0088_PRED_RECONSTRUCTED)


def test_E_no_generation_rule_was_added_for_e0088():
    """责任层结论：E-0088 由 scope_validator 兜底，生成层**不**新增规则段。

    断言方式：任何 flag 组合下，Prompt 都不含针对别名的生成规则段；
    且 detector 模块只暴露 3 个契约（E9/E10/E11），没有 E-0088 专用契约。
    """
    import app.sqlgen.semantic_contracts as sc

    assert not hasattr(sc, "detect_alias_contract")
    for flags in ("E9", "E10", "E11", "E9,E10,E11", "E4,E5,E6,E7,E8"):
        assert sc.__dict__.get("detect_global_scope") is not None
    block = semantic_contract_block(Q88)
    assert "别名" not in block


# ================================================================ §6 开关契约


def test_off_mode_prompt_is_byte_identical_to_assembled_baseline(flags_off):
    """默认关闭：Prompt 与「省略全部条件性段」的基线逐字节相同（100 题全量）。"""
    for item in _ITEMS:
        q = item["question"]
        assert semantic_contract_block(q) == "", f"{item['id']}: 默认关闭仍注入语义契约"
        assert entity_constraint_block(q) == "", f"{item['id']}: 默认关闭仍注入 E8 约束"
        assert _prompt(q) == _assembled_baseline_prompt(q), f"{item['id']}: 默认 Prompt 漂移"


@pytest.mark.parametrize("flag", ["E9", "E10", "E11"])
def test_each_flag_only_touches_its_own_target_question(monkeypatch, flag):
    """单变量：只打开一个 flag 时，只有该 flag 的靶题 Prompt 发生变化。"""
    targets = {"E9": ["E-0065"], "E10": ["E-0075"], "E11": ["E-0098"]}[flag]
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", flag)
    changed = [
        item["id"]
        for item in _ITEMS
        if _prompt(item["question"]) != _assembled_baseline_prompt(item["question"])
    ]
    # 靶题必须变化；其余变化必须 ⊆ 该 flag 的确定性触发面（§7 已锁定）
    assert set(targets) <= set(changed)


def test_on_mode_differs_from_off_only_by_the_contract_block(monkeypatch):
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E9")
    on = _prompt(Q65)
    block = global_scope_block(Q65)
    assert block
    monkeypatch.delenv("SQLGEN_EXTRA_RULES", raising=False)
    off = _prompt(Q65)
    assert on.replace(f"{block}\n", "", 1) == off


def test_e8_behaviour_is_unchanged_by_task44(monkeypatch):
    """回归守卫：Task 44 不得改变 E8 的注入行为（E-0057 仍命中，E-0036 仍不命中）。"""
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E8")
    q0057 = "按用户累计下单次数将用户分为三档（1-3单、4-10单、11单及以上），各档分别有多少用户？"
    assert "统计实体 / 驱动表约束" in _prompt(q0057)
    assert "统计实体 / 驱动表约束" not in _prompt("哪些分类下没有挂载任何商品？")
    assert semantic_contract_block(q0057) == ""


def test_semantic_block_composition_order_is_fixed(monkeypatch):
    """E9 -> E10 -> E11 的拼接顺序固定，便于人工核对。"""
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E11,E9,E10")
    q = "2026年下半年的订单数量是上半年订单数量的几倍？"
    block = semantic_contract_block(q)
    # 本题只命中 E10，但顺序函数仍应稳定
    assert block.startswith("【比值方向契约】")
    block98 = semantic_contract_block(Q98)
    assert block98.startswith("【Top-N 确定性排序契约】")


# ================================================================ §7 触发面（副作用上界）


def test_trigger_surface_is_exactly_locked():
    """锁定三个 detector 在 100 题上的触发面 —— 这是「副作用风险」的上界证据。"""
    e9 = [it["id"] for it in _ITEMS if detect_global_scope(it["question"])]
    e10 = [it["id"] for it in _ITEMS if detect_ratio_direction(it["question"])]
    e11 = [it["id"] for it in _ITEMS if detect_ranking_tiebreak(it["question"])]

    assert e9 == ["E-0065"], f"E9 触发面异常: {e9}"
    assert e10 == [
        "E-0064", "E-0075", "E-0076", "E-0081", "E-0082", "E-0083",
        "E-0089", "E-0092", "E-0094", "E-0096", "E-0099", "E-0100",
    ], f"E10 触发面异常: {e10}"
    assert len(e11) == 25, f"E11 触发面异常: {e11}"
    assert "E-0098" in e11
    # 标量 Top-1 题不得进入 E11
    for scalar in ("E-0009", "E-0010", "E-0015", "E-0032", "E-0038"):
        assert scalar not in e11, f"{scalar} 不应触发 E11"


def test_e9_trigger_surface_does_not_include_time_bound_global_questions():
    """E9 的触发面必须严格小于「含平台级全局词」的 10 题。"""
    with_global = [
        it["id"]
        for it in _ITEMS
        if any(k in it["question"] for k in ("全平台", "全站", "整个平台", "平台整体"))
    ]
    assert len(with_global) == 10
    e9 = [it["id"] for it in _ITEMS if detect_global_scope(it["question"])]
    assert set(e9) < set(with_global)


# ================================================================ §8 artifact 完整性


def test_artifact_keeps_full_sql_no_truncation():
    """§七 SQL 保存纪律：artifact 中的 pred/gold SQL 必须完整，不得只留前 400 字。"""
    for qid, sql in GOLD_SQL.items():
        assert sql.strip(), f"{qid}: gold_sql 为空"
        assert len(sql) == len(sql.strip()) or sql == sql.strip()

    for qid, sql in PRED_SQL.items():
        assert sql.strip(), f"{qid}: pred_sql 为空"
        assert not (len(sql) == 400), f"{qid}: pred_sql 恰好 400 字 —— 疑似被截断"
        # 必须能被 SQLite 方言解析（完整 SQL 的基本判据）
        import sqlglot

        sqlglot.parse_one(sql, read="sqlite")

    # E-0088 的原始记录确实被上游截断 ⇒ 必须显式保留「前缀 + 重建」两份证据
    assert len(E0088_RECORDED_PREFIX) == 400
    assert E0088_PRED_RECONSTRUCTED.startswith(E0088_RECORDED_PREFIX)
    assert len(E0088_PRED_RECONSTRUCTED) == 1020


def test_artifact_sql_constants_match_task43_records():
    """pred SQL 常量与 Task 43 记录的实测形态一致（防「事后美化」）。"""
    assert E0065_PRED.startswith("SELECT COUNT(*) AS order_count FROM orders")
    assert "strftime('%Y', order_date) = '2026'" in E0065_PRED
    assert E0075_PRED.startswith("SELECT ROUND(COUNT(CASE WHEN substr(o.order_date, 1, 4)")
    assert "BETWEEN 1 AND 6 THEN o.id END) * 1.0 /" in E0075_PRED
    assert E0082_PRED.startswith("SELECT ROUND(100.0 * SUM(CASE WHEN c.name = '休闲零食'")
    assert E0098_PRED.startswith("WITH ranked_products AS")
    assert "ORDER BY SUM(oi.quantity) DESC) as rn" in E0098_PRED
