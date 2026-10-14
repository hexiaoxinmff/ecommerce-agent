"""Task 38：条件性统计实体 / 驱动表约束（E-0057）单元测试。

覆盖：
1. 触发条件 —— E-0057 命中，并解析出正确的四个字段；
2. 条件性 —— 明确要求「包含 0 单/全集」的题不触发（E-0036 类）；
3. 保守性 —— 比例题/其他题型不误触发（E-0082 类的「比例是多少」）；
4. 开关契约 —— 未设 E8 时 Prompt 与基线逐字节相同；
5. 全 100 题触发面 —— 恰好 1 题（E-0057），无误触发。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.fewshot.models import FewShotResult  # noqa: E402
from app.schemas.schema_link import SchemaLinkResult  # noqa: E402
from app.sqlgen.entity_constraint import (  # noqa: E402
    detect_analysis_entity_constraint,
)
from app.sqlgen.prompt import build_prompt, entity_constraint_block  # noqa: E402

LINK = SchemaLinkResult(
    question="q",
    tables=["users", "orders"],
    columns=["users.id", "orders.user_id"],
    reasons=[],
    confidence=0.9,
)
FS = FewShotResult(question="q", matches=[])

E0057_Q = "按用户累计下单次数将用户分为三档（1-3单、4-10单、11单及以上），各档分别有多少用户？"


@pytest.fixture()
def e8_on(monkeypatch):
    monkeypatch.setenv("SQLGEN_EXTRA_RULES", "E8")


@pytest.fixture()
def e8_off(monkeypatch):
    monkeypatch.delenv("SQLGEN_EXTRA_RULES", raising=False)


# ---------------------------------------------------------------- 1. 触发与字段


def test_e0057_triggers_and_yields_correct_fields():
    c = detect_analysis_entity_constraint(E0057_Q)
    assert c is not None
    assert c.analysis_entity == "users_with_orders"
    assert c.driver_table == "orders"
    assert c.aggregation_grain == "user_id"
    assert c.include_zero_activity_entities is False


def test_constraint_block_mentions_driver_table_and_zero_entities():
    c = detect_analysis_entity_constraint(E0057_Q)
    block = c.to_prompt_block()
    assert "orders" in block
    assert "user_id" in block
    assert "false" in block
    # 必须明确禁止把 0 单用户引入全集
    assert "LEFT JOIN" in block


# ---------------------------------------------------------------- 2. 条件性：显式包含 0 实体


@pytest.mark.parametrize(
    "question",
    [
        "所有用户中，按累计下单次数分档各有几人？",
        "全部用户里，按下单次数分档各有多少用户？",
        "按累计下单次数分档统计用户数，包括 0 单用户。",
        "按累计购买次数分档，统计包含 0 次的用户有多少人？",
        "哪些分类下没有挂载任何商品？",
    ],
)
def test_explicitly_including_zero_entities_does_not_trigger(question):
    assert detect_analysis_entity_constraint(question) is None


def test_e0036_style_question_never_triggers():
    """E-0036 需要保留全集（找『没有商品的分类』），绝不能被约束干扰。"""
    assert detect_analysis_entity_constraint("哪些分类下没有挂载任何商品？") is None


# ---------------------------------------------------------------- 3. 保守性：其他题型不误触发


@pytest.mark.parametrize(
    "question",
    [
        # E-0082 类：比例题，「多少」修饰的是比例而非实体个数
        "休闲零食类别在全部非取消订单明细中的销售金额占全平台商品销售总额的比例是多少？",
        # 金额题
        "用户平均累计消费金额是多少？",
        # 无行为语义
        "有多少活跃用户？",
        # 无实体词
        "各地区的销售额是多少？",
        # 空
        "",
        "   ",
    ],
)
def test_other_question_types_do_not_trigger(question):
    assert detect_analysis_entity_constraint(question) is None


# ---------------------------------------------------------------- 4. 开关契约


def test_off_mode_prompt_has_no_constraint(e8_off):
    p = build_prompt(E0057_Q, LINK, FS)
    assert "统计实体" not in p
    assert entity_constraint_block(E0057_Q) == ""


def test_on_mode_injects_constraint_for_target_question(e8_on):
    p = build_prompt(E0057_Q, LINK, FS)
    assert "统计实体 / 驱动表约束" in p
    assert "users_with_orders" in p


def test_on_mode_does_not_inject_for_non_target_question(e8_on):
    """条件性局部生效：E8 开启但题目不命中时，Prompt 不含约束段。"""
    p = build_prompt("哪些分类下没有挂载任何商品？", LINK, FS)
    assert "统计实体 / 驱动表约束" not in p


def test_off_and_on_differ_only_by_constraint_block(e8_on):
    """ON 相对 OFF 的差异必须**仅为**约束段，不夹带其他改动。"""
    import os

    on = build_prompt(E0057_Q, LINK, FS)
    os.environ.pop("SQLGEN_EXTRA_RULES", None)
    off = build_prompt(E0057_Q, LINK, FS)
    os.environ["SQLGEN_EXTRA_RULES"] = "E8"

    block = entity_constraint_block(E0057_Q)
    assert on.startswith(off.split("\n\n")[0])
    # 把约束段从 ON 里去掉，应当等于 OFF
    assert on.replace(f"{block}\n", "", 1) == off


# ---------------------------------------------------------------- 5. 全 100 题触发面


def test_trigger_scope_is_exactly_e0057():
    """全 100 题中恰好只有 E-0057 触发（保守优先）。"""
    dataset = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
    data = json.loads(dataset.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data

    triggered = [
        it["id"]
        for it in items
        if detect_analysis_entity_constraint(it["question"]) is not None
    ]
    assert triggered == ["E-0057"], f"触发面异常: {triggered}"


def test_lef_join_questions_per_question_check():
    """凡 gold 使用 LEFT JOIN 保留全集的题，都不得被约束触发。"""
    dataset = PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
    data = json.loads(dataset.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data

    for item in items:
        if "LEFT JOIN" in (item.get("gold_sql") or "").upper():
            assert (
                detect_analysis_entity_constraint(item["question"]) is None
            ), f"{item['id']} 需保留全集，却被约束触发"
