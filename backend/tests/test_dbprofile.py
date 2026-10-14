"""Phase 13：Database Profile / Adapter / 跨库 A↔B 切换测试。

覆盖：
- Profile 解析（默认 / 环境变量 / 未知 id）；
- 双库 Adapter（只读连接、Schema 目录、database_info）；
- B 库结构与业务语义差异（关系不同、口径不同）；
- Few-shot Profile 绑定（跨库校验拒绝 / 跳过复核的实验模式）；
- 安全执行器在双库上的行为；
- 同一进程内 A → B → A 切换（目录缓存隔离）；
- Agent Core 零改动端到端：fake Provider 驱动 run_agent 在两库上运行。
"""

import sys
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.core import config
from app.db.sqlite import DatabaseNotFoundError, get_connection_for
from app.dbprofile import resolve_profile
from app.dbprofile.adapter import DatabaseAdapter, components_for_profile
from app.dbprofile.models import SchemaProfile
from app.dbprofile.profiles import DEFAULT_PROFILE_ID, PROFILE_IDS
from app.fewshot.dataset import (
    FewShotDatasetInvalidError,
    load_dataset,
)
from app.schema.metadata import SchemaCatalog
from app.sqlgen.prompt import BUSINESS_RULES, SYSTEM_PROMPT, build_prompt, system_prompt_for

PROJECT_ROOT = Path(config.PROJECT_ROOT)
B_DB_PATH = PROJECT_ROOT / "db" / "ecommerce_v2.db"


def _ensure_b_db() -> None:
    if not B_DB_PATH.is_file():
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import init_db_v2  # noqa: PLC0415

        init_db_v2.main()


@pytest.fixture(scope="module", autouse=True)
def _b_db() -> None:
    _ensure_b_db()


@pytest.fixture()
def adapter_a() -> DatabaseAdapter:
    return DatabaseAdapter(resolve_profile("ecommerce_A"))


@pytest.fixture()
def adapter_b() -> DatabaseAdapter:
    return DatabaseAdapter(resolve_profile("ecommerce_B"))


# ---------------- Profile 解析 ----------------


def test_resolve_profile_default_is_ecommerce_a(monkeypatch):
    monkeypatch.delenv("DB_PROFILE", raising=False)
    profile = resolve_profile()
    assert profile.profile_id == DEFAULT_PROFILE_ID == "ecommerce_A"
    assert profile.db_path == config.DB_PATH
    assert profile.db_type == "sqlite"


def test_resolve_profile_env_override(monkeypatch):
    monkeypatch.setenv("DB_PROFILE", "ecommerce_B")
    assert resolve_profile().profile_id == "ecommerce_B"
    monkeypatch.setenv("DB_PROFILE", "  ")
    assert resolve_profile().profile_id == "ecommerce_A"


def test_resolve_profile_unknown_id_raises():
    with pytest.raises(KeyError, match="未知 Database Profile"):
        resolve_profile("company_z")
    assert set(PROFILE_IDS) == {"ecommerce_A", "ecommerce_B"}


def test_profile_a_texts_equal_frozen_constants(adapter_a):
    """Profile A 的口径必须与冻结基线常量逐字节一致（v1.0 保护）。"""
    rules = adapter_a.profile.business_rules
    assert rules.generation_rules == BUSINESS_RULES
    assert system_prompt_for(adapter_a.profile.domain_name) == SYSTEM_PROMPT


# ---------------- Adapter：连接 / 目录 / 信息 ----------------


def test_adapter_connection_is_readonly(adapter_b):
    conn = adapter_b.get_connection()
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM members")
    finally:
        conn.close()


def test_adapter_missing_db_raises_clear_error(tmp_path):
    profile = resolve_profile("ecommerce_B").with_overrides(
        db_path=tmp_path / "no_such.db"
    )
    with pytest.raises(DatabaseNotFoundError):
        DatabaseAdapter(profile).get_connection()


def test_catalogs_differ_between_profiles(adapter_a, adapter_b):
    cat_a = adapter_a.get_cached_catalog()
    cat_b = adapter_b.get_cached_catalog()
    assert cat_a.table_names == ("users", "categories", "products", "orders", "order_items")
    assert cat_b.table_names == ("members", "departments", "items", "sales_orders", "order_lines")
    # 缓存隔离：同一 adapter 内为同一对象，跨 adapter 不串
    assert adapter_a.get_cached_catalog() is cat_a
    assert adapter_b.get_cached_catalog() is cat_b


