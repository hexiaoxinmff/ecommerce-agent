"""GET /api/insights/overview 验收测试（第九阶段 Phase C）。

判据原则：**真实数据库是唯一事实来源，且真值必须独立重算**。
本文件不对 KPI / 趋势 / 类目 / Top 商品做任何数值写死断言，而是：
1. 用**与实现不同的 SQL 写法**（`substr` 而非 `strftime`、子查询而非 JOIN 条件、
   Python 侧 round 而非 SQL 侧 ROUND）重算真值，再与接口响应逐项比对；
2. 对每个"口径选择"配一个**反向保护测试**，并先断言"该反例确实能区分对错"
   （否则测试是空转的 —— 见下方 `_assert_discriminating` 的用法）。

覆盖：
A. HTTP 基本行为 + 鉴权（**必须带 Bearer**，决策 D6 于 2026-09-28 反转）
B. 真值对照（独立重算）
C. 口径正确性 + 反向保护
D. 只读边界（文件字节不变 + SQL 常量静态扫描）
E. 空数据库行为（200 + 空结构，不是 500）
F. 数据库异常行为（受控 503，不泄漏路径/traceback）
G. 非法参数行为
H. LLM 隔离（子进程语义判据）
I. 响应结构最小化

鉴权夹具说明：`authed_client` 走**真实** register → login → Bearer 校验链
（临时应用库，不触碰 `db/app.db`），**不使用 `dependency_overrides`** ——
否则被测的鉴权依赖被整条短路，401 用例就失去意义。
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import insights as insights_route
from app.core import config
from app.db import appdb
from app.db.sqlite import get_connection
from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]

OVERVIEW_PATH = "/api/insights/overview"
DB_UNAVAILABLE_DETAIL = "数据库不可用，请确认 db/ecommerce.db 存在且可读。"

# demo.ts 里的静态假常量（审计报告 §2.4）。库是冻结交付物，这些值不可能真实出现。
# 用途：防止"接口被接回 demo 常量"这类回归。
_DEMO_MONTH_SALES = "7,662,921"

_TREND_MONTHS = 12
_TOP_N = 5


# --------------------------------------------------------------------------
# 真值：独立重算（刻意用不同的 SQL 写法）
# --------------------------------------------------------------------------


def _truth_as_of() -> str | None:
    """最新订单日期（用 ORDER BY + LIMIT 而非 MAX）。"""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT order_date FROM orders ORDER BY order_date DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None


def _truth_month_kpi(month: str) -> tuple[float, int]:
    """本月销售额（明细口径，Phase 15 P0-2 统一）与订单量。

    独立写法：先按订单聚合明细金额（子查询），再过滤月份 —— 与实现的
    JOIN + strftime 不同路径，保证是真值对照。
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT SUM(t.amt), COUNT(*) FROM ("
            "  SELECT o.id, o.order_date, SUM(oi.subtotal) AS amt"
            "  FROM orders o JOIN order_items oi ON oi.order_id = o.id"
            "  WHERE o.status <> 'cancelled' GROUP BY o.id"
            ") t WHERE substr(t.order_date, 1, 7) = ?",
            (month,),
        ).fetchone()
    sales = float(row[0]) if row[0] is not None else 0.0
    return sales, int(row[1])


def _truth_month_pay(month: str) -> tuple[float, int]:
    """本月实付总额与订单数（订单口径，客单价专用）。"""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT SUM(total_amount), COUNT(*) FROM orders "
            "WHERE substr(order_date, 1, 7) = ? AND status <> 'cancelled'",
            (month,),
        ).fetchone()
    pay = float(row[0]) if row[0] is not None else 0.0
    return pay, int(row[1])


def _truth_users_total() -> int:
    with closing(get_connection()) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def _truth_cancelled_total() -> float:
    """被排除的 cancelled 订单总额（用于证明口径选择确实有区分度）。"""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT SUM(total_amount) FROM orders WHERE status = 'cancelled'"
        ).fetchone()
    return float(row[0]) if row[0] is not None else 0.0


