"""业务洞察聚合路由（第九阶段 Phase C）。

`GET /api/insights/overview` —— 首页 Dashboard 的唯一业务数据来源。

只读边界（与任务书 §六 一致）：
- 复用 `app.db.sqlite.get_connection()`：`mode=ro`（文件级只读）
  + `PRAGMA query_only = ON`（会话级只读）**双重只读**，本模块不新增第二条 DB 访问路径；
- 只执行本模块内**固定的 SELECT**，不接收、不拼接任何用户输入
  （无路径参数、无查询参数、无请求体）；
- 不导入 `app.llm` / `app.agent` / `app.sqlgen`，不发起任何 LLM 调用；
- 不写入任何数据库、文件或缓存。

口径（全部锚定真实数据；决策依据见 `reports/phase9/第九阶段第一轮AB_*.md` §6；
Phase 15（P0-2）起「销售额」口径与 Agent 的 KPI Definition 统一为明细口径）：
- **D1**「本月」= `MAX(orders.order_date)` 所在月，**不是 `date('now')`**。
  真实库是静态合成数据（最新 `2026-09-12`），用 `now` 会在未来某天算出空月。
- **D2** 销售额一律排除 `status = 'cancelled'`，且金额口径为
  `SUM(order_items.subtotal)`（商品明细行金额）—— 与
  `app/dbprofile/kpi_definitions.py` 的唯一 KPI 定义一致。
- **D3** 用户数 = `COUNT(*) FROM users`（全表 2,000；`status='active'` 是 1,707，二者不可混用）。
- **D4** 类目分布取**叶子类目**（`parent_id IS NOT NULL`）按销售额 Top 5，与首页既有视觉结构一致。
- **D5** Top 商品按**销售额**排序，与 D4 口径统一（明细口径）。
- **D5b**（Phase 15）客单价 = 本月订单**实付**金额均值（`SUM(total_amount)/COUNT(*)`，
  排除 cancelled）——它是独立指标，不再由「销售额/订单量」推导，两个口径不得混算。
- **D6**（2026-09-28 用户决策**反转**）**必须带 Bearer**：本路由挂
  `Depends(get_current_user)`，无 header / 非 Bearer / 未知 token / 过期会话
  一律 401 `{"detail": "Invalid credentials"}`。
  ⚠️ **边界必须说清：这是「访问门禁」，不是「数据隔离」。** 聚合口径是全库的，
  刻意**不**按 `user_id` 过滤（本库没有按用户归属的业务数据），响应体也不含任何
  用户身份字段。它只回答「你有没有登录」，不回答「你能看谁的数据」。
  若将来要提供按用户隔离的业务数据，**必须另开接口**，不得改这里的口径。
  前端配套：`HomePage` 已纳入 `ProtectedRoute`（未登录渲染登录页），
  因此「未登录首页 401」这一路径由路由守卫兜住，而不是靠接口放行。
- **D7** 返回 `as_of`，前端必须展示。

刻意不返回：
- 趋势百分比（无真实来源，不编）；
- 查询历史（用户私有数据，走 `GET /api/history` 的既有隔离）；
- 任何用户身份字段（`user_id` / `username` / `session_id` / token hash 一概不返回）。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.db.sqlite import DatabaseError, get_connection
from app.schemas.insights import (
    CategoryDistributionItem,
    KpiValue,
    OverviewKpis,
    OverviewResponse,
    SalesTrendPoint,
    TopProductItem,
)

router = APIRouter(tags=["insights"])

# 展示口径常量（不是可配置项：改这里必须同步改测试与审计报告）
_TREND_MONTHS = 12
_TOP_N = 5

_DB_UNAVAILABLE_DETAIL = "数据库不可用，请确认 db/ecommerce.db 存在且可读。"

# --------------------------------------------------------------------------
# 固定 SQL（模块级常量，便于审计与测试逐字比对）
#
# Phase 15（P0-2）口径统一：本项目「销售额」的唯一业务定义 =
# SUM(order_items.subtotal)（商品明细行金额），排除已取消订单 ——
# 与 Agent 的 KPI Definition（app/dbprofile/kpi_definitions.py）完全一致。
# 原先本模块用 SUM(orders.total_amount)（订单实付口径），与 Agent 形成
# 双真相源（Phase 14 实测两口径全库差约 150 万），已统一为明细口径。
# 「客单价」仍为订单实付口径（SUM(total_amount)/COUNT(*)），名称与口径
# 一并明确标注。涉及 orders × order_items JOIN 的计数必须
# COUNT(DISTINCT o.id) 防 fan-out（E-0086 教训）。

# 数据截止日：全库最新订单日期
_SQL_AS_OF = "SELECT MAX(order_date) FROM orders"

# 本月销售额（明细口径）+ 本月订单量（同一 WHERE，保证两者口径严格一致）
_SQL_MONTH_KPI = """
SELECT ROUND(SUM(oi.subtotal), 2), COUNT(DISTINCT o.id)
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE strftime('%Y-%m', o.order_date) = ?
  AND o.status != 'cancelled'
"""

# 本月实付总额 + 实付订单数（客单价专用，订单口径；与销售额口径显式分离）
_SQL_MONTH_PAY = """
SELECT ROUND(SUM(total_amount), 2), COUNT(*)
FROM orders
WHERE strftime('%Y-%m', order_date) = ?
  AND status != 'cancelled'
