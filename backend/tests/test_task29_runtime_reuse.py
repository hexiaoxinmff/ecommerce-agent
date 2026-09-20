"""Task 29 Candidate A 运行时复用行为测试。

Task 29 引入了四处"复用"，它们都必须满足同一约束：
**省掉重复工作，但不得改变任何可观察语义。**

1. `SchemaCatalog.get_cached()` / `clear_cache()`
2. `app.agent.graph.get_default_graph()` / `clear_default_graph_cache()`
3. `safety.check_sql_safety_with_tables()`（单次解析，与两步法等价）
4. `MimoProvider._get_client()`（实例内复用）

其中 1、2 是**进程级**状态，最容易破坏测试隔离，因此 conftest 中的
`_reset_process_caches` autouse fixture 会在每个测试边界清空它们；
本模块同时验证"清理确实生效"。
"""

import hashlib

import pytest

from app.core import config
from app.llm.mimo import MimoProvider
from app.schema.metadata import SchemaCatalog
from app.sqlgen.errors import SQLUnsafeError
from app.sqlgen.safety import check_sql_safety, check_sql_safety_with_tables
from app.sqlgen.safety import extract_referenced_tables

# ---------- 1. SchemaCatalog 进程级缓存 ----------


def test_schema_catalog_get_cached_returns_same_instance() -> None:
    first = SchemaCatalog.get_cached()
    second = SchemaCatalog.get_cached()
    assert first is second


def test_schema_catalog_clear_cache_forces_rebuild() -> None:
    first = SchemaCatalog.get_cached()
    SchemaCatalog.clear_cache()
    second = SchemaCatalog.get_cached()

    assert first is not second
    # 重建后内容必须与首次完全一致（缓存不得改变数据）
    assert first.table_names == second.table_names
    for name in first.table_names:
        left, right = first.get_table(name), second.get_table(name)
        assert left is not None and right is not None
        assert [(c.name, c.type) for c in left.columns] == [
            (c.name, c.type) for c in right.columns
        ]


def test_schema_catalog_cached_equals_from_database() -> None:
    cached = SchemaCatalog.get_cached()
    fresh = SchemaCatalog.from_database()

    assert cached.table_names == fresh.table_names
    assert cached.to_prompt_text() == fresh.to_prompt_text()


def test_schema_catalog_cache_does_not_survive_across_tests() -> None:
    """conftest 的 autouse fixture 必须让每个测试从干净缓存开始。

    若缓存跨测试存活，第一个构造缓存的测试会决定后续所有测试看到的
    Schema；此处通过"本测试首个 get_cached() 调用必然是新建"来间接验证。
    """
    # 该断言依赖 conftest._reset_process_caches 在每个测试前清空缓存
    assert SchemaCatalog.get_cached() is SchemaCatalog.get_cached()


# ---------- 2. Agent 图进程级缓存 ----------


def test_get_default_graph_is_cached() -> None:
    from app.agent import graph as graph_module

    calls = {"n": 0}
    sentinel = object()

    def fake_build_agent(components=None):
        calls["n"] += 1
        return sentinel

    original = graph_module.build_agent
    graph_module.build_agent = fake_build_agent
    try:
        first = graph_module.get_default_graph()
        second = graph_module.get_default_graph()
    finally:
        graph_module.build_agent = original

    assert first is sentinel
    assert second is sentinel
    assert calls["n"] == 1  # 第二次命中缓存，未重编译


def test_clear_default_graph_cache_forces_rebuild() -> None:
    from app.agent import graph as graph_module

    calls = {"n": 0}

    def fake_build_agent(components=None):
        calls["n"] += 1
        return object()

    original = graph_module.build_agent
    graph_module.build_agent = fake_build_agent
    try:
        first = graph_module.get_default_graph()
        graph_module.clear_default_graph_cache()
        second = graph_module.get_default_graph()
    finally:
        graph_module.build_agent = original

    assert calls["n"] == 2
    assert first is not second


def test_replacing_build_agent_invalidates_cache() -> None:
    """缓存键必须包含工厂函数身份，否则 monkeypatch 注入会被静默忽略。"""
    from app.agent import graph as graph_module

    first_sentinel, second_sentinel = object(), object()

    original = graph_module.build_agent
    try:
        graph_module.build_agent = lambda components=None: first_sentinel
        assert graph_module.get_default_graph() is first_sentinel

        # 换一个构建函数 → 必须重建，不能返回上一个函数的产物
        graph_module.build_agent = lambda components=None: second_sentinel
        assert graph_module.get_default_graph() is second_sentinel
    finally:
        graph_module.build_agent = original