def _truth_trend(months: int) -> list[tuple[str, float]]:
    """近 N 个月销售额（明细口径），正序（用 substr + Python 侧翻转）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT substr(o.order_date, 1, 7) AS m, SUM(oi.subtotal) "
            "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
            "WHERE o.status <> 'cancelled' GROUP BY m ORDER BY m DESC LIMIT ?",
            (months,),
        ).fetchall()
    return [(row[0], float(row[1]) if row[1] is not None else 0.0) for row in reversed(rows)]


def _truth_categories(n: int) -> list[tuple[str, float, int]]:
    """叶子类目销售额 Top N（用 IN 子查询而非 JOIN 条件）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT c.name, SUM(oi.subtotal), SUM(oi.quantity)
            FROM order_items oi
            JOIN orders o     ON o.id = oi.order_id
            JOIN products p   ON p.id = oi.product_id
            JOIN categories c ON c.id = p.category_id
            WHERE o.status <> 'cancelled'
              AND c.id IN (SELECT id FROM categories WHERE parent_id IS NOT NULL)
            GROUP BY c.id
            ORDER BY 2 DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
    return [
        (row[0], float(row[1]) if row[1] is not None else 0.0, int(row[2]))
        for row in rows
    ]


def _truth_top_products(n: int) -> list[tuple[str, int, float]]:
    """Top N 商品（用「先聚合子查询、再 JOIN 商品表」的不同写法）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT p.name, t.q, t.amt
            FROM (
                SELECT oi.product_id,
                       SUM(oi.quantity) AS q,
                       SUM(oi.subtotal) AS amt
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.status <> 'cancelled'
                GROUP BY oi.product_id
                ORDER BY amt DESC
                LIMIT ?
            ) t
            JOIN products p ON p.id = t.product_id
            ORDER BY t.amt DESC
            """,
            (n,),
        ).fetchall()
    return [
        (row[0], int(row[1]), float(row[2]) if row[2] is not None else 0.0)
        for row in rows
    ]


def _truth_leaf_category_names() -> set[str]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT name FROM categories WHERE parent_id IS NOT NULL"
        ).fetchall()
    return {row[0] for row in rows}


def _truth_root_category_names() -> set[str]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT name FROM categories WHERE parent_id IS NULL"
        ).fetchall()
    return {row[0] for row in rows}


def _truth_ddl() -> list[str]:
    """真实库的建表语句（供"空数据库"用例复刻同一 Schema）。"""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
        ).fetchall()
    return [row[0] for row in rows]


# --------------------------------------------------------------------------
# 响应取用
# --------------------------------------------------------------------------


def _overview(authed_client: TestClient) -> dict:
    response = authed_client.get(OVERVIEW_PATH)
    assert response.status_code == 200, response.text
    return response.json()


def _db_hash() -> str:
    return hashlib.sha256(Path(config.DB_PATH).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# 鉴权夹具（决策 D6 反转：overview 必须带 Bearer）
# --------------------------------------------------------------------------

_TEST_USERNAME = "insights-user"
_TEST_PASSWORD = "S3cret!pass"


@pytest.fixture()
def _auth_env(tmp_path, monkeypatch):
    """把应用库重定向到临时目录，**绝不触碰正式 `db/app.db`**。

    沿用 `test_auth_api.py` 的隔离手法：`appdb` 在每次调用时读
    `config.APP_DB_PATH`，因此 monkeypatch 该属性即可整体切换，
    无需 override 任何 FastAPI 依赖。
    """
    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "insights-api" / "test-app.db")
    appdb.init_app_db()
    yield


@pytest.fixture()
def anon_client(_auth_env) -> TestClient:
    """匿名客户端：用于验证「不带 token 必须被拒」。"""
    return TestClient(app)