"""

# 平台注册用户数（全表，非 active）
_SQL_USERS_TOTAL = "SELECT COUNT(*) FROM users"

# 近 N 个月销售趋势（明细口径）：锚定最新月份倒推，取回后在 Python 侧翻正序
_SQL_SALES_TREND = """
SELECT strftime('%Y-%m', o.order_date)         AS month,
       ROUND(SUM(oi.subtotal), 2)              AS sales
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.status != 'cancelled'
GROUP BY month
ORDER BY month DESC
LIMIT ?
"""

# 叶子类目销售额 Top N
_SQL_CATEGORY_DISTRIBUTION = """
SELECT cat.name                       AS category,
       ROUND(SUM(oi.subtotal), 2)     AS sales,
       SUM(oi.quantity)               AS quantity
FROM order_items oi
JOIN orders     o   ON o.id = oi.order_id
JOIN products   p   ON p.id = oi.product_id
JOIN categories cat ON cat.id = p.category_id
WHERE o.status != 'cancelled'
  AND cat.parent_id IS NOT NULL
GROUP BY cat.id
ORDER BY sales DESC
LIMIT ?
"""

# Top N 商品（按销售额，与类目分布口径统一）
_SQL_TOP_PRODUCTS = """
SELECT p.name                       AS product,
       SUM(oi.quantity)             AS quantity,
       ROUND(SUM(oi.subtotal), 2)   AS sales
FROM order_items oi
JOIN orders   o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
WHERE o.status != 'cancelled'
GROUP BY p.id
ORDER BY sales DESC
LIMIT ?
"""


def _num(value: object) -> float:
    """聚合结果 -> float；空表时 SQL 的 SUM/ROUND 返回 NULL，统一收敛为 0.0。"""
    return float(value) if value is not None else 0.0


def _int(value: object) -> int:
    """聚合结果 -> int；空表时 SUM(quantity) 为 NULL，收敛为 0。"""
    return int(value) if value is not None else 0


def _load_overview() -> OverviewResponse:
    """在**单条只读连接**上执行全部固定 SQL，组装响应。

    单连接：保证 4 段聚合看到的是同一个数据库快照，避免跨连接读到不同状态。
    """
    conn = get_connection()
    try:
        (as_of_raw,) = conn.execute(_SQL_AS_OF).fetchone()
        as_of = as_of_raw if as_of_raw else None
        month = as_of[:7] if isinstance(as_of, str) and len(as_of) >= 7 else None

        if month is None:
            # 空库：本月指标无法定义，返回 0 而不是抛错（空库必须是 200，不是 500）
            month_sales, month_orders = 0.0, 0
            month_pay_total, month_pay_orders = 0.0, 0
        else:
            sales_raw, orders_raw = conn.execute(_SQL_MONTH_KPI, (month,)).fetchone()
            month_sales, month_orders = _num(sales_raw), _int(orders_raw)
            # 客单价走订单实付口径（与销售额口径显式分离，见 SQL 区注释）
            pay_raw, pay_orders_raw = conn.execute(_SQL_MONTH_PAY, (month,)).fetchone()
            month_pay_total, month_pay_orders = _num(pay_raw), _int(pay_orders_raw)

        (users_raw,) = conn.execute(_SQL_USERS_TOTAL).fetchone()
        users_total = _int(users_raw)

        avg_order_value = (
            round(month_pay_total / month_pay_orders, 2) if month_pay_orders else 0.0
        )

        # 趋势：SQL 侧按月倒序取最近 N 个月，这里翻成正序（时间从左到右）
        trend_rows = conn.execute(_SQL_SALES_TREND, (_TREND_MONTHS,)).fetchall()
        sales_trend = [
            SalesTrendPoint(month=row["month"], sales=_num(row["sales"]))
            for row in reversed(trend_rows)
        ]

        category_rows = conn.execute(_SQL_CATEGORY_DISTRIBUTION, (_TOP_N,)).fetchall()
        category_distribution = [
            CategoryDistributionItem(
                category=row["category"],
                sales=_num(row["sales"]),
                quantity=_int(row["quantity"]),
            )
            for row in category_rows
        ]

        top_rows = conn.execute(_SQL_TOP_PRODUCTS, (_TOP_N,)).fetchall()
        top_products = [
            TopProductItem(
                rank=index,
                product=row["product"],
                quantity=_int(row["quantity"]),
                sales=_num(row["sales"]),
            )
            for index, row in enumerate(top_rows, start=1)
        ]
    finally:
        conn.close()

    return OverviewResponse(
        as_of=as_of,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        kpis=OverviewKpis(
            month_sales=KpiValue(
                label="本月销售额", value=month_sales, unit="元", month=month
            ),
            month_orders=KpiValue(
                label="订单量", value=float(month_orders), unit="单", month=month
            ),
            users_total=KpiValue(label="平台注册用户", value=float(users_total), unit="人"),
            avg_order_value=KpiValue(
                label="客单价", value=avg_order_value, unit="元/单", month=month
            ),
        ),
        sales_trend=sales_trend,
        category_distribution=category_distribution,
        top_products=top_products,
    )


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="首页业务概览（只读聚合 + Bearer 鉴权，不调用 LLM）",
)
def insights_overview(_user=Depends(get_current_user)) -> OverviewResponse:
    """返回首页 Dashboard 所需的全部真实业务聚合数据。

    数据全部来自 `db/ecommerce.db` 的固定只读 SQL；不调用 LLM，不写任何数据。
    数据库不可用时返回受控 503（响应体只有 `detail`，不泄漏路径与 traceback）。

    `_user`（决策 D6 反转）：**只做登录门禁，刻意不参与任何过滤**。
    本接口是全库口径聚合，不是「我的数据」接口 —— 见模块 docstring 的边界说明。
    参数名带下划线前缀，是为了让「未被使用」这件事在代码里显式可见，
    防止后人顺手把它接进 WHERE 子句从而改变口径。
    """
    try:
        return _load_overview()
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE_DETAIL) from exc
