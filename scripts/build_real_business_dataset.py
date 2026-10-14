"""Phase 14：构建 Real Business Question Set（RBQ）数据集。

产物：data/eval/real_business_v1.json（新文件，不触碰任何冻结资产）。

设计来源（Phase 14 第一/二部分审计）：
- 从当前 A 库（db/ecommerce.db，dev-2026-09-14，数据 2024-01-01 ~ 2026-09-12）
  的真实结构、Dashboard 固定 SQL、Agent BUSINESS_RULES、前端示例问题反推；
- 40 题注册题（category A~F 六类，question/metadata 齐全）+ 4 题陷阱题
  （无 gold，人工评审，用于检验 Agent 的诚实拒绝能力）；
- value_tier=P20 的 20 题为「最有业务价值的 20 题」，进入真实 Agent 离线审计；
- 时间相对题的 gold 按「业务口径」给出（本月=库内最新数据月 2026-09、
  上个月=上一个完整自然月 2026-08、近30天=数据截止日往前 30 天），
  并在 business_rule 中显式声明 —— 这正是 Phase 14 要审计的时间漂移风险。

运行（项目根目录）：python scripts/build_real_business_dataset.py
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "ecommerce.db"
OUT_PATH = PROJECT_ROOT / "data" / "eval" / "real_business_v1.json"

# 数据事实（2026-10-02 审计日核对）：
#   MAX(order_date) = 2026-09-12（数据截止日，D_CUTOFF）
#   最新数据月 = 2026-09（部分月）；上一个完整自然月 = 2026-08
D_CUTOFF = "2026-09-12"
D_LAST_MONTH = "2026-09"
D_PREV_FULL_MONTH = "2026-08"
D_30D_START = "2026-08-14"  # 数据截止日往前 30 天（含）
D_7D_START = "2026-09-06"

_MONEY_SALES = (
    "SELECT ROUND(SUM(oi.subtotal), 2) "
    "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "WHERE o.status != 'cancelled'"
)


def _sales_where(extra: str = "") -> str:
    base = (
        "SELECT ROUND(SUM(oi.subtotal), 2) "
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status != 'cancelled'"
    )
    return f"{base}{(' AND ' + extra) if extra else ''}"


def _top_qty(extra: str = "", n: int = 5, order: str = "DESC") -> str:
    base = (
        "SELECT p.name AS product_name, SUM(oi.quantity) AS total_quantity "
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id "
        "WHERE o.status != 'cancelled'"
    )
    return (
        f"{base}{(' AND ' + extra) if extra else ''} "
        f"GROUP BY p.id ORDER BY total_quantity {order}, p.name LIMIT {n}"
    )


# ---------------------------------------------------------------------------
# 40 题注册题（category A 高频 / B 分析 / C 时间 / D 口径 / E 关联 / F 不规范）
# ---------------------------------------------------------------------------

ITEMS: list[dict] = [
    # ---------- A. 高频查询（8） ----------
    dict(
        id="RBQ-001", tier="P20", category="A", difficulty="easy",
        question="平台现在一共有多少个注册用户？",
        expected_business_intent="平台用户规模总量（注册口径，全量）",
        required_tables=["users"],
        business_rule="用户数 = users 全表 COUNT(*)（含 active 与 inactive）",
        expected_result_type="单值-整数",
        scenario="total_user_count", operators=["COUNT"],
        gold_sql="SELECT COUNT(*) FROM users",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-002", tier="P20", category="A", difficulty="easy",
        question="平台累计一共有多少笔订单？",
        expected_business_intent="累计订单总量（结构统计）",
        required_tables=["orders"],
        business_rule="订单量 = orders 全表 COUNT(*)，不排除 cancelled（结构统计口径）",
        expected_result_type="单值-整数",
        scenario="total_order_count", operators=["COUNT"],
        gold_sql="SELECT COUNT(*) FROM orders",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-003", tier="P20", category="A", difficulty="easy",
        question="目前有多少个活跃用户？",
        expected_business_intent="当前活跃（状态正常）用户数",
        required_tables=["users"],
        business_rule="活跃用户 = users.status = 'active'（非登录活跃度）",
        expected_result_type="单值-整数",
        scenario="active_user_count", operators=["COUNT", "FILTER"],
        gold_sql="SELECT COUNT(*) FROM users WHERE status = 'active'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-004", tier="P20", category="A", difficulty="medium",
        question="平台的总销售额是多少？",
        expected_business_intent="全库实际销售额规模",
        required_tables=["orders", "order_items"],
        business_rule="销售额默认=明细口径 SUM(order_items.subtotal)，排除 cancelled 订单",
        expected_result_type="单值-金额",
        scenario="total_sales", operators=["SUM", "JOIN", "FILTER"],
        gold_sql=_sales_where(),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-005", tier="P20", category="A", difficulty="medium",
        question="销量最高的 5 个商品是哪些？",
        expected_business_intent="商品维度畅销榜（按件数）",
        required_tables=["orders", "order_items", "products"],
        business_rule="销量 = SUM(quantity)（不是销售额）；排除 cancelled；Top 5",
        expected_result_type="Top-N-列表",
        scenario="top_products_by_qty", operators=["SUM", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=_top_qty(),
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-006", tier="P20", category="A", difficulty="medium",
        question="哪个商品类别的销售额最高？",
        expected_business_intent="类目维度销售贡献 Top 1",
        required_tables=["orders", "order_items", "products", "categories"],
        business_rule="销售额=明细口径 subtotal；排除 cancelled；按类目聚合取第一",
        expected_result_type="单值-类目+金额",
        scenario="top_category", operators=["SUM", "JOIN", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=(
            "SELECT c.name AS category_name, ROUND(SUM(oi.subtotal), 2) AS total_sales "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "JOIN products p ON p.id = oi.product_id "
            "JOIN categories c ON c.id = p.category_id "
            "WHERE o.status != 'cancelled' GROUP BY c.id ORDER BY total_sales DESC LIMIT 1"
        ),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-007", tier="P20", category="A", difficulty="medium",
        question="各地区的销售额排名是怎样的？",
        expected_business_intent="地区维度销售额分布（15 省）",
        required_tables=["orders", "order_items"],
        business_rule="地区用 orders.region 冗余列；销售额=明细口径；排除 cancelled；全量 15 行",
        expected_result_type="分组-列表",
        scenario="region_sales", operators=["SUM", "JOIN", "GROUP BY", "ORDER BY"],
        gold_sql=(
            "SELECT o.region AS region, ROUND(SUM(oi.subtotal), 2) AS total_sales "
            "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
            "WHERE o.status != 'cancelled' GROUP BY o.region ORDER BY total_sales DESC"
        ),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-008", tier="P20", category="A", difficulty="medium",
        question="平台的客单价是多少？",
        expected_business_intent="平均每笔订单的成交金额",
        required_tables=["orders"],
        business_rule="客单价 = SUM(total_amount)/COUNT(*)（订单实付口径），排除 cancelled",
        expected_result_type="单值-金额",
        scenario="avg_order_value", operators=["SUM", "COUNT", "FILTER"],
        gold_sql="SELECT ROUND(SUM(total_amount) * 1.0 / COUNT(*), 2) FROM orders WHERE status != 'cancelled'",
        answer_slots={"value_type": "currency"},
    ),
    # ---------- B. 分析问题（P20 内 5 题） ----------
    dict(
        id="RBQ-009", tier="P20", category="B", difficulty="easy",
        question="有多少笔订单被取消了？",
        expected_business_intent="取消单量（订单流失/异常监测）",
        required_tables=["orders"],
        business_rule="取消 = orders.status = 'cancelled'",
        expected_result_type="单值-整数",
        scenario="cancelled_count", operators=["COUNT", "FILTER"],
        gold_sql="SELECT COUNT(*) FROM orders WHERE status = 'cancelled'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-010", tier="P20", category="B", difficulty="easy",
        question="有哪些订单状态？每种状态各有多少笔订单？",
        expected_business_intent="订单状态分布全景",
        required_tables=["orders"],
        business_rule="结构统计：GROUP BY status 全状态计数，不排除任何状态",
        expected_result_type="分组-列表",
        scenario="status_distribution", operators=["COUNT", "GROUP BY"],
        gold_sql="SELECT status AS order_status, COUNT(*) AS order_count FROM orders GROUP BY status",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-015", tier="P20", category="B", difficulty="hard",
        question="有多少用户从来没有下过单？",
        expected_business_intent="沉睡/未转化用户规模（反连接）",
        required_tables=["users", "orders"],
        business_rule="从未下单 = users 中不存在 orders.user_id 引用（NOT EXISTS / LEFT JOIN IS NULL）",
        expected_result_type="单值-整数",
        scenario="never_ordered_users", operators=["COUNT", "ANTI JOIN"],
        gold_sql="SELECT COUNT(*) FROM users u WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-016", tier="P20", category="B", difficulty="medium",
        question="广东省的用户一共下了多少笔订单？",
        expected_business_intent="指定地区的订单规模（用户属性 JOIN 订单）",
        required_tables=["users", "orders"],
        business_rule="地区取 users.region（用户归属口径）；订单为结构统计不排除 cancelled",
        expected_result_type="单值-整数",
        scenario="region_orders_via_users", operators=["COUNT", "JOIN", "FILTER"],
        gold_sql="SELECT COUNT(*) FROM orders o JOIN users u ON u.id = o.user_id WHERE u.region = '广东'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-017", tier="P20", category="B", difficulty="medium",
        question="累计消费金额最高的 5 个用户是谁？",
        expected_business_intent="高价值用户榜",
        required_tables=["orders", "users"],
        business_rule="累计消费 = 订单实付口径 SUM(total_amount)，排除 cancelled；Top 5",
        expected_result_type="Top-N-列表",
        scenario="top_users_by_spend", operators=["SUM", "JOIN", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=(
            "SELECT u.username AS username, ROUND(SUM(o.total_amount), 2) AS total_spent "
            "FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.status != 'cancelled' GROUP BY u.id ORDER BY total_spent DESC, u.username LIMIT 5"
        ),
        answer_slots={"value_type": "currency"},
    ),
    # ---------- C. 时间问题（P20 内 5 题，全部为时间漂移风险区） ----------
    dict(
        id="RBQ-011", tier="P20", category="C", difficulty="medium",
        question="本月的销售额是多少？",
        expected_business_intent="最新月度销售规模",
        required_tables=["orders", "order_items"],
        business_rule=(
            f"本月 = 数据库最新数据月 {D_LAST_MONTH}（数据截至 {D_CUTOFF}，为部分月，"
            "与 Dashboard 口径 D1 一致）；销售额=明细口径；排除 cancelled。"
            "【已知风险】Agent 若按真实时钟 date('now') 取 2026-10 会得到空结果"
        ),
        expected_result_type="单值-金额",
        scenario="this_month_sales", operators=["SUM", "FILTER", "TIME"],
        gold_sql=_sales_where(f"strftime('%Y-%m', o.order_date) = '{D_LAST_MONTH}'"),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-012", tier="P20", category="C", difficulty="medium",
        question="今年以来每个月的销售额趋势是怎样的？",
        expected_business_intent="年度内月度趋势（看增长/下滑）",
        required_tables=["orders", "order_items"],
        business_rule="2026-01 至数据截止；按月分组升序；销售额=明细口径；排除 cancelled",
        expected_result_type="时间序列",
        scenario="monthly_trend_2026", operators=["SUM", "GROUP BY", "ORDER BY", "TIME"],
        gold_sql=(
            "SELECT strftime('%Y-%m', o.order_date) AS month, "
            "ROUND(SUM(oi.subtotal), 2) AS total_sales "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "WHERE o.status != 'cancelled' AND o.order_date >= '2026-01-01' "
            "GROUP BY strftime('%Y-%m', o.order_date) ORDER BY month"
        ),
        answer_slots={"value_type": "currency", "order_sensitive": True},
    ),
    dict(
        id="RBQ-013", tier="P20", category="C", difficulty="medium",
        question="最近 30 天销量最高的 5 个商品是哪些？",
        expected_business_intent="近期（30 天窗口）畅销榜",
        required_tables=["orders", "order_items", "products"],
        business_rule=(
            f"近30天 = 数据覆盖内最近 30 天（{D_30D_START} ~ {D_CUTOFF}）；"
            "销量=SUM(quantity)；排除 cancelled。"
            "【已知风险】Agent 若用 date('now','-30 day')（=2026-09-02）窗口只剩 11 天"
        ),
        expected_result_type="Top-N-列表",
        scenario="top30_products", operators=["SUM", "FILTER", "TIME", "LIMIT"],
        gold_sql=_top_qty(f"o.order_date BETWEEN '{D_30D_START}' AND '{D_CUTOFF}'"),
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-014", tier="P20", category="C", difficulty="easy",
        question="2025 年全年的销售额是多少？",
        expected_business_intent="指定完整年度销售规模",
        required_tables=["orders", "order_items"],
        business_rule="2025-01-01 ~ 2025-12-31；销售额=明细口径；排除 cancelled",
        expected_result_type="单值-金额",
        scenario="year_2025_sales", operators=["SUM", "FILTER", "TIME"],
        gold_sql=_sales_where("o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01'"),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-021", tier="P20", category="C", difficulty="medium",
        question="上个月的销售额是多少？",
        expected_business_intent="上一个完整自然月销售规模（最常用的月度回顾问题）",
        required_tables=["orders", "order_items"],
        business_rule=(
            f"上个月 = 上一个完整自然月 {D_PREV_FULL_MONTH}；销售额=明细口径；排除 cancelled。"
            "【已知风险】Agent 若用 strftime('now','-1 month') = 2026-09（部分月），"
            "数值只有完整月的约 1/3（实测 76.6 万 vs 220.7 万）"
        ),
        expected_result_type="单值-金额",
        scenario="last_month_sales", operators=["SUM", "FILTER", "TIME"],
        gold_sql=_sales_where(f"strftime('%Y-%m', o.order_date) = '{D_PREV_FULL_MONTH}'"),
        answer_slots={"value_type": "currency"},
    ),
    # ---------- D. 业务口径问题（P20 内 2 题） ----------
    dict(
        id="RBQ-019", tier="P20", category="D", difficulty="hard",
        question="被取消的订单涉及的总金额是多少？",
        expected_business_intent="取消订单的金额影响（退款/损失估计的替代口径）",
        required_tables=["orders"],
        business_rule=(
            "A 库口径：cancelled 订单的 total_amount 建库时清零 → 正确答案为 0；"
            "若 Agent 改用明细 subtotal 估算取消金额，数值非 0 但属于口径杜撰"
        ),
        expected_result_type="单值-金额",
        scenario="cancelled_amount", operators=["SUM", "FILTER"],
        gold_sql="SELECT ROUND(SUM(total_amount), 2) FROM orders WHERE status = 'cancelled'",
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-020", tier="P20", category="D", difficulty="medium",
        question="每个类目各有多少种在售商品？",
        expected_business_intent="类目在售商品数（商品结构盘点）",
        required_tables=["products", "categories"],
        business_rule="在售 = products.status = 'on_sale'（不是 availability/off_sale）",
        expected_result_type="分组-列表",
        scenario="on_sale_count_by_category", operators=["COUNT", "JOIN", "GROUP BY", "FILTER"],
        gold_sql=(
            "SELECT c.name AS category_name, COUNT(*) AS on_sale_count "
            "FROM products p JOIN categories c ON c.id = p.category_id "
            "WHERE p.status = 'on_sale' GROUP BY c.id ORDER BY on_sale_count DESC, c.name"
        ),
        answer_slots={"value_type": "integer"},
    ),
    # ---------- E. 多表关联（P20 内 0 题专设，RBQ-015/016/017 已覆盖） ----------
    # ---------- F. 不规范表述（P20 内 2 题） ----------
    dict(
        id="RBQ-022", tier="P20", category="F", difficulty="medium",
        question="哪个东西卖得最好？",
        expected_business_intent="口语化「东西」= 商品；「卖得最好」默认按销量（件数）",
        required_tables=["orders", "order_items", "products"],
        business_rule="口语映射：卖得最好 → 销量 SUM(quantity) Top 1；排除 cancelled",
        expected_result_type="单值-商品+数量",
        scenario="colloquial_best_seller", operators=["SUM", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=(
            "SELECT p.name AS product_name, SUM(oi.quantity) AS total_quantity "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "JOIN products p ON p.id = oi.product_id "
            "WHERE o.status != 'cancelled' GROUP BY p.id ORDER BY total_quantity DESC, p.name LIMIT 1"
        ),
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-023", tier="P20", category="F", difficulty="easy",
        question="哪个地区的用户最多？",
        expected_business_intent="用户地域分布 Top 1（前端示例问题之一）",
        required_tables=["users"],
        business_rule="按 users.region 计数取 Top 1（不涉及订单）",
        expected_result_type="单值-地区+数量",
        scenario="top_region_users", operators=["COUNT", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=(
            "SELECT region AS region_name, COUNT(*) AS user_count "
            "FROM users GROUP BY region ORDER BY user_count DESC, region LIMIT 1"
        ),
        answer_slots={"value_type": "integer"},
    ),
    # ============ 以下为扩展题（EXT，注册在案，暂不进入 P20 自动运行） ============
    dict(
        id="RBQ-024", tier="EXT", category="A", difficulty="easy",
        question="目前有多少种在售商品？",
        expected_business_intent="在售商品 SKU 数",
        required_tables=["products"],
        business_rule="在售 = products.status = 'on_sale'",
        expected_result_type="单值-整数",
        scenario="on_sale_product_count", operators=["COUNT", "FILTER"],
        gold_sql="SELECT COUNT(*) FROM products WHERE status = 'on_sale'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-025", tier="EXT", category="B", difficulty="medium",
        question="各个类别的销售额分布是怎样的？",
        expected_business_intent="全部类目销售额全景",
        required_tables=["orders", "order_items", "products", "categories"],
        business_rule="销售额=明细口径；排除 cancelled；全部类目",
        expected_result_type="分组-列表",
        scenario="category_sales_all", operators=["SUM", "JOIN", "GROUP BY"],
        gold_sql=(
            "SELECT c.name AS category_name, ROUND(SUM(oi.subtotal), 2) AS total_sales "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "JOIN products p ON p.id = oi.product_id "
            "JOIN categories c ON c.id = p.category_id "
            "WHERE o.status != 'cancelled' GROUP BY c.id ORDER BY total_sales DESC"
        ),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-026", tier="EXT", category="B", difficulty="medium",
        question="销量最差的 5 个商品是哪些？",
        expected_business_intent="滞销品识别",
        required_tables=["orders", "order_items", "products"],
        business_rule="销量升序 Top 5；排除 cancelled；只统计有销量的商品（无明细=0 的商品不在结果）",
        expected_result_type="Top-N-列表",
        scenario="worst_products", operators=["SUM", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=_top_qty(order="ASC"),
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-027", tier="EXT", category="C", difficulty="medium",
        question="本月的订单量是多少？",
        expected_business_intent="最新月订单量",
        required_tables=["orders"],
        business_rule=f"本月 = 数据库最新数据月 {D_LAST_MONTH}（部分月）；结构统计不排除 cancelled",
        expected_result_type="单值-整数",
        scenario="this_month_orders", operators=["COUNT", "FILTER", "TIME"],
        gold_sql=f"SELECT COUNT(*) FROM orders WHERE strftime('%Y-%m', order_date) = '{D_LAST_MONTH}'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-028", tier="EXT", category="C", difficulty="medium",
        question="最近 7 天的订单量是多少？",
        expected_business_intent="本周/近 7 天订单热度",
        required_tables=["orders"],
        business_rule=(
            f"近7天 = {D_7D_START} ~ {D_CUTOFF}（数据覆盖内）。"
            "【已知风险】date('now','-7 day') = 2026-09-25 之后无数据 → 空结果"
        ),
        expected_result_type="单值-整数",
        scenario="last7d_orders", operators=["COUNT", "FILTER", "TIME"],
        gold_sql=f"SELECT COUNT(*) FROM orders WHERE order_date BETWEEN '{D_7D_START}' AND '{D_CUTOFF}'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-029", tier="EXT", category="C", difficulty="medium",
        question="2026 年第二季度的销售额是多少？",
        expected_business_intent="指定季度销售规模",
        required_tables=["orders", "order_items"],
        business_rule="Q2 = 2026-04-01 ~ 2026-06-30；销售额=明细口径；排除 cancelled",
        expected_result_type="单值-金额",
        scenario="q2_sales", operators=["SUM", "FILTER", "TIME"],
        gold_sql=_sales_where("o.order_date >= '2026-04-01' AND o.order_date < '2026-07-01'"),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-030", tier="EXT", category="C", difficulty="medium",
        question="2024 年、2025 年、2026 年各年的销售额分别是多少？",
        expected_business_intent="分年度销售对比",
        required_tables=["orders", "order_items"],
        business_rule="按年分组；销售额=明细口径；排除 cancelled",
        expected_result_type="分组-列表",
        scenario="yearly_sales", operators=["SUM", "GROUP BY"],
        gold_sql=(
            "SELECT substr(o.order_date, 1, 4) AS year, ROUND(SUM(oi.subtotal), 2) AS total_sales "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "WHERE o.status != 'cancelled' GROUP BY substr(o.order_date, 1, 4) ORDER BY year"
        ),
        answer_slots={"value_type": "currency", "order_sensitive": True},
    ),
    dict(
        id="RBQ-031", tier="EXT", category="D", difficulty="medium",
        question="平台一共让利（优惠）了多少金额？",
        expected_business_intent="优惠让利总额",
        required_tables=["orders"],
        business_rule="让利 = SUM(discount_amount)；按订单口径；排除 cancelled（取消单让利视为未发生）",
        expected_result_type="单值-金额",
        scenario="total_discount", operators=["SUM", "FILTER"],
        gold_sql="SELECT ROUND(SUM(discount_amount), 2) FROM orders WHERE status != 'cancelled'",
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-032", tier="EXT", category="D", difficulty="medium",
        question="运费收入总共有多少？",
        expected_business_intent="运费收入规模",
        required_tables=["orders"],
        business_rule="运费 = SUM(shipping_fee)；排除 cancelled（未成交订单运费未收）",
        expected_result_type="单值-金额",
        scenario="total_shipping", operators=["SUM", "FILTER"],
        gold_sql="SELECT ROUND(SUM(shipping_fee), 2) FROM orders WHERE status != 'cancelled'",
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-033", tier="EXT", category="D", difficulty="medium",
        question="已完成的订单有多少笔？",
        expected_business_intent="履约完成订单量",
        required_tables=["orders"],
        business_rule="已完成 = orders.status = 'completed'",
        expected_result_type="单值-整数",
        scenario="completed_orders", operators=["COUNT", "FILTER"],
        gold_sql="SELECT COUNT(*) FROM orders WHERE status = 'completed'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-034", tier="EXT", category="E", difficulty="medium",
        question="买过商品的用户有多少个？",
        expected_business_intent="转化用户数（有订单行为的用户去重计数）",
        required_tables=["orders"],
        business_rule="COUNT(DISTINCT orders.user_id)（结构统计，含取消单的下单行为）",
        expected_result_type="单值-整数",
        scenario="converted_users", operators=["COUNT DISTINCT"],
        gold_sql="SELECT COUNT(DISTINCT user_id) FROM orders",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-035", tier="EXT", category="E", difficulty="hard",
        question="各地区用户的客单价对比是怎样的？",
        expected_business_intent="地区维度客单价对比（用户归属口径）",
        required_tables=["orders", "users"],
        business_rule="地区取 users.region（非订单冗余列）；客单价 = AVG(total_amount) 按订单；排除 cancelled",
        expected_result_type="分组-列表",
        scenario="region_aov_via_users", operators=["AVG", "JOIN", "GROUP BY"],
        gold_sql=(
            "SELECT u.region AS region, ROUND(AVG(o.total_amount), 2) AS avg_order_value "
            "FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.status != 'cancelled' GROUP BY u.region ORDER BY avg_order_value DESC"
        ),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-036", tier="EXT", category="E", difficulty="medium",
        question="哪个用户下单次数最多？",
        expected_business_intent="高频下单用户",
        required_tables=["orders", "users"],
        business_rule="下单次数 = COUNT(*)（含取消，结构统计）；Top 1",
        expected_result_type="单值-用户+次数",
        scenario="most_frequent_user", operators=["COUNT", "JOIN", "GROUP BY", "ORDER BY", "LIMIT"],
        gold_sql=(
            "SELECT u.username AS username, COUNT(*) AS order_count "
            "FROM orders o JOIN users u ON u.id = o.user_id "
            "GROUP BY u.id ORDER BY order_count DESC, u.username LIMIT 1"
        ),
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-037", tier="EXT", category="A", difficulty="easy",
        question="有多少个停用用户？",
        expected_business_intent="停用账号规模",
        required_tables=["users"],
        business_rule="停用 = users.status = 'inactive'",
        expected_result_type="单值-整数",
        scenario="inactive_users", operators=["COUNT", "FILTER"],
        gold_sql="SELECT COUNT(*) FROM users WHERE status = 'inactive'",
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-038", tier="EXT", category="B", difficulty="easy",
        question="目前售价最高的在售商品是什么？",
        expected_business_intent="在售商品价格带上限",
        required_tables=["products"],
        business_rule="售价 = products.price（当前标价，非成交价）；限 on_sale",
        expected_result_type="单值-商品+价格",
        scenario="highest_price_product", operators=["ORDER BY", "LIMIT", "FILTER"],
        gold_sql=(
            "SELECT name AS product_name, price AS current_price FROM products "
            "WHERE status = 'on_sale' ORDER BY price DESC LIMIT 1"
        ),
        answer_slots={"value_type": "currency"},
    ),
    dict(
        id="RBQ-039", tier="EXT", category="C", difficulty="medium",
        question="2026 年 9 月有多少笔取消订单？",
        expected_business_intent="指定月份取消单量",
        required_tables=["orders"],
        business_rule="月份 = 显式 2026-09；状态 = cancelled",
        expected_result_type="单值-整数",
        scenario="cancel_2026_09", operators=["COUNT", "FILTER", "TIME"],
        gold_sql=(
            "SELECT COUNT(*) FROM orders WHERE status = 'cancelled' "
            "AND strftime('%Y-%m', order_date) = '2026-09'"
        ),
        answer_slots={"value_type": "integer"},
    ),
    dict(
        id="RBQ-040", tier="EXT", category="D", difficulty="hard",
        question="平台平均每天有多少笔订单？",
        expected_business_intent="日均订单量（运营节奏）",
        required_tables=["orders"],
        business_rule="日均 = COUNT(*) / COUNT(DISTINCT order_date)（分母=实际有订单的天数，非固定天数）",
        expected_result_type="单值-数值",
        scenario="daily_avg_orders", operators=["COUNT", "COUNT DISTINCT"],
        gold_sql="SELECT ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT order_date), 2) FROM orders",
        answer_slots={"value_type": "scalar_number"},
    ),
    # ============ 陷阱题（TRAP，无 gold，人工评审） ============
    dict(
        id="TRAP-001", tier="TRAP", category="F", difficulty="hard",
        question="最近卖得怎么样？",
        expected_business_intent="模糊提问：期望给出最近销售概况或反问澄清",
        required_tables=["orders", "order_items"],
        business_rule="「最近」无明确定义；理想行为：给出合理默认窗口并声明，或反问澄清；最差行为：静默选一个无依据窗口",
        expected_result_type="人工评审",
        scenario="vague_recent_sales", operators=[],
        gold_sql=None,
        answer_slots={},
    ),
    dict(
        id="TRAP-002", tier="TRAP", category="F", difficulty="hard",
        question="有多少 VIP 用户？",
        expected_business_intent="库中不存在 VIP/会员等级概念",
        required_tables=["users"],
        business_rule="users 表无 tier/level 字段；理想行为：明确告知无此字段并给出最接近替代（如 active 用户）；最差行为：静默把 active/VIP 划等号",
        expected_result_type="人工评审",
        scenario="nonexistent_vip", operators=[],
        gold_sql=None,
        answer_slots={},
    ),
    dict(
        id="TRAP-003", tier="TRAP", category="F", difficulty="hard",
        question="退款金额一共有多少？",
        expected_business_intent="库中无退款字段（取消单金额已清零）",
        required_tables=["orders"],
        business_rule="无 refund 字段；cancelled 金额为 0 不等价于退款额；理想行为：说明口径限制；最差行为：用 SUM(total_amount WHERE cancelled)=0 冒充退款额",
        expected_result_type="人工评审",
        scenario="nonexistent_refund", operators=[],
        gold_sql=None,
        answer_slots={},
    ),
    dict(
        id="TRAP-004", tier="TRAP", category="C", difficulty="hard",
        question="上个月销售额环比增长了多少？",
        expected_business_intent="环比 = 本期/上期 - 1（多步计算）",
        required_tables=["orders", "order_items"],
        business_rule="需要两期销售额再计算比率；且「上个月」受时间漂移影响（now-1m=2026-09 为部分月）",
        expected_result_type="人工评审",
        scenario="mom_growth", operators=[],
        gold_sql=None,
        answer_slots={},
    ),
]


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    verified: list[dict] = []
    problems: list[str] = []
    for item in ITEMS:
        out = dict(item)
        gold = item.get("gold_sql")
        if gold:
            try:
                cur = conn.execute(gold)
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
                payload = json.dumps(
                    {"columns": cols, "rows": rows}, ensure_ascii=False,
                    default=str, sort_keys=True,
                ).encode("utf-8")
                out["gold_result_hash"] = hashlib.sha256(payload).hexdigest()[:16]
                out["gold_row_count"] = len(rows)
                out["gold_preview"] = [list(map(str, r)) for r in rows[:3]]
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{item['id']}: gold 执行失败 {exc}")
        verified.append(out)
    conn.close()

    if problems:
        raise SystemExit("Gold 校验失败：\n" + "\n".join(problems))

    p20 = [i for i in verified if i["tier"] == "P20"]
    doc = {
        "metadata": {
            "dataset_name": "Real Business Question Set",
            "version": "1.0",
            "created_at": "2026-10-02",
            "database_version": "dev-2026-09-14",
            "data_cutoff": D_CUTOFF,
            "description": (
                "Phase 14 真实业务问题集：40 题注册题（P20 20 题 + EXT 20 题）"
                "+ 4 题陷阱题（无 gold，人工评审）。gold 口径在 business_rule 中显式声明；"
                "时间相对题按业务口径锚定数据截止日（非真实时钟）。"
                "本数据集不进入正式 Benchmark，不触碰任何冻结资产。"
            ),
            "tier_counts": {
                "P20": len(p20),
                "EXT": len([i for i in verified if i["tier"] == "EXT"]),
                "TRAP": len([i for i in verified if i["tier"] == "TRAP"]),
            },
        },
        "items": verified,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OK 写出 {OUT_PATH}")
    print(f"题目数: {len(verified)}（P20={len(p20)}）")
    for i in p20:
        prev = "; ".join("/".join(r) for r in i.get("gold_preview", [])[:1])
        print(f"  {i['id']} [{i['category']}] {i['question']} -> {i.get('gold_row_count')}行 {prev[:60]}")


if __name__ == "__main__":
    main()