@pytest.fixture()
def authed_client(_auth_env) -> TestClient:
    """已登录客户端：真实走完 register → login → Bearer 校验链。

    **刻意不用 `dependency_overrides`**（对比 `test_agent_api.py` 的做法）：
    本文件的核心契约之一恰恰是「overview 必须带 Bearer」，override 会把
    `get_current_session` 整条短路掉，401 用例就沦为自欺欺人的空转。
    走真实链路后，token 哈希、会话落库、过期检查都在被测范围内。

    `TestClient(headers=...)` 让**每条请求自动带上 Bearer**，
    因此 28 条既有用例的调用方式（`authed_client.get(...)`）完全不用改。
    """
    bootstrap = TestClient(app)
    registered = bootstrap.post(
        "/api/auth/register",
        json={
            "username": _TEST_USERNAME,
            "email": "insights@example.com",
            "password": _TEST_PASSWORD,
        },
    )
    assert registered.status_code == 201, registered.text

    logged_in = bootstrap.post(
        "/api/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text
    token = logged_in.json()["access_token"]

    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


# --------------------------------------------------------------------------
# A. HTTP 基本行为
# --------------------------------------------------------------------------


def test_overview_returns_200(authed_client: TestClient) -> None:
    assert authed_client.get(OVERVIEW_PATH).status_code == 200


def test_overview_is_get_only(authed_client: TestClient) -> None:
    """只读接口不接受写方法。"""
    assert authed_client.post(OVERVIEW_PATH).status_code == 405
    assert authed_client.delete(OVERVIEW_PATH).status_code == 405


def test_overview_rejects_request_without_token(anon_client: TestClient) -> None:
    """决策 D6（2026-09-28 反转）：**不带 Bearer 必须 401**。

    若此测试变红，说明鉴权依赖被摘掉了 —— 那首页就不再需要登录。
    """
    response = anon_client.get(OVERVIEW_PATH)
    assert response.status_code == 401
    # 统一文案 + WWW-Authenticate，不区分具体失败原因（抑制用户枚举）
    assert response.json()["detail"] == "Invalid credentials"
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_overview_rejects_forged_or_malformed_token(anon_client: TestClient) -> None:
    """伪造 / 畸形 / 非 Bearer 三类凭证一律 401，且文案不泄漏差异。"""
    for header in (
        "Bearer not-a-real-token",
        "Bearer ",
        "Basic YWxpY2U6cHc=",
        "not-even-a-scheme",
    ):
        response = anon_client.get(OVERVIEW_PATH, headers={"Authorization": header})
        assert response.status_code == 401, header
        assert response.json()["detail"] == "Invalid credentials", header


def test_overview_accepts_real_login_token(authed_client: TestClient) -> None:
    """真实注册 + 登录拿到的 token 可以正常取到业务数据（对照上一条 401）。"""
    response = authed_client.get(OVERVIEW_PATH)
    assert response.status_code == 200
    assert response.json()["as_of"] == _truth_as_of()


def test_overview_does_not_leak_user_identity(authed_client: TestClient) -> None:
    """门禁是**访问控制**，不是数据隔离：响应体不得含任何用户身份字段。

    防止后人误以为「加了鉴权 = 按用户隔离」而顺手塞进 user_id / username。
    """
    payload = authed_client.get(OVERVIEW_PATH).json()
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("user_id", "username", "session_id", "token", "password"):
        assert forbidden not in serialized, forbidden
    # 顶层键必须恰好是契约里的 6 个（新增字段会改变前端契约）
    assert set(payload) == {
        "as_of",
        "generated_at",
        "kpis",
        "sales_trend",
        "category_distribution",
        "top_products",
    }


def test_overview_route_registered_in_openapi(authed_client: TestClient) -> None:
    paths = authed_client.get("/openapi.json").json()["paths"]
    assert OVERVIEW_PATH in paths
    assert "get" in paths[OVERVIEW_PATH]


# --------------------------------------------------------------------------
# B. 真值对照（独立重算）
# --------------------------------------------------------------------------


def test_as_of_matches_latest_order_date(authed_client: TestClient) -> None:
    assert _overview(authed_client)["as_of"] == _truth_as_of()


def test_kpi_month_sales_matches_independent_recompute(authed_client: TestClient) -> None:
    month = _truth_as_of()[:7]
    expected, _ = _truth_month_kpi(month)
    kpi = _overview(authed_client)["kpis"]["month_sales"]
    assert kpi["value"] == pytest.approx(expected, abs=0.01)
    assert kpi["month"] == month
    assert kpi["unit"] == "元"


def test_kpi_month_orders_matches_independent_recompute(authed_client: TestClient) -> None:
    month = _truth_as_of()[:7]
    _, expected = _truth_month_kpi(month)
    kpi = _overview(authed_client)["kpis"]["month_orders"]
    assert kpi["value"] == expected
    assert kpi["unit"] == "单"


def test_kpi_users_total_matches_independent_recompute(authed_client: TestClient) -> None:
    """口径 D3：全表 COUNT(*)，不是 status='active'。"""
    kpi = _overview(authed_client)["kpis"]["users_total"]
    assert kpi["value"] == _truth_users_total()
    assert kpi["unit"] == "人"


def test_kpi_avg_order_value_is_order_pay_metric(authed_client: TestClient) -> None:
    """客单价 = 订单实付口径（SUM(total_amount)/COUNT(*)），Phase 15 起与
    销售额口径显式分离 —— 不得再用明细销售额除以订单数。"""
    month = _truth_as_of()[:7]
    pay, orders = _truth_month_pay(month)
    kpi = _overview(authed_client)["kpis"]["avg_order_value"]
    assert kpi["value"] == pytest.approx(round(pay / orders, 2), abs=0.01)
    assert kpi["unit"] == "元/单"

    # 反向保护：客单价不得等于 明细销售额/订单数（两口径在真实库必然不同）
    sales, _ = _truth_month_kpi(month)
    assert round(sales / orders, 2) != round(pay / orders, 2), (
        "明细口径与实付口径数值相同，本测试失去区分度"
    )


def test_sales_trend_matches_independent_recompute(authed_client: TestClient) -> None:
    expected = _truth_trend(_TREND_MONTHS)
    actual = _overview(authed_client)["sales_trend"]
    assert len(actual) == len(expected) == _TREND_MONTHS
    assert [p["month"] for p in actual] == [m for m, _ in expected]
    for point, (_, sales) in zip(actual, expected):
        assert point["sales"] == pytest.approx(sales, abs=0.01)


def test_sales_trend_is_ascending_and_ends_at_latest_month(authed_client: TestClient) -> None:
    """趋势必须时间正序（图从左到右），且最后一点是数据截止月。"""
    months = [p["month"] for p in _overview(authed_client)["sales_trend"]]
    assert months == sorted(months)
    assert months[-1] == _truth_as_of()[:7]


def test_category_distribution_matches_independent_recompute(authed_client: TestClient) -> None:
    expected = _truth_categories(_TOP_N)
    actual = _overview(authed_client)["category_distribution"]
    assert len(actual) == len(expected) == _TOP_N
    for item, (name, sales, qty) in zip(actual, expected):
        assert item["category"] == name
        assert item["sales"] == pytest.approx(sales, abs=0.01)
        assert item["quantity"] == qty


def test_top_products_matches_independent_recompute(authed_client: TestClient) -> None:
    expected = _truth_top_products(_TOP_N)
    actual = _overview(authed_client)["top_products"]
    assert len(actual) == len(expected) == _TOP_N
    for index, (item, (name, qty, sales)) in enumerate(zip(actual, expected), start=1):
        assert item["rank"] == index
        assert item["product"] == name
        assert item["quantity"] == qty
        assert item["sales"] == pytest.approx(sales, abs=0.01)


# --------------------------------------------------------------------------
# C. 口径正确性 + 反向保护
# --------------------------------------------------------------------------


def _truth_cancelled_rows_in(month: str) -> int:
    with closing(get_connection()) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM orders "
                "WHERE status = 'cancelled' AND substr(order_date, 1, 7) = ?",
                (month,),
            ).fetchone()[0]
        )


