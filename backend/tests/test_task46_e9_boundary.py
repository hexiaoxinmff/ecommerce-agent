"""Task 46：E9 触发边界的离线语义 fixture（只测 E9 边界，不引入新业务规则）。

## 要区分的两件事（本文件的唯一主题）

| 概念 | 含义 | E9 是否应触发 |
|---|---|---|
| **全局参照基准** | 参照对象是「全平台 / 全站 / 平台整体」这类**不受本题时间窗限制**的整体 | ✅ 触发 |
| **同一时间窗口内的全部对象** | 「该季度全部商品」「2026 年所有订单」——对象虽多，但**与本题共享同一时间窗** | ❌ 不触发 |

反例（真实冻结题）：`E-0083`「2025年第四季度中，家用电器类目销售金额占该季度**全部**商品销售金额的比例」
——含「全部」，但该「全部」被**同一句的时间窗**限定 ⇒ E9 必须保持 NO。
若把判据放宽到「全部 / 所有」，本题会被误触，规则会教模型丢掉合法的时间过滤。

## 结构

| 段 | 内容 |
|---|---|
| §1 | Positive fixtures（全局参照基准 + 时间过滤 ⇒ 必须触发） |
| §2 | Negative fixtures（同一时间窗内的全部对象 ⇒ 必须不触发） |
| §3 | Boundary fixtures（有平台级词但无时间过滤 ⇒ 必须不触发） |
| §4 | 真实冻结题的边界锁定（E-0065 YES；E-0083/E-0077/E-0064/E-0090/E-0058 NO） |
| §5 | 注入侧断言（block 非空 / 为空 + 例外条款存在） |
| §6 | 判据确定性（同一输入恒同输出；不依赖 DB / Gold） |
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.sqlgen.prompt import global_scope_block, semantic_contract_block  # noqa: E402
from app.sqlgen.semantic_contracts import detect_global_scope  # noqa: E402

DATASET = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
_ITEMS = json.loads(DATASET.read_text(encoding="utf-8"))["items"]
ITEMS = {it["id"]: it for it in _ITEMS}


# ---------------------------------------------------------------- §1 Positive
POSITIVE_FIXTURES = [
    # (fixture_id, question, 期望命中的全局词)
    ("P1", "2026年各地区销量与全平台平均销量相比如何？", "全平台"),
    ("P2", "2026年订单实付金额高于全平台非取消订单平均实付金额的订单有多少笔？", "全平台"),
    ("P3", "2025年销售额高于全站平均销售额的商品有哪些？", "全站"),
    ("P4", "2025年各订单状态中，金额高于整个平台平均金额的订单有多少笔？", "整个平台"),
    ("P5", "2026年各省份用户数高于平台整体平均用户数的省份有哪些？", "平台整体"),
]


@pytest.mark.parametrize("fid,question,term", POSITIVE_FIXTURES)
def test_positive_fixtures_trigger(fid, question, term):
    """全局参照基准 + 时间过滤 ⇒ 必须触发。"""
    c = detect_global_scope(question)
    assert c is not None, f"{fid} 应触发但未触发：{question}"
    assert term in c.global_terms, (fid, c.global_terms)
    assert c.time_terms, (fid, c.time_terms)


# ---------------------------------------------------------------- §2 Negative
NEGATIVE_FIXTURES = [
    # 全部 / 所有 —— 但都被**同一句的时间窗**限定
    ("N1", "2026年全部商品中销量最高的是哪些？"),
    ("N2", "该季度全部商品销售金额是多少？"),
    ("N3", "2025年所有订单的总金额是多少？"),
    ("N4", "2026年全部订单的平均实付金额是多少？"),
    ("N5", "2025年第四季度中，家用电器类目销售金额占该季度全部商品销售金额的比例是多少？（百分比，保留两位小数）"),
    ("N6", "2026年所有收货地区的订单数量分别是多少？"),
    ("N7", "2025年各订单状态的订单数及其占2025年总订单数的比例是多少？"),
]


@pytest.mark.parametrize("fid,question", NEGATIVE_FIXTURES)
def test_negative_fixtures_do_not_trigger(fid, question):
    """「同一时间窗口内的全部对象」不是全局参照基准 ⇒ 必须不触发。"""
    assert detect_global_scope(question) is None, f"{fid} 被误触发：{question}"


# ---------------------------------------------------------------- §3 Boundary
BOUNDARY_FIXTURES = [
    ("B1", "全平台商品平均售价是多少？"),
    ("B2", "所有商品的平均售价是多少？"),
    ("B3", "整个平台售价最高的商品属于哪个分类？"),
    ("B4", "哪些收货地区的客单价高于全平台非取消订单客单价？"),
]


@pytest.mark.parametrize("fid,question", BOUNDARY_FIXTURES)
def test_boundary_platform_term_without_time_filter_does_not_trigger(fid, question):
    """有平台级词但**没有**时间过滤 ⇒ 没有「可能被继承的时间窗」⇒ 不触发（注入是纯噪声）。"""
    assert detect_global_scope(question) is None, f"{fid} 被误触发：{question}"


# ---------------------------------------------------------------- §4 真实冻结题
def test_real_positive_E0065_triggers():
    c = detect_global_scope(ITEMS["E-0065"]["question"])
    assert c is not None
    assert "全平台" in c.global_terms
    assert c.time_terms == ("2026年",)


@pytest.mark.parametrize(
    "qid,why",
    [
        ("E-0083", "「该季度全部商品销售金额」——全部被同一句时间窗限定（必须锁定为 NO）"),
        ("E-0077", "「各地区平均销售额」——同一 2025 窗口内的对象"),
        ("E-0064", "「占2025年总订单数的比例」——分母与本题共享 2025 窗口"),
        ("E-0090", "「2025年各订单状态」——无全局基准，比较对象是固定阈值 5000 元"),
        ("E-0058", "含「全平台」但题面无时间过滤 ⇒ 无窗可继承"),
    ],
)
def test_real_negative_questions_do_not_trigger(qid, why):
    q = ITEMS[qid]["question"]
    assert detect_global_scope(q) is None, f"{qid} 被误触发（{why}）：{q}"


def test_E0083_gold_keeps_the_time_window_on_both_sides():
    """E-0083 的 gold 证明「该季度」这一时间窗必须保留在分子与分母两侧。"""
    gold = ITEMS["E-0083"]["gold_sql"]
    # 分母子查询内**保留**了季度过滤 ⇒ 与 E-0065 的情形正好相反
    inner = gold.split("(SELECT SUM(oi3.subtotal)")[1].split(")")[0]
    assert "o3.order_date >= '2025-10-01'" in inner
    assert "o3.order_date <= '2025-12-31'" in inner


def test_E0065_gold_does_not_inherit_the_time_window_on_the_baseline():
    """E-0065 的 gold 证明参照基准子查询**不得**继承外层的 2026 过滤。"""
    gold = ITEMS["E-0065"]["gold_sql"]
    inner = gold.split("(SELECT AVG(total_amount)")[1]
    assert "order_date" not in inner.split(")")[0]


# ---------------------------------------------------------------- §5 注入侧
def _with_e9(question: str) -> str:
    prev = os.environ.get("SQLGEN_EXTRA_RULES")
    os.environ["SQLGEN_EXTRA_RULES"] = "E9"
    try:
        return global_scope_block(question)
    finally:
        if prev is None:
            os.environ.pop("SQLGEN_EXTRA_RULES", None)
        else:
            os.environ["SQLGEN_EXTRA_RULES"] = prev


def test_block_injected_for_positive_and_empty_for_negative():
    assert _with_e9(POSITIVE_FIXTURES[0][1]) != ""
    assert _with_e9(NEGATIVE_FIXTURES[4][1]) == ""  # N5 == E-0083 的题面
    assert _with_e9(BOUNDARY_FIXTURES[3][1]) == ""


def test_block_states_the_same_window_exception():
    """文本必须显式写出「与同一时间窗绑定时必须保留过滤」这一例外，否则会诱导丢过滤。"""
    block = _with_e9(POSITIVE_FIXTURES[0][1])
    assert "例外" in block
    assert "必须" in block and "保留该时间窗" in block
    assert "该季度全部商品销售金额" in block  # 显式反例


def test_block_lists_the_detected_terms_for_auditability():
    block = _with_e9("2026年各地区销量与全平台平均销量相比如何？")
    assert "2026年" in block
    assert "全平台" in block


# ---------------------------------------------------------------- §6 确定性
def test_detector_is_deterministic_and_side_effect_free():
    """同一输入恒同输出；且不读取 Gold / DB（只依赖 question 文本）。"""
    q = POSITIVE_FIXTURES[1][1]
    outs = {detect_global_scope(q) for _ in range(5)}
    assert len(outs) == 1
    assert detect_global_scope("") is None
    assert detect_global_scope("   ") is None


def test_e9_off_yields_empty_semantic_block():
    prev = os.environ.get("SQLGEN_EXTRA_RULES")
    os.environ.pop("SQLGEN_EXTRA_RULES", None)
    try:
        assert semantic_contract_block(ITEMS["E-0065"]["question"]) == ""
    finally:
        if prev is not None:
            os.environ["SQLGEN_EXTRA_RULES"] = prev