def test_b_schema_relationship_differences(adapter_b):
    """第二库的关系差异：sales_orders 无城市冗余列；departments 单层。"""
    cat = adapter_b.get_cached_catalog()
    assert not cat.has_column("sales_orders", "city")
    assert not cat.has_column("departments", "parent_id")
    assert cat.has_column("members", "city")
    assert cat.has_column("members", "tier")
    cat_a = DatabaseAdapter(resolve_profile("ecommerce_A")).get_cached_catalog()
    assert cat_a.has_column("orders", "region")
    assert cat_a.has_column("categories", "parent_id")


def test_database_info_from_real_queries(adapter_a, adapter_b):
    info_a = adapter_a.database_info()
    info_b = adapter_b.database_info()
    assert info_a["database"] == "ecommerce.db"
    assert info_a["users"] == 2000 and info_a["orders"] == 10000
    assert info_b["database"] == "ecommerce_v2.db"
    assert info_b["members"] == 1200 and info_b["sales_orders"] == 6000


def test_generic_whitelist_introspects_all_tables():
    """SchemaProfile(table_names=None) = 全表内省（迁移实验 B 组的最低适配）。"""
    profile = resolve_profile("ecommerce_B").with_overrides(
        schema=SchemaProfile(table_names=None, table_descriptions={}, column_descriptions={})
    )
    tables = DatabaseAdapter(profile).build_catalog().table_names
    assert set(tables) == {"members", "departments", "items", "sales_orders", "order_lines"}


def test_a_whitelist_on_b_db_yields_empty_catalog():
    """B0 场景：仅换连接、A 白名单原样生效 → 结构不可用（无可见表）。"""
    profile = resolve_profile("ecommerce_A").with_overrides(
        db_path=B_DB_PATH
    )
    assert DatabaseAdapter(profile).build_catalog().table_names == ()


# ---------------- 业务语义层 ----------------


def test_business_rules_differ_between_profiles(adapter_a, adapter_b):
    rules_a = adapter_a.profile.business_rules.generation_rules
    rules_b = adapter_b.profile.business_rules.generation_rules
    assert "order_items.subtotal" in rules_a and "cancelled" in rules_a
    assert "order_lines.line_total" in rules_b and "voided" in rules_b
    # B 规则只会以「不是 cancelled」的形式提及该词，绝不允许作为可用取值出现
    assert "'cancelled'" not in rules_b
    assert "status != 'cancelled'" not in rules_b
    assert rules_a != rules_b
    # 精简口径与链接示例同样不同
    assert adapter_a.profile.business_rules.schema_link_rules != \
        adapter_b.profile.business_rules.schema_link_rules
    assert adapter_a.profile.business_rules.schema_link_example != \
        adapter_b.profile.business_rules.schema_link_example


def test_prompt_injection_changes_rules_text():
    """build_prompt 的 business_rules 注入：缺省 = 冻结基线。"""
    from app.fewshot.models import FewShotMatch, FewShotResult
    from app.schemas.schema_link import SchemaLinkResult

    link = SchemaLinkResult(question="q", tables=["users"], columns=[],
                            reasons=[], confidence=0.9)
    fs = FewShotResult(question="q", matches=[])
    base = build_prompt("q", link, fs)
    injected = build_prompt(
        "q", link, fs,
        business_rules=resolve_profile("ecommerce_B").business_rules.generation_rules,
    )
    assert BUSINESS_RULES in base
    assert "voided" in injected
    assert "status != 'cancelled'" not in injected
    assert "【用户问题】q" in base and "【用户问题】q" in injected


def test_b_payment_due_consistency(adapter_b):
    """B 库物化口径：payment_due = 明细合计 − 抵扣 + 配送费；作废订单全 0。"""
    with closing(adapter_b.get_connection()) as conn:
        bad = conn.execute(
            """
            SELECT COUNT(*) FROM sales_orders so
            WHERE so.order_state != 'voided'
              AND ABS(so.payment_due - ROUND(
                  (SELECT COALESCE(SUM(ol.line_total), 0) FROM order_lines ol
                    WHERE ol.sales_order_id = so.id)
                  - so.coupon_deduction + so.delivery_charge, 2)) > 0.01
            """
        ).fetchone()[0]
        assert bad == 0
        voided_bad = conn.execute(
            """
            SELECT COUNT(*) FROM sales_orders
            WHERE order_state = 'voided'
              AND (coupon_deduction != 0 OR delivery_charge != 0 OR payment_due != 0)
            """
        ).fetchone()[0]
        assert voided_bad == 0


# ---------------- Few-shot Profile ----------------


def test_fewshot_profiles_load_per_database(adapter_a, adapter_b):
    ex_a = adapter_a.load_fewshot()
    ex_b = adapter_b.load_fewshot()
    assert len(ex_a) == 23
    assert len(ex_b) == 14
    # A 示例只引用 A 表；B 示例只引用 B 表
    a_tables = {t for ex in ex_a for t in ex.tables}
    b_tables = {t for ex in ex_b for t in ex.tables}
    assert a_tables <= set(adapter_a.get_cached_catalog().table_names)
    assert b_tables <= set(adapter_b.get_cached_catalog().table_names)