def test_month_orders_excludes_cancelled_orders(authed_client: TestClient) -> None:
    """口径 D2 的**有效**判据在"计数"上。

    实测数据事实（2026-09-28）：478 条 `cancelled` 订单的 `total_amount` **全部为 0**，
    因此排除 cancelled 对**金额是空转**（见下一个测试），但对**订单量有真实影响**：
    最新月全部状态 240 单 → 排除后 234 单。

    区分度证明：若最新月没有 cancelled 订单，本测试会先失败并明确告知失去区分度。
    """
    month = _truth_as_of()[:7]
    cancelled = _truth_cancelled_rows_in(month)
    assert cancelled > 0, f"{month} 无 cancelled 订单，本测试失去区分度"

    with closing(get_connection()) as conn:
        including = int(
            conn.execute(
                "SELECT COUNT(*) FROM orders WHERE substr(order_date, 1, 7) = ?",
                (month,),
            ).fetchone()[0]
        )

    actual = _overview(authed_client)["kpis"]["month_orders"]["value"]
    assert actual == including - cancelled
    assert actual != including, "接口把 cancelled 订单也算进了订单量"


def test_month_sales_excludes_cancelled_items_materially(
    authed_client: TestClient,
) -> None:
    """明细口径下（Phase 15 P0-2），排除 cancelled 对**金额有真实影响**。

    实测数据事实（2026-10-02）：cancelled 订单的 total_amount 恒为 0，但其
    order_items.subtotal 合计 = 1,674,278.89（非零）。旧口径（SUM(total_amount)）
    排除 cancelled 是空转；新口径（SUM(oi.subtotal)）下排除是实质约束。

    区分度证明：若某月 cancelled 明细金额为 0，本测试会先失败并告知失去区分度。
    """
    month = _truth_as_of()[:7]
    with closing(get_connection()) as conn:
        cancelled_amt = conn.execute(
            "SELECT COALESCE(SUM(oi.subtotal), 0) FROM order_items oi "
            "JOIN orders o ON o.id = oi.order_id "
            "WHERE o.status = 'cancelled' AND substr(o.order_date, 1, 7) = ?",
            (month,),
        ).fetchone()[0]
    assert float(cancelled_amt) > 0, (
        f"{month} 的 cancelled 订单明细金额为 0，本测试失去区分度"
    )

    with closing(get_connection()) as conn:
        including = conn.execute(
            "SELECT COALESCE(SUM(oi.subtotal), 0) FROM order_items oi "
            "JOIN orders o ON o.id = oi.order_id "
            "WHERE substr(o.order_date, 1, 7) = ?",
            (month,),
        ).fetchone()[0]
    excluding, _ = _truth_month_kpi(month)

    actual = _overview(authed_client)["kpis"]["month_sales"]["value"]
    assert actual == pytest.approx(excluding, abs=0.01)
    # 实质约束：排除后的销售额必须**小于**不排除（cancelled 明细金额非零）
    assert actual < float(including) - 0.01


