"""SQL Generator Prompt 专项规则（Task 14.2 E4~E7）单元测试。

验证：
- 默认（无 SQLGEN_EXTRA_RULES）不注入任何专项规则（保持 V1.1 行为）；
- E4/E5/E6/E7 各自启用时注入对应规则段；
- build_prompt 包含/不包含正确内容。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.schemas.schema_link import SchemaLinkResult  # noqa: E402
from app.sqlgen.prompt import (  # noqa: E402
    BUSINESS_RULES,
    build_prompt,
    enabled_extra_rules,
)

from app.fewshot.models import FewShotResult  # noqa: E402

LINK = SchemaLinkResult(
    question="q", tables=["orders"], columns=["orders.order_date"], reasons=[], confidence=0.9
)
FS = FewShotResult(question="q", matches=[])


def _prompt(monkeypatch, extra: str | None = None) -> str:
    if extra is None:
        monkeypatch.delenv("SQLGEN_EXTRA_RULES", raising=False)
    else:
        monkeypatch.setenv("SQLGEN_EXTRA_RULES", extra)
    return build_prompt("q", LINK, FS)


def test_default_no_extra_rules(monkeypatch):
    p = _prompt(monkeypatch, None)
    assert "输出列契约" not in p
    assert "金额/销售口径-字段选择决策" not in p
    assert "分层聚合思维" not in p
    assert "CASE WHEN 分段边界" not in p
    assert "业务语义-金额字段" in p  # V1.1 基础规则仍在


@pytest.mark.parametrize("flag,key", [
    ("E4", "输出列契约"),
    ("E5", "金额/销售口径-字段选择决策"),
    ("E6", "分层聚合思维"),
    ("E7", "CASE WHEN 分段边界"),
])
def test_single_extra_enabled(monkeypatch, flag, key):
    p = _prompt(monkeypatch, flag)
    assert key in p


def test_multiple_extras(monkeypatch):
    p = _prompt(monkeypatch, "E4,E6")
    assert "输出列契约" in p
    assert "分层聚合思维" in p
    assert "金额/销售口径-字段选择决策" not in p


def test_unknown_flag_ignored(monkeypatch):
    # Task 44：原用例用 "E9" 当「未知 flag」，但 E9 在 Task 44 中已成为真实 flag
    # （条件性语义契约）。继续用 E9 会让本用例名不副实（它只是「已知 flag 不注入
    # 无条件规则段」而非「未知 flag 被忽略」），因此改用真正未定义的 E999。
    p = _prompt(monkeypatch, "E999")
    assert "输出列契约" not in p


def test_enabled_extra_rules_empty_by_default(monkeypatch):
    monkeypatch.delenv("SQLGEN_EXTRA_RULES", raising=False)
    assert enabled_extra_rules() == ""