def test_fewshot_cross_database_validation_rejects(adapter_a, adapter_b):
    """A 的数据集按 B 库目录复核必须被拒（Few-shot 与 Schema 强绑定）。"""
    with pytest.raises(FewShotDatasetInvalidError):
        load_dataset(adapter_a.profile.fewshot.dataset_path,
                     catalog=adapter_b.get_cached_catalog())
    with pytest.raises(FewShotDatasetInvalidError):
        load_dataset(adapter_b.profile.fewshot.dataset_path,
                     catalog=adapter_a.get_cached_catalog())


def test_fewshot_skip_validation_for_bare_switch(adapter_a, adapter_b):
    """迁移实验 B 组模式：跳过跨库复核后 A 示例可注入（无适配裸切换）。"""
    raw = load_dataset(adapter_a.profile.fewshot.dataset_path, catalog=None)
    assert len(raw) == 23


# ---------------- 执行器与切换 ----------------


def test_executor_works_on_both_databases(adapter_a, adapter_b):
    for adapter in (adapter_a, adapter_b):
        executor = adapter.sql_executor()
        result = executor("SELECT 1 AS one")
        assert result.row_count == 1
        with pytest.raises(Exception):
            executor("DELETE FROM users")  # 安全层拒绝写操作（两库同构）


def test_switch_a_b_a_within_process(adapter_a, adapter_b):
    """同一进程内 A → B → A 切换：查询各自库、目录缓存互不污染。"""
    count_sql = {"A": "SELECT COUNT(*) FROM users",
                 "B": "SELECT COUNT(*) FROM members"}
    seq = [(adapter_a, "A", 2000), (adapter_b, "B", 1200), (adapter_a, "A", 2000)]
    for adapter, side, expected in seq:
        with closing(adapter.get_connection()) as conn:
            (got,) = conn.execute(count_sql[side]).fetchone()
        assert got == expected
    assert adapter_a.get_cached_catalog().table_names[0] == "users"
    assert adapter_b.get_cached_catalog().table_names[0] == "members"


# ---------------- Agent Core 零改动端到端（fake Provider） ----------------


class _ScriptedProvider:
    """按 System Prompt 内容分流 Linking / Generation 响应的假 Provider。"""

    name = "scripted"
    model = "scripted-test"

    def __init__(self, table_by_profile: dict[str, str]) -> None:
        # profile_id -> 该库的用户表名
        self._table = table_by_profile

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        system = messages[0]["content"]
        user = messages[1]["content"]
        if "SQL Generator" in system:
            table = "users" if "order_items.subtotal" in user else "members"
            return (
                '{"sql": "SELECT COUNT(*) AS user_count FROM ' + table + '", '
                '"explanation": "计数", "tables": ["' + table + '"], '
                '"columns": ["' + table + '.id"]}'
            )
        if "Schema Linking" in system:
            table = "users" if "order_items.subtotal" in user else "members"
            return (
                '{"tables": ["' + table + '"], "columns": ["' + table + '.id"], '
                '"reasons": ["计数需要"], "confidence": 0.9}'
            )
        raise AssertionError("未识别的组件 System Prompt")


def test_agent_graph_runs_on_both_profiles_unchanged(adapter_a, adapter_b):
    """run_agent(components=...) 直接在两库上运行 —— Agent Core 零改动。"""
    from app.agent.graph import run_agent

    components_a = components_for_profile(
        resolve_profile("ecommerce_A"),
        provider=_ScriptedProvider({"ecommerce_A": "users"}),
    )
    result_a = run_agent("数据库里目前一共有多少个用户？", components=components_a)
    assert result_a.success
    assert result_a.execution_result.rows[0][0] == 2000

    components_b = components_for_profile(
        resolve_profile("ecommerce_B"),
        provider=_ScriptedProvider({"ecommerce_B": "members"}),
    )
    result_b = run_agent("数据库里目前一共有多少个用户？", components=components_b)
    assert result_b.success
    assert result_b.execution_result.rows[0][0] == 1200


def test_components_for_profile_wiring(adapter_a, adapter_b):
    """Profile 组件装配结构与 default_components 同构（依赖注入齐全）。"""
    provider = _ScriptedProvider({})
    comps = components_for_profile(resolve_profile("ecommerce_B"), provider=provider)
    assert comps.schema_linker is not None
    assert comps.fewshot_retriever is not None
    assert comps.sql_generator is not None
    assert comps.sql_repairer is not None
    # 执行器绑定到 B 库
    comps.sql_executor("SELECT COUNT(*) FROM members")