def test_category_distribution_uses_leaf_categories_only(authed_client: TestClient) -> None:
    """口径 D4：必须是叶子类目，不能是顶层类目。

    区分度证明：顶层类目 Top1（数码家电）金额远大于叶子类目 Top1，
    若实现误用顶层类目，本测试必然变红。
    """
    leaves = _truth_leaf_category_names()
    roots = _truth_root_category_names()
    assert roots, "库中无顶层类目，本测试失去区分度"
    assert not (leaves & roots), "叶子类目与顶层类目集合重叠，本测试失去区分度"

    names = [item["category"] for item in _overview(authed_client)["category_distribution"]]
    assert names, "类目分布为空"
    assert set(names) <= leaves, f"返回了非叶子类目: {set(names) - leaves}"
    assert not (set(names) & roots), f"返回了顶层类目: {set(names) & roots}"


def test_top_products_sorted_by_sales_not_quantity(authed_client: TestClient) -> None:
    """口径 D5：按销售额排序。

    区分度证明：真实库"按销量 Top1"与"按销售额 Top1"是两个不同商品，
    若实现误按销量排序，本测试必然变红。
    """
    with closing(get_connection()) as conn:
        by_qty = conn.execute(
            "SELECT p.name FROM order_items oi "
            "JOIN orders o ON o.id = oi.order_id "
            "JOIN products p ON p.id = oi.product_id "
            "WHERE o.status <> 'cancelled' "
            "GROUP BY p.id ORDER BY SUM(oi.quantity) DESC LIMIT 1"
        ).fetchone()[0]
    by_sales = _truth_top_products(1)[0][0]
    assert by_qty != by_sales, "销量 Top1 与销售额 Top1 相同，本测试失去区分度"

    items = _overview(authed_client)["top_products"]
    assert items[0]["product"] == by_sales
    assert items[0]["product"] != by_qty
    # 销售额必须单调不增
    sales = [item["sales"] for item in items]
    assert sales == sorted(sales, reverse=True)


