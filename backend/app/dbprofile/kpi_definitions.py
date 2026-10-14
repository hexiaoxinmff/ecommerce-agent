"""KPI Definition 注册表（Phase 15 · P0-2）。

问题（Phase 14 实证）：
- 「销售额」存在两个真相源：Agent 业务规则说「销售额 = order_items.subtotal
  （明细口径）」，而 Dashboard 的固定 SQL 用「SUM(orders.total_amount)（订单实付
  口径）」—— 同名指标两种算法，实测全库差 150 万元（33,206,362 vs 31,705,588）。
- 模型侧还系统性偏离 Profile 口径（RBQ-P20 口径题 4/4 静默错）。

本项目当前唯一业务定义（依据 docs/database-schema.md、sqlgen/prompt.py
BUSINESS_RULES「口径唯一权威」、E5 口径决策表，2026-09 起四端统一）：

    销售额（Sales）      = SUM(order_items.subtotal)，排除已取消订单 —— 明细口径
    订单实付（Order Pay）= orders.total_amount —— 订单口径（客单价/累计消费用）
    销量（Quantity）     = SUM(order_items.quantity)

本模块是这一定义的**唯一注册点**：
- to_prompt_block() 注入 Agent 生成 Prompt（与 Dashboard 无关地表达同一口径）；
- Dashboard 的固定 SQL 由 test_p0_kpi_consistency.py 钉死与本定义一致；
- Database/Profile 换库时只需提供该库的 KPI 文本（A/B 各一份，结构相同）。

Data As-Of 不在此硬编码：由 time_anchor.DataTimeContract 动态提供，
仅在文档性字段中以占位符说明。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KpiDefinition:
    """一个指标的正式定义（机器可读 + 可渲染为 Prompt 文本）。"""

    name: str
    definition: str
    source: str
    included_orders: str
    excluded_orders: str
    calculation: str
    aliases: tuple[str, ...] = ()  # 用户口语中会映射到本指标的说法
    forbidden: tuple[str, ...] = ()  # 禁止混用的来源字段

    def to_prompt_lines(self) -> str:
        alias_text = "、".join(self.aliases)
        alias_line = f"（含：{alias_text}）" if alias_text else ""
        forbidden_text = "；".join(self.forbidden)
        forbidden_line = f"禁止用 {' / '.join(self.forbidden)} 回答本指标；" if forbidden_text else ""
        return (
            f"- 「{self.name}」{alias_line}：一律 = {self.calculation}"
            f"（来源字段：{self.source}；计入：{self.included_orders}；"
            f"排除：{self.excluded_orders}）；{forbidden_line}\n"
        )


# ---------------------------------------------------------------------------
# A 库（ecommerce.db）口径 —— 与冻结基线 BUSINESS_RULES 的「口径唯一权威」一致
# ---------------------------------------------------------------------------

KPI_SALES_A = KpiDefinition(
    name="销售额",
    definition="商品明细行金额合计（line-item amount），未特别注明「实付」的一切「销售额」都用它",
    source="order_items.subtotal",
    included_orders="status != 'cancelled' 的订单的全部明细行",
    excluded_orders="status = 'cancelled' 的订单（其明细金额一并排除）",
    calculation="SUM(order_items.subtotal)（JOIN orders）",
    aliases=(
        "总销售额",
        "本月/上月/某月销售额",
        "商品/类目/地区销售额",
        "销售额趋势",
        "卖了多少",
        "销售金额",
    ),
    forbidden=("orders.total_amount",),
)

KPI_ORDER_PAY_A = KpiDefinition(
    name="订单实付金额",
    definition="订单最终支付金额（明细合计 - 优惠 + 运费）；客单价/累计消费用订单口径",
    source="orders.total_amount",
    included_orders="status != 'cancelled' 的订单",
    excluded_orders="status = 'cancelled' 的订单",
    calculation="SUM(orders.total_amount)（订单粒度聚合）",
    aliases=("客单价", "用户累计消费", "平均订单金额", "订单金额"),
)

KPI_QUANTITY_A = KpiDefinition(
    name="销量",
    definition="购买件数（与销售额是两个不同指标）",
    source="order_items.quantity",
    included_orders="同「销售额」的订单范围",
    excluded_orders="status = 'cancelled' 的订单",
    calculation="SUM(order_items.quantity)",
)


def kpi_rules_a() -> str:
    """A 库 KPI 口径 Prompt 文本（注入生成 Prompt 的附录）。"""
    return (
        "【KPI 口径定义】（唯一权威，与 Dashboard 完全一致，禁止二义）\n"
        + KPI_SALES_A.to_prompt_lines()
        + KPI_ORDER_PAY_A.to_prompt_lines()
        + KPI_QUANTITY_A.to_prompt_lines()
        + "- 用户只说「卖得怎么样 / 销售情况」等模糊说法时，默认按「销售额」口径理解；\n"
    )


# ---------------------------------------------------------------------------
# B 库（ecommerce_v2.db）口径 —— 结构同构，字段名不同
# ---------------------------------------------------------------------------


def kpi_rules_b() -> str:
    return (
        "【KPI 口径定义】（唯一权威，与 Dashboard 完全一致，禁止二义）\n"
        "- 「销售额」（含：总销售额、本月/上月销售额、商品/类目/城市销售额、销售趋势）："
        "一律 = SUM(order_lines.line_total)（明细行金额，JOIN sales_orders 并排除 "
        "order_state = 'voided'）；禁止用 sales_orders.payment_due 回答任何「销售额」问题；\n"
        "- 「订单应付金额 / 客单价 / 会员累计消费」：= sales_orders.payment_due（订单口径，"
        "订单粒度聚合），排除 voided；\n"
        "- 「销量」= SUM(order_lines.qty)；与销售额是两个不同指标；\n"
        "- 模糊说法（卖得怎么样/销售情况）默认按「销售额」口径理解。\n"
    )
