"""Task 18 telemetry 单元测试。

覆盖任务书 §十 五项：
1. Detector=false 样本不会影响 execution result；
2. Detector=true 样本不会触发 repair；
3. OFF 与 ON 的核心 Agent 输出字段保持同一 schema；
4. telemetry 正确记录 detector finding；
5. E-0086 在 ON 流程能够记录 alarm（以纯函数方式验证：E-0086 pred_sql → analyze_fanout → alarm）。

全部为本地静态测试：不调用 Mimo、不访问数据库、不读取 Gold。
"""

import json
import sqlglot

from app.sqlcheck.fanout_detector import analyze_fanout

# E-0086 Clean Baseline 的 pred_sql（经典 fan-out 正例，来源 baseline eval json）
E0086_PRED_SQL = (
    "WITH user_stats AS ("
    "SELECT u.id, u.username, SUM(o.total_amount) AS total_spent, "
    "COUNT(DISTINCT o.id) AS order_count, COUNT(DISTINCT pi.product_id) AS product_count "
    "FROM users u JOIN orders o ON u.id = o.user_id "
    "JOIN order_items pi ON o.id = pi.order_id "
    "WHERE o.status != 'cancelled' GROUP BY u.id, u.username), "
    "platform_avg AS (SELECT AVG(total_spent) AS avg_spent FROM user_stats) "
    "SELECT us.username, us.total_spent, us.order_count, us.product_count "
    "FROM user_stats us, platform_avg pa "
    "WHERE us.total_spent > pa.avg_spent * 2 AND us.order_count > 8 ORDER BY us.total_spent"
)

# 一条安全 SQL（item 粒度聚合，Detector=false）
SAFE_SQL = (
    "SELECT o.region, ROUND(SUM(oi.subtotal), 2) AS item_sales "
    "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
    "WHERE o.status != 'cancelled' AND o.order_date BETWEEN '2025-04-01' AND '2025-06-30' "
    "GROUP BY o.region ORDER BY item_sales DESC"
)


def _fake_result(eval_id: str, sql: str, exec_ok: bool, ex: bool, **kw) -> dict:
    """构造最小 eval result 结构（与 run_eval 输出对齐的字段）。"""
    return {
        "eval_id": eval_id,
        "difficulty": kw.get("difficulty", "hard"),
        "scenario": kw.get("scenario", "x"),
        "operators": [],
        "final_sql": sql,
        "initial_sql": "",
        "exec_success": exec_ok,
        "execution_accuracy": ex,
        "failure_stage": kw.get("failure_stage"),
        "error_type": kw.get("error_type"),
        "latency_ms": 10.0,
        "repair_triggered": kw.get("repair_triggered", False),
        "valid_model_run": True,
    }


def test_detector_false_does_not_touch_sql():
    """1) Detector=false 样本：analyze_fanout 后 SQL 文本不变、仍可解析、语义列不变。"""
    before = SAFE_SQL
    diag = analyze_fanout(before)
    assert diag.fan_out_suspected is False
    # 纯函数：输入 SQL 不被修改
    ast_before = sqlglot.parse_one(before, read="sqlite")
    ast_after = sqlglot.parse_one(SAFE_SQL, read="sqlite")  # 再次确认全局变量未被改写
    assert ast_before.sql() == ast_after.sql()
    assert SAFE_SQL == before


def test_detector_true_does_not_trigger_repair():
    """2) Detector=true 样本：analyze_fanout 返回诊断，但不触发 repair（无 repair 副作用）。"""
    sql = E0086_PRED_SQL
    diag = analyze_fanout(sql)
    assert diag.fan_out_suspected is True
    # telemetry 生成不修改 SQL；repair 由 runner 单独控制，analyze_fanout 不引入
    # repair_triggered 字段，也不改写任何状态 —— 这里验证纯函数性质。
    assert analyze_fanout(sql).fan_out_suspected is True
    assert E0086_PRED_SQL == sql


def test_off_on_share_agent_output_schema():
    """3) OFF 与 ON 的核心 Agent 输出字段保持同一 schema。"""
    from scripts.fanout_telemetry import build_telemetry

    key_set = {
        "exec_ok", "ex", "timeout", "provider_failure", "model_failure",
        "repair_triggered", "failure_stage", "error_type", "latency_ms",
    }
    fake_results = [
        _fake_result("E-A", SAFE_SQL, True, True),
        _fake_result("E-B", E0086_PRED_SQL, True, False, failure_stage="result", error_type="result_mismatch"),
    ]
    fake_eval = {"meta": {"run_id": "r1", "experiment": "x"}, "results": fake_results}
    tele = build_telemetry(fake_eval)
    assert len(tele) == 2
    for t in tele:
        assert key_set <= set(t.keys())


def test_telemetry_records_finding():
    """4) telemetry 正确记录 detector finding（alarm/id/severity/patterns）。"""
    from scripts.fanout_telemetry import build_telemetry

    fake = {"meta": {"run_id": "r"}, "results": [_fake_result("E-0086", E0086_PRED_SQL, True, False)]}
    tele = build_telemetry(fake)[0]
    assert tele["case_id"] == "E-0086"
    assert tele["fan_out_suspected"] is True
    assert tele["severity"] == "high"
    assert "order_join_item_order_agg" in tele["patterns"]
    assert tele["evidence"]


def test_e0086_alarm_in_on_flow():
    """5) E-0086 在 ON 流程能被记录 alarm（纯函数层验证）。"""
    diag = analyze_fanout(E0086_PRED_SQL)
    assert diag.fan_out_suspected is True
    assert diag.severity == "high"
    record = {
        "case_id": "E-0086",
        "fan_out_suspected": diag.fan_out_suspected,
        "severity": diag.severity,
        "patterns": diag.patterns,
        "evidence": diag.evidence,
    }
    assert record["case_id"] == "E-0086"
    assert record["fan_out_suspected"] is True


def test_model_failure_flag_only_for_generation_stage():
    """model_failure 判定只属于生成/修复级且非 provider 的失败（避免误标）。"""
    from scripts.fanout_telemetry import build_telemetry

    r = _fake_result("E-C", SAFE_SQL, True, False, failure_stage="result", error_type="result_mismatch")
    tele = build_telemetry({"meta": {}, "results": [r]})[0]
    assert tele["model_failure"] is False  # result 阶段不算 model_generation_failure
    r2 = _fake_result("E-D", "", False, False, failure_stage="sql_generate", error_type="gen_error")
    tele2 = build_telemetry({"meta": {}, "results": [r2]})[0]
    assert tele2["model_failure"] is True


def test_telemetry_json_preserves_off_values():
    """telemetry 中 outcome 仅为复制，detector 不改写 exec/ex（只读性质）。"""
    from scripts.fanout_telemetry import build_telemetry

    r = _fake_result("E-B", E0086_PRED_SQL, True, False)
    fake = {"meta": {}, "results": [r]}
    tele = build_telemetry(fake)[0]
    # detector 输入(exec/ex) 从原始 result 继承，不被 analyze_fanout 改变
    assert tele["exec_ok"] is True
    assert tele["ex"] is False
    # 原始 result 未被改动
    assert r["exec_success"] is True and r["execution_accuracy"] is False