def test_category_distribution_sorted_by_sales_desc(authed_client: TestClient) -> None:
    sales = [item["sales"] for item in _overview(authed_client)["category_distribution"]]
    assert sales == sorted(sales, reverse=True)


def test_overview_does_not_serve_demo_constants(authed_client: TestClient) -> None:
    """回归保护：接口绝不能返回 data/demo.ts 里的静态假常量。

    依据审计报告 §2.4：demo 的「本月销售额 ¥7,662,921」是真实值的 10 倍。
    若这里命中，说明有人把接口接回了 demo 常量。
    """
    text = authed_client.get(OVERVIEW_PATH).text
    assert _DEMO_MONTH_SALES not in text
    # 同时确认接口返回的确实是"那个真实值"，而不是空壳
    month = _truth_as_of()[:7]
    expected, _ = _truth_month_kpi(month)
    assert _overview(authed_client)["kpis"]["month_sales"]["value"] == pytest.approx(expected, abs=0.01)


def test_overview_has_no_trend_percentage_fields(authed_client: TestClient) -> None:
    """刻意不返回趋势百分比（demo 的 +12.4% 无真实来源，不编）。"""
    payload = _overview(authed_client)
    for kpi in payload["kpis"].values():
        assert set(kpi) == {"label", "value", "unit", "month"}
    assert "%" not in authed_client.get(OVERVIEW_PATH).text


# --------------------------------------------------------------------------
# D. 只读边界
# --------------------------------------------------------------------------


def test_overview_leaves_database_byte_identical(authed_client: TestClient) -> None:
    hash_before = _db_hash()
    payload = _overview(authed_client)
    assert payload["kpis"]["month_sales"]["value"] > 0
    assert _db_hash() == hash_before


_FORBIDDEN_SQL_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "PRAGMA",
    "ATTACH",
    "DETACH",
    "VACUUM",
    "REINDEX",
    "TRUNCATE",
    "GRANT",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
)


def _sql_constants() -> dict[str, str]:
    """实现里的 SQL 常量（按 `_SQL` 前缀精确取，避免把模块 docstring 也算进来）。"""
    return {
        name: value
        for name, value in vars(insights_route).items()
        if name.startswith("_SQL") and isinstance(value, str)
    }


def test_all_overview_sql_is_read_only() -> None:
    """静态扫描：模块内每一条 SQL 常量都必须是单条只读 SELECT/WITH。

    这是"只读"的第一道闸门（第二道是 `mode=ro` + `query_only=ON` 连接本身）。
    """
    sql_constants = _sql_constants()
    assert len(sql_constants) >= 5, f"未找到预期的 SQL 常量: {sorted(sql_constants)}"

    for name, sql in sql_constants.items():
        upper = sql.upper()
        assert upper.lstrip().startswith(("SELECT", "WITH")), f"{name} 不是只读语句"
        assert ";" not in sql.strip().rstrip(";"), f"{name} 含多语句"
        for keyword in _FORBIDDEN_SQL_KEYWORDS:
            assert keyword not in upper, f"{name} 含被禁关键字 {keyword}"


def test_overview_sql_uses_bound_parameters_only() -> None:
    """实现不得把任何外部输入拼进 SQL：所有可变部分必须走 `?` 占位符。"""
    checked = 0
    for name, value in _sql_constants().items():
        if "LIMIT" in value.upper() or "= ?" in value:
            assert "?" in value, f"{name} 的变量部分未使用绑定参数"
            checked += 1
    assert checked >= 3, f"只检查到 {checked} 条带参数的 SQL，覆盖面不足"


# --------------------------------------------------------------------------
# E. 空数据库行为
# --------------------------------------------------------------------------


@pytest.fixture()
def empty_db(tmp_path: Path) -> Path:
    """复刻真实库 Schema 的空数据库（0 行）。"""
    db_file = tmp_path / "empty.db"
    conn = sqlite3.connect(db_file)
    try:
        for statement in _truth_ddl():
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()
    return db_file


