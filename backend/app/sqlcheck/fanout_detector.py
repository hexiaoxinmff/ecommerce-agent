"""Fan-out 静态风险检测器（Task 17 / E3）。

只读、非干预的 SQL 结构分析器：用于识别 "1:N JOIN + Order-level Aggregation" 风险
（典型如 orders × order_items 直连后对订单级字段做 SUM/AVG/COUNT）。

设计约束（Task 17 任务书 §三）：
- 只读取 Pred SQL + AST，不读取 Gold SQL / Gold Result / Gold Label；
- 不修改 SQL、不触发 Repair、不影响 Agent 主链路；
- 输出诊断信息，不做 hard gate。

识别模式：
- Pattern A (order_join_item_order_agg)：orders 与 order_items 在同一 SELECT 的
  FROM/JOIN 直连，且 SELECT/HAVING 中出现对 orders 列的非去重聚合
  （SUM/AVG/COUNT），存在按明细行放大的风险。
- Pattern B (count_star_ambiguous)：直连下出现 COUNT(*)/COUNT(1)，
  意图（订单数 vs 明细数）无法从 AST 区分，标记 medium 风险提示。

不当成 fan-out 的情况（不报警）：
- 聚合参数全部为 order_items 粒度（oi.subtotal / oi.quantity / oi.unit_price*oi.quantity）；
- COUNT(DISTINCT orders主键) 去重保护；
- MIN/MAX(orders列)（重复行不影响最值）；
- orders 在独立 CTE/子查询完成订单级聚合后再 JOIN（不同查询块，无双表直连）；
- order_items 仅出现在 EXISTS 子查询中。

模块完全独立：不 import 任何 Agent / LLM / 数据库模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp


# 聚合名称 -> 是否可能因 1:N 直连产生膨胀
_AGG_INFLATE = {"SUM", "AVG", "COUNT"}
_AGG_NON_INFLATE = {"MIN", "MAX"}
_ALL_AGGS = _AGG_INFLATE | _AGG_NON_INFLATE

ORDER_TABLE = "orders"
ITEM_TABLE = "order_items"


@dataclass
class FanoutFinding:
    """单条发现。"""

    pattern: str
    severity: str  # high / medium / low
    evidence: list[str] = field(default_factory=list)
    protected: bool = False


@dataclass
class FanoutDiagnosis:
    """单条 SQL 的完整诊断结果。"""

    fan_out_suspected: bool
    severity: str  # high / medium / low / none
    patterns: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    detection_reason: str = ""


def _col_table(col: exp.Column) -> str:
    """Column 的限定表名（无限定返回 ''）。"""
    return (col.table or "").strip()


def _direct_tables(select: exp.Select) -> dict[str, str]:
    """当前 SELECT 的 FROM/JOIN 直接引用的表：{限定名(alias或原名): 真实表名}。

    不递归进入子查询 / CTE（它们各自是独立的 SELECT 节点）。
    """
    tables: dict[str, str] = {}
    source = select.args.get("from") or select.args.get("from_")
    if source and isinstance(source.this, exp.Table):
        t = source.this
        name = t.name.lower()
        key = (t.alias or name).lower()
        tables.setdefault(key, name)
    for join in select.args.get("joins") or []:
        jt = join.this
        if isinstance(jt, exp.Table):
            name = jt.name.lower()
            key = (jt.alias or name).lower()
            tables.setdefault(key, name)
    return tables


def _collect_agg_columns(node: exp.Expression) -> list[exp.Column]:
    """收集聚合参数中"参与求和的值列"。

    - 对 CASE WHEN 只取 THEN/ELSE 值分支（条件里出现的列只是过滤键，不放大金额）；
    - 遇到子查询/CTE 边界时停止（不跨查询块）。
    """
    cols: list[exp.Column] = []

    def _walk(n: exp.Expression) -> None:
        if isinstance(n, exp.Subquery):
            return
        if isinstance(n, exp.Column):
            cols.append(n)
            return
        if isinstance(n, exp.Case):
            # 只深入值分支：If.args["true"]=THEN 值，default=ELSE 值
            for w in n.args.get("ifs") or []:
                val = w.args.get("true") if isinstance(w, exp.If) else w
                if isinstance(val, exp.Expression):
                    _walk(val)
            if n.args.get("default") is not None and isinstance(n.args["default"], exp.Expression):
                _walk(n.args["default"])
            return
        for child in n.args.values():
            if isinstance(child, list):
                for c in child:
                    if isinstance(c, exp.Expression):
                        _walk(c)
            elif isinstance(child, exp.Expression):
                _walk(child)

    _walk(node)
    return cols


def _select_has_metric_aggregations(select: exp.Select) -> list[exp.Func]:
    """当前 SELECT 直接投影/HAVING 中的聚合函数（不深挖子查询）。"""
    aggs: list[exp.Func] = []
    projections = select.args.get("expressions") or []
    having = select.args.get("having")
    scan_nodes: list[exp.Expression] = list(projections)
    if having is not None:
        scan_nodes.append(having)
    for node in scan_nodes:
        for child in node.walk():
            # 不跨入子查询/CTE
            if isinstance(child, exp.Subquery):
                continue
            if isinstance(child, exp.AggFunc) and not isinstance(child, exp.ArrayAgg):
                aggs.append(child)
    return aggs


def _evidence_type(agg: exp.Func, table_map: dict[str, str]) -> str:
    """聚合的参数类型：order / item / mixed / star / other。"""
    this = agg.this
    # COUNT(*) / COUNT(1)
    if this is None or isinstance(this, exp.Star) or (isinstance(this, exp.Literal) and this.is_int):
        return "star"
    cols = _collect_agg_columns(this)
    if not cols:
        return "other"
    order_hit = any(_col_table(c).lower() in table_map and table_map[_col_table(c).lower()] == ORDER_TABLE
                    for c in cols)
    item_hit = any(_col_table(c).lower() in table_map and table_map[_col_table(c).lower()] == ITEM_TABLE
                   for c in cols)
    if order_hit and item_hit:
        return "mixed"
    if order_hit:
        return "order"
    if item_hit:
        return "item"
    return "other"


def _agg_sql_name(agg: exp.Func) -> str:
    return (agg.sql_name() or "").upper()


def analyze_fanout(sql: str) -> FanoutDiagnosis:
    """对单条 SQL 做静态 fan-out 风险分析。"""
    try:
        ast = sqlglot.parse_one(sql, read="sqlite")
    except Exception as exc:  # noqa: BLE001
        return FanoutDiagnosis(
            fan_out_suspected=False,
            severity="none",
            patterns=[],
            evidence=[],
            detection_reason=f"SQL 无法解析（{exc}），无法进行结构分析",
        )

    findings: list[FanoutFinding] = []
    for select in ast.find_all(exp.Select):
        table_map = _direct_tables(select)
        has_orders = ORDER_TABLE in table_map.values()
        has_items = ITEM_TABLE in table_map.values()
        if not (has_orders and has_items):
            continue  # 无 orders×order_items 直连 → 不过 Pattern A/B
        # 注意：MySQL 多层嵌套场景下 find_all 会重复遍历子查询里的 Select，
        # 但我们只对该 Select 自身的 FROM/JOIN 直连表做分析，子查询独立成块，
        # orders×order_items 在同一块直连才可能有 fan-out 放大。
        join_evidence = (
            f"orders 表与 order_items 表在同一查询块直连（JOIN/FROM），1:N 连接存在"
        )
        for agg in _select_has_metric_aggregations(select):
            name = _agg_sql_name(agg)
            if name not in _ALL_AGGS:
                continue
            distinct = isinstance(agg.this, exp.Distinct)
            etype = _evidence_type(agg, table_map)

            if etype == "item":
                continue  # item 粒度聚合，不误报
            if etype not in ("order", "mixed", "star", "other"):
                continue

            # MIN/MAX 不因重复行改变 → 无膨胀
            if name in _AGG_NON_INFLATE and etype in ("order", "mixed"):
                continue

            evidence_lines = [join_evidence]
            if etype in ("order", "mixed"):
                evidence_lines.append(f"订单级聚合 {agg.sql()}")
            elif etype == "star":
                evidence_lines.append(f"聚合 {agg.sql()}（COUNT(*) 在 1:N 直连下无法区分订单数/明细数）")

            if name in _AGG_INFLATE and distinct and etype in ("order", "mixed"):
                # COUNT(DISTINCT orders.id) 去重保护成立；其余订单级 DISTINCT 也按保护处理
                findings.append(FanoutFinding(
                    pattern="order_join_item_order_agg(protected)",
                    severity="low",
                    evidence=evidence_lines + ["订单级 DISTINCT 聚合（去重保护）"],
                    protected=True,
                ))
                continue

            if etype == "star":
                findings.append(FanoutFinding(
                    pattern="count_star_ambiguous",
                    severity="medium",
                    evidence=evidence_lines,
                    protected=False,
                ))
                continue

            if name in _AGG_INFLATE and etype in ("order", "mixed"):
                findings.append(FanoutFinding(
                    pattern="order_join_item_order_agg",
                    severity="high",
                    evidence=evidence_lines,
                    protected=False,
                ))

    if not findings:
        return FanoutDiagnosis(
            fan_out_suspected=False,
            severity="none",
            patterns=[],
            evidence=[],
            detection_reason="未发现 orders×order_items 直连下的订单级非去重聚合模式",
        )

    # 仅当存在非保护的高/中风险才视为 suspected；仅 protected/low 视为无风险
    risky = [f for f in findings if not f.protected and f.severity in ("high", "medium")]
    if not risky:
        return FanoutDiagnosis(
            fan_out_suspected=False,
            severity="low",
            patterns=[f.pattern for f in findings],
            evidence=[e for f in findings for e in f.evidence],
            detection_reason="存在订单级 DISTINCT 去重等保护，未判定为风险",
        )

    severity = "high" if any(f.severity == "high" for f in risky) else "medium"
    return FanoutDiagnosis(
        fan_out_suspected=True,
        severity=severity,
        patterns=sorted({f.pattern for f in risky}),
        evidence=[e for f in risky for e in f.evidence],
        detection_reason=(
            "检测到 orders×order_items 直连下存在订单级聚合（SUM/AVG/COUNT(orders列)/COUNT(*)），"
            "可能因 1:N 行数放大导致订单级指标重复累计"
        ),
    )


def to_dict(diag: FanoutDiagnosis, case_id: str = "") -> dict[str, Any]:
    """任务书 §四 统一诊断结构。"""
    return {
        "case_id": case_id,
        "fan_out_suspected": diag.fan_out_suspected,
        "severity": diag.severity,
        "patterns": diag.patterns,
        "evidence": diag.evidence,
        "detection_reason": diag.detection_reason,
    }