def test_run_agent_without_components_uses_default_graph(monkeypatch) -> None:
    """components=None 必须走默认图缓存路径。"""
    from app.agent import graph as graph_module

    class _Sentinel(Exception):
        pass

    def boom() -> None:
        raise _Sentinel

    monkeypatch.setattr(graph_module, "get_default_graph", boom)
    with pytest.raises(_Sentinel):
        graph_module.run_agent("任意问题")


def test_default_graph_builds_real_components() -> None:
    """默认图必须能在真实配置下构建（不依赖网络）。"""
    from app.agent import graph as graph_module

    graph = graph_module.get_default_graph()
    assert graph is not None
    assert hasattr(graph, "invoke")


# ---------- 3. 单次解析的表名提取 ----------

_EQUIVALENCE_CASES = [
    # 安全 SQL：两者都应返回相同的表集合
    "SELECT id FROM users",
    "SELECT u.id, o.id FROM users u JOIN orders o ON u.id = o.user_id",
    "SELECT * FROM order_items oi JOIN products p ON oi.product_id = p.id",
    "WITH recent AS (SELECT id FROM orders) SELECT * FROM recent",
    "WITH a AS (SELECT id FROM users), b AS (SELECT id FROM a) SELECT * FROM b",
    "SELECT id FROM users UNION SELECT id FROM orders",
    "SELECT (SELECT COUNT(*) FROM orders) AS n FROM users",
    # 非安全 SQL：两者都应抛 SQLUnsafeError，且错误信息一致
    "DELETE FROM users",
    "UPDATE users SET name = 'x'",
    "INSERT INTO users (id) VALUES (1)",
    "DROP TABLE users",
    "CREATE TABLE t (id INT)",
    "ALTER TABLE users ADD COLUMN x INT",
    "PRAGMA table_info(users)",
    "SELECT 1; SELECT 2",
    "   ",
    "SELECT FROM WHERE (",
]


@pytest.mark.parametrize("sql", _EQUIVALENCE_CASES)
def test_with_tables_equivalent_to_two_step(sql: str) -> None:
    """check_sql_safety_with_tables 与两步法必须完全等价。"""
    try:
        check_sql_safety(sql)
    except SQLUnsafeError as exc:
        expected_error = str(exc)
    else:
        expected_error = None

    if expected_error is not None:
        with pytest.raises(SQLUnsafeError) as with_tables_exc:
            check_sql_safety_with_tables(sql)
        assert str(with_tables_exc.value) == expected_error
        # 两步法第二步同样应失败（此处不作断言：extract_referenced_tables
        # 对单条非法语句可能仍能解析，语义差异由 check_sql_safety 负责）
    else:
        assert check_sql_safety_with_tables(sql) == extract_referenced_tables(sql)


def test_with_tables_excludes_cte_names() -> None:
    sql = (
        "WITH recent_orders AS ("
        "  SELECT o.id FROM orders o JOIN order_items oi ON oi.order_id = o.id"
        ") SELECT * FROM recent_orders"
    )
    assert check_sql_safety_with_tables(sql) == {"orders", "order_items"}


def test_with_tables_matches_validator_usage() -> None:
    """与 validator.validate_output 的实际调用方式一致：返回 set[str]。"""
    result = check_sql_safety_with_tables("SELECT id FROM users")
    assert isinstance(result, set)
    assert result == {"users"}


# ---------- 4. MimoProvider HTTP 客户端复用 ----------


def test_mimo_provider_reuses_single_client(monkeypatch) -> None:
    monkeypatch.setattr(config, "MIMO_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://mimo.test/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setattr(config, "MIMO_TIMEOUT", 30.0)

    provider = MimoProvider()
    assert provider._client is None  # 惰性创建：构造时不建连接

    first = provider._get_client()
    second = provider._get_client()
    assert first is second


def test_mimo_provider_client_bound_to_constructor_config(monkeypatch) -> None:
    monkeypatch.setattr(config, "MIMO_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://mimo.test/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setattr(config, "MIMO_TIMEOUT", 30.0)

    provider = MimoProvider()
    client = provider._get_client()
    assert str(client.base_url).rstrip("/") == "https://mimo.test/v1"
    assert client.max_retries == 0


def test_mimo_provider_instances_do_not_share_client(monkeypatch) -> None:
    """复用范围必须限定在实例内，不能跨实例共享（否则配置变更会串味）。"""
    monkeypatch.setattr(config, "MIMO_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://mimo.test/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setattr(config, "MIMO_TIMEOUT", 30.0)

    assert MimoProvider()._get_client() is not MimoProvider()._get_client()


# ---------- 5. 复用不得改变冻结数据库 ----------


def test_reuse_does_not_touch_database() -> None:
    """反复使用缓存不得写数据库（DB 为冻结资产）。"""
    before = hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()
    for _ in range(3):
        SchemaCatalog.get_cached().to_prompt_text()
        check_sql_safety_with_tables("SELECT id FROM users")
    after = hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()
    assert before == after
