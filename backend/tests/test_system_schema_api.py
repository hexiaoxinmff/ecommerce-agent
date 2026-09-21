"""GET /api/system/schema 验收测试（Task 40 Phase 2-A）。

判据原则：**真实数据库是唯一事实来源**。
本文件不对字段名 / 类型 / 行数 / 描述做字符串写死断言，而是逐项与
直连数据库（PRAGMA table_info / PRAGMA foreign_key_list / SELECT COUNT(*)）
以及 metadata.py 既有描述常量做对照。

覆盖：
A. HTTP 基本行为
B. 表完整性（恰好 5 张业务表，无 sqlite_*）
C. 字段真值（name / type / not_null / primary_key）
D. 外键真值
E. description 来源
F. row_count 真值
G. 只读证明（数据库文件 SHA256 前后相同）
H. LLM 隔离（子进程语义判据，非关键词 grep）
I. Provider 配置不可用时仍正常
J. 数据库不存在时受控 503
K. 响应结构最小化（不含 DDL / CHECK 等未来字段）
"""

import hashlib
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.db.sqlite import TABLE_NAMES, get_connection
from app.main import app
from app.schema.metadata import COLUMN_DESCRIPTIONS, SchemaCatalog, TABLE_DESCRIPTIONS

BACKEND_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_PATH = "/api/system/schema"
DB_UNAVAILABLE_DETAIL = "数据库不可用，请确认 db/ecommerce.db 存在且可读。"


# --------------------------------------------------------------------------
# 直连数据库取真值（不经过被测代码）
# --------------------------------------------------------------------------


def _db_hash() -> str:
    """数据库文件内容哈希。"""
    return hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()


def _real_table_names() -> list[str]:
    """真实业务表名（排除 sqlite_ 系统表）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    return sorted(row[0] for row in rows)


def _pragma_columns(table: str) -> list[dict]:
    """直连 PRAGMA table_info 的字段真值。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        {
            "name": row[1],
            "type": row[2] or "",
            "not_null": bool(row[3]),
            "primary_key": bool(row[5]),
        }
        for row in rows
    ]


