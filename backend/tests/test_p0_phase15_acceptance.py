"""Phase 15 P0 验收测试。

P0-1 数据时效契约（Data As-Of / Time Anchor）：
- 契约来自真实只读查询（MIN/MAX），不是硬编码日期；
- 契约文本锚定"业务数据截止日"，显式禁止 date('now') / strftime('now')；
- 注入路径：Profile.time_anchor → adapter.prompt_appendix() /
  default_prompt_appendix() → 生成与修复 Prompt 附录；
- 无附录时 Prompt 与冻结基线逐字节一致（冻结保护）。

P0-2 KPI 一致性：
- Dashboard「本月销售额」= Agent KPI 定义 = SUM(order_items.subtotal)
  （排除 cancelled）—— 双真相源已消除；
- 客单价 = 订单实付口径（SUM(total_amount)/COUNT(*)），与销售额显式分离。

P0-3 后端侧首页链路：
- /api/agent/analyze 响应携带 data_as_of（前端据此展示「数据截至」）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent import graph as graph_module
from app.agent.models import AgentResult
from app.api.routes.insights import _load_overview
from app.auth.dependencies import get_current_session
from app.dbprofile.adapter import DatabaseAdapter
from app.dbprofile.kpi_definitions import KPI_SALES_A, kpi_rules_a
from app.dbprofile.profiles import resolve_profile
from app.dbprofile.time_anchor import (
    TimeAnchor,
    cached_time_contract,
    clear_time_contract_cache,
    compute_time_contract,
    default_prompt_appendix,
    default_time_contract,
)
from app.main import app
from app.sqlgen.prompt import BUSINESS_RULES, build_prompt
from app.schemas.schema_link import SchemaLinkResult
from app.fewshot.models import FewShotMatch, FewShotResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RBQ_DATASET = PROJECT_ROOT / "data" / "eval" / "real_business_v1.json"


# ---------------------------------------------------------------------------
# P0-1：数据时效契约
# ---------------------------------------------------------------------------


def test_time_contract_comes_from_real_query():
    """契约值来自真实库查询（A 库数据 2024-01-01 ~ 2026-09-12）。"""
    clear_time_contract_cache()
    contract = compute_time_contract(
        resolve_profile("ecommerce_A").db_path,
        TimeAnchor(table="orders", column="order_date"),
    )
    assert contract.data_as_of == "2026-09-12"
    assert contract.data_min_date == "2024-01-01"
    assert contract.source_table == "orders"
    assert contract.source_column == "order_date"


def test_time_contract_block_anchors_relative_time():
    """契约文本必须锚定业务截止日并显式禁止系统时钟函数。"""
    clear_time_contract_cache()
    block = compute_time_contract(
        resolve_profile("ecommerce_A").db_path,
        TimeAnchor(table="orders", column="order_date"),
    ).to_prompt_block()
    assert "2026-09-12" in block
    assert "2024-01-01" in block
    assert "date('now')" in block and "禁止" in block
    assert "本月 = 2026-09" in block
    assert "上月 = 2026-08" in block
    assert "今年 = 2026" in block
    assert "部分月" in block  # 明示本月是部分月，防止模型自行换月


def test_b_profile_uses_its_own_anchor():
    """换库只改 Profile 锚点：B 库锚定 sales_orders.placed_on。"""
    profile_b = resolve_profile("ecommerce_B")
    assert profile_b.time_anchor is not None
    assert profile_b.time_anchor.table == "sales_orders"
    assert profile_b.time_anchor.column == "placed_on"
    contract = cached_time_contract(profile_b.db_path, profile_b.time_anchor)
    assert contract.data_as_of == "2026-09-20"  # B 库数据止于 2026-09-20（独立建库）
    assert contract.source_table == "sales_orders"


def test_build_prompt_without_appendix_is_freeze_safe():
    """冻结保护：不传附录时 Prompt 不含任何 Phase 15 新增块。"""
    link = SchemaLinkResult(question="q", tables=["orders"], columns=[], reasons=[], confidence=0.9)
    fs = FewShotResult(question="q", matches=[])
    prompt = build_prompt("本月销售额是多少？", link, fs)
    assert "数据时效契约" not in prompt
    assert "KPI 口径定义" not in prompt


def test_build_prompt_with_appendix_contains_contract():
    link = SchemaLinkResult(question="q", tables=["orders"], columns=[], reasons=[], confidence=0.9)
    fs = FewShotResult(question="q", matches=[])
    appendix = default_prompt_appendix()
    prompt = build_prompt("本月销售额是多少？", link, fs, appendix_rules=appendix)
    assert "数据时效契约" in prompt
    assert "KPI 口径定义" in prompt
    assert "2026-09-12" in prompt


def test_profile_a_frozen_rules_untouched_and_appendix_separate():
    """Phase 13 冻结契约不破坏：A 口径常量逐字节不变；新内容走附录字段。"""
    profile = resolve_profile("ecommerce_A")
    assert profile.business_rules.generation_rules == BUSINESS_RULES
    appendix = DatabaseAdapter(profile).prompt_appendix()
    assert "KPI 口径定义" in appendix
    assert "数据时效契约" in appendix


def test_default_components_carry_appendix(monkeypatch):
    """生产默认组件（API 运行路径）必须携带同一附录。"""
    monkeypatch.setattr(graph_module, "get_llm_provider", lambda: _NullProvider())
    components = graph_module.default_components()
    gen_appendix = components.sql_generator._appendix_rules
    repair_appendix = components.sql_repairer._appendix_rules
    assert "KPI 口径定义" in gen_appendix
    assert "数据时效契约" in gen_appendix
    assert "数据时效契约" in repair_appendix  # 修复 Prompt 同锚（生成/修复一致）


class _NullProvider:
    """占位 Provider（default_components 只装配，不发请求）。"""


# ---------------------------------------------------------------------------
# P0-2：KPI 一致性（Dashboard == Agent KPI 定义 == 业务口径真值）
# ---------------------------------------------------------------------------


def _rbq_gold_result(eval_id: str):
    """执行 RBQ 数据集中指定题的 gold SQL（真实只读库）。"""
    data = json.loads(RBQ_DATASET.read_text(encoding="utf-8"))
    item = next(i for i in data["items"] if i["id"] == eval_id)
    import sqlite3

    conn = sqlite3.connect(
        f"file:{(PROJECT_ROOT / 'db' / 'ecommerce.db').as_posix()}?mode=ro", uri=True
    )
    try:
        return conn.execute(item["gold_sql"]).fetchone()
    finally:
        conn.close()


def test_dashboard_month_sales_equals_agent_kpi_definition():
    """Dashboard 本月销售额 == Agent「本月销售额」gold（RBQ-011）== 826,080.07。"""
    overview = _load_overview()
    gold_value = float(_rbq_gold_result("RBQ-011")[0])
    assert overview.kpis.month_sales.value == pytest.approx(gold_value, abs=0.01)
    assert overview.kpis.month_sales.value == pytest.approx(826080.07, abs=0.01)


def test_dashboard_month_sales_is_not_old_total_amount_value():
    """反向保护：不得再返回旧实付口径的 766,292.18（双真相源已消除）。"""
    overview = _load_overview()
    assert overview.kpis.month_sales.value != pytest.approx(766292.18, abs=0.01)


def test_dashboard_trend_uses_detail_scope():
    """趋势图与本月销售额同口径：最后一点（最新月）== 本月销售额。"""
    overview = _load_overview()
    trend = overview.sales_trend
    assert trend, "趋势为空"
    assert trend[-1].month == overview.kpis.month_sales.month
    assert trend[-1].sales == pytest.approx(overview.kpis.month_sales.value, abs=0.01)


def test_dashboard_aov_is_order_pay_metric():
    """客单价 = 订单实付口径；与销售额口径分离（两口径真实库必然不同）。"""
    overview = _load_overview()
    import sqlite3

    conn = sqlite3.connect(
        f"file:{(PROJECT_ROOT / 'db' / 'ecommerce.db').as_posix()}?mode=ro", uri=True
    )
    try:
        month = overview.kpis.month_sales.month
        pay, orders = conn.execute(
            "SELECT SUM(total_amount), COUNT(*) FROM orders "
            "WHERE strftime('%Y-%m', order_date) = ? AND status != 'cancelled'",
            (month,),
        ).fetchone()
    finally:
        conn.close()
    assert overview.kpis.avg_order_value.value == pytest.approx(
        round(float(pay) / int(orders), 2), abs=0.01
    )


def test_kpi_definition_forbids_total_amount_for_sales():
    """KPI 定义的 Prompt 文本必须显式禁止用 total_amount 回答销售额。"""
    text = kpi_rules_a()
    assert "order_items.subtotal" in text
    assert "禁止用 orders.total_amount" in text
    assert KPI_SALES_A.source == "order_items.subtotal"


def test_kpi_definition_carries_data_as_of_reference():
    """KPI 定义文本不硬编码日期 —— 时间口径由 Data As-Of 契约统一提供。"""
    text = kpi_rules_a()
    assert "2026-09-12" not in text  # 日期只能来自 time_anchor 动态查询


# ---------------------------------------------------------------------------
# P0-3（后端侧）：/api/agent/analyze 响应携带 data_as_of
# ---------------------------------------------------------------------------


@pytest.fixture()
def _agent_route_client(monkeypatch):
    fake_session = {"id": 1, "user_id": 1, "token_hash": "h", "created_at": "", "expires_at": ""}
    fake_user = {"id": 1, "username": "u", "email": "e", "password_hash": "x", "created_at": "", "is_active": 1}
    app.dependency_overrides[get_current_session] = lambda: (fake_session, fake_user)

    def _fake_run_agent(question: str) -> AgentResult:
        return AgentResult(question=question, success=True, execute_count=1, repair_count=0)

    monkeypatch.setattr(graph_module, "run_agent", _fake_run_agent)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_current_session, None)


def test_agent_route_attaches_data_as_of(_agent_route_client):
    resp = _agent_route_client.post(
        "/api/agent/analyze", json={"question": "本月销售额是多少？"}
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data_as_of"] == "2026-09-12"


def test_default_time_contract_degrades_when_db_missing(tmp_path, monkeypatch):
    """库不可读时契约降级为 None（不阻断服务），附录降级为仅 KPI 口径。"""
    from app.dbprofile import time_anchor as ta

    profile = resolve_profile("ecommerce_A").with_overrides(db_path=tmp_path / "no.db")
    monkeypatch.setattr(
        "app.dbprofile.profiles.resolve_profile", lambda pid=None: profile
    )
    clear_time_contract_cache()
    try:
        assert ta.default_time_contract() is None
        appendix = ta.default_prompt_appendix()
        assert "KPI 口径定义" in appendix
        assert "数据时效契约" not in appendix
    finally:
        clear_time_contract_cache()
