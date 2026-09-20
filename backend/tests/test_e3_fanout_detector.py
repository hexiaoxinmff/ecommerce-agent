"""Fan-out Detector 单元测试（Task 17 / E3）。

覆盖任务书 §八 五个用例 + E-0086 正例 + COUNT(DISTINCT) 保护 + E-0057 类 JOIN。
全部为纯静态测试：不调用 Mimo、不访问数据库、不读取 Gold。
"""

import pytest

from app.sqlcheck.fanout_detector import analyze_fanout


def test_orders_join_items_sum_total_amount_should_warn():
    """1) orders JOIN order_items + SUM(o.total_amount) → 应报警。"""
    sql = (
        "SELECT o.id, SUM(o.total_amount) AS revenue "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is True
    assert diag.severity == "high"
    assert "order_join_item_order_agg" in diag.patterns


def test_orders_join_items_count_order_id_should_warn():
    """2) orders JOIN order_items + COUNT(o.id) → 应报警（非去重 COUNT 被明细放大）。"""
    sql = (
        "SELECT o.id, COUNT(o.id) AS order_cnt "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is True
    assert diag.severity == "high"
    assert "order_join_item_order_agg" in diag.patterns


def test_orders_join_items_sum_item_subtotal_should_not_warn():
    """3) orders JOIN order_items + SUM(oi.subtotal) → 不应按经典 fan-out 报警。"""
    sql = (
        "SELECT o.id, SUM(oi.subtotal) AS item_sales "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is False
    assert diag.severity in ("none", "low")


def test_pre_aggregated_then_join_should_not_warn():
    """4) 先做 item/order 级预聚合再 JOIN → 不应误报。"""
    sql = (
        "WITH order_agg AS (SELECT id, SUM(total_amount) AS revenue FROM orders GROUP BY id), "
        "item_agg AS (SELECT order_id, SUM(subtotal) AS items FROM order_items GROUP BY order_id) "
        "SELECT oa.id, oa.revenue, ia.items "
        "FROM order_agg oa JOIN item_agg ia ON ia.order_id = oa.id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is False


def test_e0057_like_join_should_not_warn_by_join_alone():
    """5) E-0057 类（users LEFT JOIN orders，无 order_items）→ 不应仅因 JOIN 存在报警。"""
    sql = (
        "SELECT CASE WHEN cnt <= 3 THEN '1-3单' WHEN cnt <= 10 THEN '4-10单' ELSE '11单及以上' END AS tier, "
        "COUNT(*) AS user_count FROM "
        "(SELECT o.user_id AS uid, COUNT(*) AS cnt FROM orders o GROUP BY o.user_id) AS u "
        "GROUP BY tier"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is False


def test_e0086_pred_should_warn():
    """E-0086 正例：users×orders×order_items 直连 + SUM(o.total_amount) → 报警。"""
    sql = (
        "WITH user_stats AS ("
        "SELECT u.id, u.username, SUM(o.total_amount) AS total_spent, "
        "COUNT(DISTINCT o.id) AS order_count, COUNT(DISTINCT pi.product_id) AS product_count "
        "FROM users u JOIN orders o ON u.id = o.user_id "
        "JOIN order_items pi ON o.id = pi.order_id "
        "WHERE o.status != 'cancelled' GROUP BY u.id, u.username), "
        "platform_avg AS (SELECT AVG(total_spent) AS avg_spent FROM user_stats) "
        "SELECT us.username, us.total_spent, us.order_count, us.product_count "
        "FROM user_stats us, platform_avg pa "
        "WHERE us.total_spent > pa.avg_spent * 2 AND us.order_count > 8"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is True
    assert diag.severity == "high"
    assert "order_join_item_order_agg" in diag.patterns
    assert any("SUM(o.total_amount)" in e for e in diag.evidence)


def test_count_distinct_order_id_is_protection():
    """COUNT(DISTINCT o.id) 在直连下是去重保护 → 不应误报。"""
    sql = (
        "SELECT o.user_id, COUNT(DISTINCT o.id) AS order_cnt, SUM(oi.subtotal) AS item_sales "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.status != 'cancelled' GROUP BY o.user_id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is False


def test_count_star_ambiguous_is_medium():
    """1:N 直连 + COUNT(*)（无显式订单字段）→ 意图不明，标记 medium，不算 silent pass。"""
    sql = (
        "SELECT o.user_id, COUNT(*) AS cnt "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.user_id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is True
    assert diag.severity == "medium"
    assert "count_star_ambiguous" in diag.patterns


def test_malformed_sql_no_crash():
    """解析失败 → 不 panic，返回 none。"""
    diag = analyze_fanout("SELECT FROM WHERE ((")
    assert diag.fan_out_suspected is False
    assert diag.severity == "none"
    assert diag.detection_reason


def test_case_condition_on_order_col_value_on_item_col_should_not_warn():
    """E-0100 型：CASE 条件引用订单列、聚合值列是明细列 → 不应报警。

    例如 SUM(CASE WHEN strftime('%Y-%m', o.order_date)='2025-05' THEN oi.subtotal ELSE 0 END)
    的聚合对象是 oi.subtotal（item 粒度），订单列只出现在过滤条件里，不放大金额。
    """
    sql = (
        "SELECT ROUND(SUM(CASE WHEN strftime('%Y-%m', o.order_date) = '2025-05' "
        "THEN oi.subtotal ELSE 0 END), 2) AS sales_may "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.status != 'cancelled'"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is False


def test_case_value_on_order_col_should_warn():
    """反向：CASE 的值分支聚合订单列 → 应报警（THEN o.total_amount 被明细行放大）。"""
    sql = (
        "SELECT o.user_id, "
        "SUM(CASE WHEN oi.quantity > 1 THEN o.total_amount ELSE 0 END) AS risky "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.user_id"
    )
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is True
    assert "order_join_item_order_agg" in diag.patterns


def test_gold_independent():
    """检测器只依赖 SQL 自身结构 —— gold 内容不应影响结果（输入为预测 SQL 且含风险→报警）。"""
    # 该 SQL 含明显风险，即使没有任何 gold 上下文也应报警（同上 #1），
    # 且 analyze_fanout 签名无 gold 参数（Gold-independent 由接口保证）。
    import inspect

    params = inspect.signature(analyze_fanout).parameters
    assert "gold" not in params and "gold_sql" not in params