def _pragma_foreign_keys(table: str) -> list[dict]:
    """直连 PRAGMA foreign_key_list 的外键真值（排序口径与接口一致）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    foreign_keys = [
        {
            "from_column": row[3],
            "to_table": row[2],
            "to_column": row[4] or "",
        }
        for row in rows
    ]
    return sorted(
        foreign_keys,
        key=lambda fk: (fk["from_column"], fk["to_table"], fk["to_column"]),
    )


def _real_row_count(table: str) -> int:
    """直连 COUNT(*) 的行数真值。"""
    with closing(get_connection()) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --------------------------------------------------------------------------
# 接口响应取用
# --------------------------------------------------------------------------


def _fetch(client: TestClient) -> dict:
    response = client.get(SCHEMA_PATH)
    assert response.status_code == 200, response.text
    return response.json()


def _table_of(payload: dict, table: str) -> dict:
    matches = [item for item in payload["tables"] if item["table"] == table]
    assert matches, f"响应中缺少表 {table}"
    return matches[0]


# --------------------------------------------------------------------------
# A. HTTP 基本行为
# --------------------------------------------------------------------------


def test_schema_endpoint_returns_200(client: TestClient) -> None:
    assert client.get(SCHEMA_PATH).status_code == 200


def test_schema_endpoint_is_get_only(client: TestClient) -> None:
    """只读接口不应接受写方法。"""
    assert client.post(SCHEMA_PATH).status_code == 405


# --------------------------------------------------------------------------
# B. 表完整性
# --------------------------------------------------------------------------


def test_schema_returns_exactly_five_business_tables(client: TestClient) -> None:
    payload = _fetch(client)
    names = [item["table"] for item in payload["tables"]]
    assert len(names) == 5
    assert set(names) == set(TABLE_NAMES)
    assert set(names) == set(_real_table_names())


def test_schema_table_names_exclude_sqlite_internal(client: TestClient) -> None:
    payload = _fetch(client)
    assert not [item["table"] for item in payload["tables"] if item["table"].startswith("sqlite_")]


def test_schema_table_order_is_deterministic(client: TestClient) -> None:
    """表顺序由 SchemaCatalog 决定，必须稳定（页面按此顺序展示）。"""
    payload = _fetch(client)
    assert [item["table"] for item in payload["tables"]] == list(TABLE_NAMES)


def test_schema_reports_real_database_name(client: TestClient) -> None:
    payload = _fetch(client)
    assert payload["database"] == Path(config.DB_PATH).name


# --------------------------------------------------------------------------
# C. 字段真值
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_schema_columns_match_pragma_table_info(client: TestClient, table: str) -> None:
    payload = _fetch(client)
    api_columns = [
        {key: column[key] for key in ("name", "type", "not_null", "primary_key")}
        for column in _table_of(payload, table)["columns"]
    ]
    assert api_columns == _pragma_columns(table)


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_schema_has_at_least_one_primary_key(client: TestClient, table: str) -> None:
    payload = _fetch(client)
    primary_keys = [
        column["name"]
        for column in _table_of(payload, table)["columns"]
        if column["primary_key"]
    ]
    assert primary_keys, f"{table} 未返回主键"


# --------------------------------------------------------------------------
# D. 外键真值
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_schema_foreign_keys_match_pragma(client: TestClient, table: str) -> None:
    payload = _fetch(client)
    api_foreign_keys = [
        {key: fk[key] for key in ("from_column", "to_table", "to_column")}
        for fk in _table_of(payload, table)["foreign_keys"]
    ]
    assert api_foreign_keys == _pragma_foreign_keys(table)


def test_schema_foreign_key_edges_are_complete(client: TestClient) -> None:
    """5 条外键边一条都不能少（漏边会直接误导 Schema 页面读者）。"""
    payload = _fetch(client)
    edges = {
        (item["table"], fk["from_column"], fk["to_table"], fk["to_column"])
        for item in payload["tables"]
        for fk in item["foreign_keys"]
    }
    assert edges == {
        ("categories", "parent_id", "categories", "id"),
        ("products", "category_id", "categories", "id"),
        ("orders", "user_id", "users", "id"),
        ("order_items", "order_id", "orders", "id"),
        ("order_items", "product_id", "products", "id"),
    }


# --------------------------------------------------------------------------
# E. description 来源
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_schema_descriptions_come_from_metadata(client: TestClient, table: str) -> None:
    """描述必须逐字来自 metadata.py，不允许接口另造一套。"""
    payload = _fetch(client)
    api_table = _table_of(payload, table)
    assert api_table["description"] == TABLE_DESCRIPTIONS[table]
    for column in api_table["columns"]:
        assert column["description"] == COLUMN_DESCRIPTIONS[table][column["name"]]


def test_schema_descriptions_are_not_empty(client: TestClient) -> None:
    """反向保护：不允许用空串冒充「来自 metadata」。"""
    payload = _fetch(client)
    for item in payload["tables"]:
        assert item["description"], item["table"]
        for column in item["columns"]:
            assert column["description"], (item["table"], column["name"])


# --------------------------------------------------------------------------
# F. row_count 真值
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_schema_row_count_matches_real_query(client: TestClient, table: str) -> None:
    payload = _fetch(client)
    assert _table_of(payload, table)["row_count"] == _real_row_count(table)


# --------------------------------------------------------------------------
# G. 只读证明
# --------------------------------------------------------------------------


def test_schema_endpoint_leaves_database_byte_identical(client: TestClient) -> None:
    hash_before = _db_hash()
    payload = _fetch(client)
    assert len(payload["tables"]) == 5
    assert _db_hash() == hash_before


# --------------------------------------------------------------------------
# H. LLM 隔离（语义判据）
# --------------------------------------------------------------------------

_ISOLATION_PREFIXES = (
    "app.llm",
    "app.agent",
    "app.schema.linker",
    "app.sqlgen",
    "app.sqlrepair",
    "app.sqlexec",
    "app.fewshot",
)

_ISOLATION_PROBE = f"""
import sys
import app.api.routes.system
prefixes = {_ISOLATION_PREFIXES!r}
leaked = sorted(n for n in sys.modules if n.startswith(prefixes))
assert not leaked, "路由导入链污染了 LLM/Agent/SQL 层: %s" % leaked
assert "openai" not in sys.modules, "openai SDK 被加载"
print("ISOLATED")
"""


def test_schema_route_import_chain_excludes_llm_and_openai() -> None:
    """只导入 system 路由模块，不得连带加载 LLM / Agent / SQL 层或 openai SDK。

    刻意使用**子进程 + 全新解释器**做模块级语义判据，而不是本进程
    sys.modules：conftest 会 import app.main，而 app.main → agent 路由 →
    app.agent.graph → app.llm.provider，且 app/llm/__init__.py 会 import
    MimoProvider。因此本进程里 app.llm.mimo / openai 必然已在 sys.modules，
    用它当判据属于自指假阳性 —— 什么都没验证。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", _ISOLATION_PROBE],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ISOLATED"


# --------------------------------------------------------------------------
# I. Provider 不可用仍能工作
# --------------------------------------------------------------------------


def test_schema_endpoint_works_when_provider_unavailable(
    client: TestClient, monkeypatch
) -> None:
    """API Key 为空 / Base URL 不可达时，只读 Schema 接口必须照常返回 200。"""
    monkeypatch.setattr(config, "MIMO_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "MIMO_BASE_URL", "http://127.0.0.1:9/unreachable", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.setenv("MIMO_BASE_URL", "http://127.0.0.1:9/unreachable")

    payload = _fetch(client)
    assert payload["database"] == Path(config.DB_PATH).name
    assert len(payload["tables"]) == 5


# --------------------------------------------------------------------------
# J. 数据库不存在
# --------------------------------------------------------------------------


def test_schema_endpoint_returns_controlled_503_when_database_missing(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DB_PATH", Path("no-such-dir") / "ecommerce.db")
    # Schema 目录是进程级缓存，先清空，避免命中真实库的旧缓存
    SchemaCatalog.clear_cache()
    try:
        response = client.get(SCHEMA_PATH)
    finally:
        SchemaCatalog.clear_cache()

    assert response.status_code == 503
    assert response.json()["detail"] == DB_UNAVAILABLE_DETAIL
    assert "Traceback" not in response.text
    assert "sqlite3" not in response.text
    assert "no-such-dir" not in response.text


# --------------------------------------------------------------------------
# K. 响应结构最小化
# --------------------------------------------------------------------------


def test_schema_response_shape_is_minimal(client: TestClient) -> None:
    """接口保持最小：不暴露 DDL / CHECK 等未使用字段。"""
    payload = _fetch(client)
    assert set(payload) == {"database", "tables"}
    for item in payload["tables"]:
        assert set(item) == {"table", "description", "columns", "row_count", "foreign_keys"}
        for column in item["columns"]:
            assert set(column) == {"name", "type", "description", "not_null", "primary_key"}
        for fk in item["foreign_keys"]:
            assert set(fk) == {"from_column", "to_table", "to_column"}