def test_overview_returns_200_and_empty_structure_on_empty_database(
    authed_client: TestClient, monkeypatch, empty_db: Path
) -> None:
    """空库必须是 200 + 空结构，**不是 500**（前端要能渲染"暂无数据"）。"""
    monkeypatch.setattr(config, "DB_PATH", empty_db)
    response = authed_client.get(OVERVIEW_PATH)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["as_of"] is None
    assert payload["kpis"]["month_sales"]["value"] == 0.0
    assert payload["kpis"]["month_orders"]["value"] == 0
    assert payload["kpis"]["users_total"]["value"] == 0
    assert payload["kpis"]["avg_order_value"]["value"] == 0.0
    assert payload["kpis"]["month_sales"]["month"] is None
    assert payload["sales_trend"] == []
    assert payload["category_distribution"] == []
    assert payload["top_products"] == []


def test_overview_empty_database_does_not_leak_paths(
    authed_client: TestClient, monkeypatch, empty_db: Path
) -> None:
    monkeypatch.setattr(config, "DB_PATH", empty_db)
    text = authed_client.get(OVERVIEW_PATH).text
    assert "Traceback" not in text
    assert str(empty_db) not in text


# --------------------------------------------------------------------------
# F. 数据库异常行为
# --------------------------------------------------------------------------


def test_overview_returns_controlled_503_when_database_missing(
    authed_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DB_PATH", Path("no-such-dir") / "ecommerce.db")
    response = authed_client.get(OVERVIEW_PATH)
    assert response.status_code == 503
    assert response.json()["detail"] == DB_UNAVAILABLE_DETAIL
    assert "Traceback" not in response.text
    assert "sqlite3" not in response.text
    assert "no-such-dir" not in response.text


# --------------------------------------------------------------------------
# G. 非法参数行为
# --------------------------------------------------------------------------


def test_overview_ignores_unknown_query_params(authed_client: TestClient) -> None:
    """接口不接收任何参数：多余 query string 必须被忽略，而不是 500 或改变结果。"""
    baseline = _overview(authed_client)
    for query in ("?foo=1", "?limit=999999", "?month=1900-01", "?top_n=-5&page=abc"):
        response = authed_client.get(OVERVIEW_PATH + query)
        assert response.status_code == 200, f"{query} -> {response.status_code}"
        payload = response.json()
        assert payload["kpis"] == baseline["kpis"]
        assert payload["top_products"] == baseline["top_products"]


def test_overview_rejects_trailing_slash_variants(authed_client: TestClient) -> None:
    """路径必须精确：`/overview/` 由 FastAPI 重定向，不应 500。"""
    response = authed_client.get(OVERVIEW_PATH + "/", follow_redirects=False)
    assert response.status_code in (307, 308)


# --------------------------------------------------------------------------
# H. LLM 隔离（语义判据，子进程 + 全新解释器）
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
import app.api.routes.insights
prefixes = {_ISOLATION_PREFIXES!r}
leaked = sorted(n for n in sys.modules if n.startswith(prefixes))
assert not leaked, "insights 路由导入链污染了 LLM/Agent/SQL 层: %s" % leaked
assert "openai" not in sys.modules, "openai SDK 被加载"
print("ISOLATED")
"""


def test_insights_route_import_chain_excludes_llm_and_openai() -> None:
    """只导入 insights 路由模块，不得连带加载 LLM / Agent / SQL 层或 openai SDK。

    用子进程 + 全新解释器，而不是本进程 `sys.modules`：conftest 会
    `import app.main`，而 `app.main` → agent 路由 → `app.llm.provider`，
    本进程里 `openai` 必然已加载 —— 用它当判据属于自指假阳性。
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
# I. 响应结构最小化
# --------------------------------------------------------------------------


def test_overview_response_shape_is_minimal(authed_client: TestClient) -> None:
    payload = _overview(authed_client)
    assert set(payload) == {
        "as_of",
        "generated_at",
        "kpis",
        "sales_trend",
        "category_distribution",
        "top_products",
    }
    assert set(payload["kpis"]) == {
        "month_sales",
        "month_orders",
        "users_total",
        "avg_order_value",
    }
    for point in payload["sales_trend"]:
        assert set(point) == {"month", "sales"}
    for item in payload["category_distribution"]:
        assert set(item) == {"category", "sales", "quantity"}
    for item in payload["top_products"]:
        assert set(item) == {"rank", "product", "quantity", "sales"}
