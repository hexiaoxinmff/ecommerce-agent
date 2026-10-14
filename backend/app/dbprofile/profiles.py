"""内置 Database Profile 注册表（Phase 13 跨数据库迁移验证）。

- ecommerce_A：电商演示库 db/ecommerce.db（v1.0 冻结基线使用的库）。
  口径文本直接 import 自现有模块常量（单一权威来源，避免两处维护）；
- ecommerce_B：第二公司电商库 db/ecommerce_v2.db。
  表名 / 字段名 / 表关系 / 业务口径 / 枚举值均与 A 不同：
  * users→members、categories→departments（单层）、products→items、
    orders→sales_orders、order_items→order_lines；
  * sales_orders 无城市冗余列，城市维度必须 JOIN members；
  * 取消订单叫 voided（不是 cancelled）；用户状态是整数 is_active；
  * 「销售额」口径 / 优惠与运费字段 / 状态枚举全部改名换义。

本阶段只支持 ecommerce_A / ecommerce_B 两个 Profile，不扩展更多行业。
"""

import os

from app.core import config
from app.db.sqlite import TABLE_NAMES
from app.fewshot.retriever import KEYWORDS as KEYWORDS_A
from app.schema.linker import _EXAMPLE as _LINK_EXAMPLE_A
from app.schema.linker import BUSINESS_RULES as LINK_RULES_A
from app.schema.metadata import COLUMN_DESCRIPTIONS, TABLE_DESCRIPTIONS
from app.sqlgen.prompt import BUSINESS_RULES as GEN_RULES_A
from app.sqlrepair.prompt import BUSINESS_RULES as REPAIR_RULES_A

from app.dbprofile.models import (
    BusinessRulesProfile,
    DatabaseProfile,
    FewShotProfile,
    SchemaProfile,
)
from app.dbprofile.time_anchor import TimeAnchor
from app.dbprofile.kpi_definitions import kpi_rules_a, kpi_rules_b

DEFAULT_PROFILE_ID = "ecommerce_A"

# ---------------------------------------------------------------------------
# ecommerce_A：当前电商演示库（与 v1.0 冻结基线逐字节一致的知识）
# ---------------------------------------------------------------------------


def _ecommerce_a() -> DatabaseProfile:
    return DatabaseProfile(
        profile_id="ecommerce_A",
        db_type="sqlite",
        db_path=config.DB_PATH,
        domain_name="电商",
        schema=SchemaProfile(
            table_names=TABLE_NAMES,
            table_descriptions=TABLE_DESCRIPTIONS,
            column_descriptions=COLUMN_DESCRIPTIONS,
        ),
        business_rules=BusinessRulesProfile(
            generation_rules=GEN_RULES_A,
            schema_link_rules=LINK_RULES_A,
            repair_rules=REPAIR_RULES_A,
            schema_link_example=_LINK_EXAMPLE_A,
            kpi_rules=kpi_rules_a(),
        ),
        fewshot=FewShotProfile(
            dataset_path=config.FEWSHOT_DATASET_PATH,
            keywords=KEYWORDS_A,
        ),
        time_anchor=TimeAnchor(table="orders", column="order_date"),
    )


# ---------------------------------------------------------------------------
# ecommerce_B：第二公司电商库（独立业务语义，见本文件头部说明）
# ---------------------------------------------------------------------------

B_DB_PATH = config.PROJECT_ROOT / "db" / "ecommerce_v2.db"
B_FEWSHOT_PATH = (
    config.PROJECT_ROOT / "data" / "fewshot" / "ecommerce_v2_examples.json"
)

B_TABLE_NAMES: tuple[str, ...] = (
    "members",
    "departments",
    "items",
    "sales_orders",
    "order_lines",
)

B_TABLE_DESCRIPTIONS: dict[str, str] = {
    "members": "会员档案（连锁零售会员，含城市、等级、状态）",
    "departments": "商品类目（单层结构，无父子层级）",
    "items": "商品档案（挂在类目下，含吊牌价与在库状态）",
    "sales_orders": "会员销售订单（含订单状态、优惠券抵扣、配送费、应付金额；无城市冗余列）",
    "order_lines": "订单商品明细行（每个商品一行）",
}

B_COLUMN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "members": {
        "id": "会员 ID（主键）",
        "member_code": "会员编码（唯一）",
        "member_name": "会员姓名（唯一）",
        "city": "会员所在城市（收货城市口径）",
        "joined_on": "入会日期（ISO YYYY-MM-DD）",
        "tier": "会员等级：gold 金卡 / silver 银卡 / bronze 铜卡",
        "is_active": "会员状态（整数）：1 活跃 / 0 停用",
    },
    "departments": {
        "id": "类目 ID（主键）",
        "dept_name": "类目名称（唯一，单层无父子）",
    },
    "items": {
        "id": "商品 ID（主键）",
        "item_title": "商品名称（唯一）",
        "dept_id": "所属类目 ID",
        "list_price": "商品吊牌价（元）",
        "availability": "商品状态：in_stock 在库 / discontinued 停售",
    },
    "sales_orders": {
        "id": "订单 ID（主键）",
        "member_id": "下单会员 ID",
        "placed_on": "下单日期（ISO YYYY-MM-DD）",
        "order_state": "订单状态：pending/paid/shipped/completed/voided（作废）",
        "coupon_deduction": "优惠券抵扣金额（作废订单为 0）",
        "delivery_charge": "配送费（作废订单为 0）",
        "payment_due": "订单应付金额（作废订单为 0）",
    },
    "order_lines": {
        "id": "明细 ID（主键）",
        "sales_order_id": "所属订单 ID",
        "item_id": "商品 ID",
        "qty": "购买数量",
        "deal_price": "成交单价（元）",
        "line_total": "明细行金额（qty * deal_price）",
    },
}

B_GEN_RULES = (
    "【业务语义-金额字段】（口径唯一权威）\n"
    "- order_lines.line_total = 商品明细行金额（line-item amount）——「商品/类目/明细销售额、销售金额」"
    "以及未特别注明“实付”的「销售额」一律用此字段；\n"
    "- sales_orders.payment_due = 订单应付金额（明细合计 - 优惠券抵扣 + 配送费）——仅当题面明确说"
    "「实付金额 / 应付金额 / 客单价 / 平均实付 / 累计消费金额」时使用；\n"
    "- items.list_price = 商品吊牌价（“商品标价 / 平均售价”用此字段）；order_lines.deal_price = 成交单价快照"
    "（一般不用于销售额 / 平均售价）；\n"
    "- order_lines.qty = 购买件数（“销量 / 件数”聚合用）；\n"
    "- 城市维度「销售额」默认指商品明细口径（order_lines.line_total，与类目销售额一致）；"
    "若题面明确写「实付销售额」才用 sales_orders.payment_due；\n"
    "\n"
    "【业务语义-作废订单口径】（重要）\n"
    "- 本库订单作废状态为 sales_orders.order_state = 'voided'（不是 cancelled，库中不存在 cancelled 取值）；\n"
    "- “销售额 / 销量 / 客单价 / 类目销售 / 商品销售 / 实际收入”等实际销售类指标："
    "必须排除作废订单（WHERE so.order_state != 'voided'）；\n"
    "- “订单数 / 订单量 / 状态分布 / 各城市订单量 / 月度订单量 / 会员下单次数”"
    " 等结构统计（计数类）指标：不要排除作废订单；\n"
    "- 若问题按状态统计（如高/低金额订单数），金额口径部分排除 voided，但结构统计（总订单数）包含 voided；\n"
    "\n"
    "【业务语义-城市维度】（重要，与常见电商库不同）\n"
    "- sales_orders 表没有城市字段；城市/地区维度必须 JOIN members"
    "（sales_orders.member_id = members.id）取 members.city；\n"
    "- 城市取值为以下 15 个城市名原值，不加“市”后缀：\n"
    "  深圳、广州、杭州、成都、武汉、南京、西安、重庆、长沙、郑州、青岛、沈阳、苏州、宁波、合肥；\n"
    "\n"
    "【业务语义-枚举值】（按表分开，来自数据库 CHECK 约束，禁止跨表混用）\n"
    "- sales_orders.order_state ∈ {'pending', 'paid', 'shipped', 'completed', 'voided'}；\n"
    "- items.availability ∈ {'in_stock', 'discontinued'}（在库/停售）；\n"
    "- members.is_active ∈ {1, 0}（整数：1 活跃 / 0 停用，不是文本 active/inactive）；\n"
    "- members.tier ∈ {'gold', 'silver', 'bronze'}（会员等级）；\n"
    "\n"
    "【业务语义-聚合粒度】\n"
    "- “会员平均累计消费”：先按会员 GROUP BY 求和，再对这些“每会员累计值”求 AVG（两阶段聚合），"
    "不能直接用订单金额 AVG 代替；\n"
    "- “日均销售额”：分母 = 时间区间内实际有订单的不同日期数（COUNT(DISTINCT placed_on)），"
    "不要用固定天数硬除；\n"
    "- “占比”：分子分母必须同一统计口径与时间窗口；\n"
    "- 涉及 order_lines 的多表 JOIN 后统计「订单数」时必须用 COUNT(DISTINCT so.id)；"
    "订单级金额（payment_due）必须在订单粒度聚合（避免 JOIN 放大重复累计）；\n"
    "\n"
    "【业务语义-日期】\n"
    "- 日期字段为 ISO YYYY-MM-DD 字符串；季度分组用 substr(placed_on,6,2) + CASE，"
    "禁止使用不存在的 strftime 格式（如 %Q）；\n"
)

_B_LINK_RULES = (
    "【业务语义】\n"
    "- order_lines.line_total = 商品明细行金额；\n"
    "- sales_orders.payment_due = 订单应付金额（明细合计 - 优惠券抵扣 + 配送费）；\n"
    "- 城市维度必须 JOIN members 取 members.city（sales_orders 无城市字段）；\n"
    ' - “实际销售额 / 实际销量”类指标默认排除 sales_orders.order_state = "voided" 的订单；\n'
    "- 日期字段为 ISO YYYY-MM-DD 字符串格式。\n"
)

_B_LINK_EXAMPLE = (
    "【示例】用户问题：近30天销售额最高的商品有哪些？\n"
    '输出：{"tables": ["sales_orders", "order_lines", "items"], '
    '"columns": ["sales_orders.placed_on", "sales_orders.order_state", '
    '"sales_orders.payment_due", "order_lines.item_id", "order_lines.line_total", '
    '"items.id", "items.item_title"], '
    '"reasons": ["按 placed_on 筛选近30天订单", '
    '"payment_due/line_total 用于计算销售额，order_state 排除 voided 作废订单", '
    '"通过 order_lines 关联商品获取名称"], "confidence": 0.92}\n'
)

B_KEYWORDS: tuple[str, ...] = (
    "销售额",
    "销量",
    "订单",
    "会员",
    "城市",
    "商品",
    "类目",
    "排名",
    "趋势",
    "平均",
    "均价",
    "数量",
    "价格",
    "金额",
    "近30天",
    "近7天",
    "上月",
    "本月",
    "时间范围",
    "入会",
    "活跃",
    "在库",
    "占比",
    "作废",
    "Top",
    "客单",
    "复购",
)


def _ecommerce_b() -> DatabaseProfile:
    return DatabaseProfile(
        profile_id="ecommerce_B",
        db_type="sqlite",
        db_path=B_DB_PATH,
        domain_name="电商",
        schema=SchemaProfile(
            table_names=B_TABLE_NAMES,
            table_descriptions=B_TABLE_DESCRIPTIONS,
            column_descriptions=B_COLUMN_DESCRIPTIONS,
        ),
        business_rules=BusinessRulesProfile(
            generation_rules=B_GEN_RULES,
            schema_link_rules=_B_LINK_RULES,
            repair_rules=_B_LINK_RULES,
            schema_link_example=_B_LINK_EXAMPLE,
            kpi_rules=kpi_rules_b(),
        ),
        fewshot=FewShotProfile(
            dataset_path=B_FEWSHOT_PATH,
            keywords=B_KEYWORDS,
        ),
        time_anchor=TimeAnchor(table="sales_orders", column="placed_on"),
    )


# ---------------------------------------------------------------------------
# 注册表与解析入口
# ---------------------------------------------------------------------------

_PROFILE_FACTORIES = {
    "ecommerce_A": _ecommerce_a,
    "ecommerce_B": _ecommerce_b,
}

PROFILE_IDS: tuple[str, ...] = tuple(_PROFILE_FACTORIES)


def resolve_profile(profile_id: str | None = None) -> DatabaseProfile:
    """解析 Profile：显式参数 > 环境变量 DB_PROFILE > ecommerce_A。

    ecommerce_A 的路径沿用 config（ECOMMERCE_DB_PATH / FEWSHOT_DATASET_PATH
    环境变量仍然生效）；ecommerce_B 使用固定路径（db/ecommerce_v2.db）。
    """
    pid = (profile_id or os.getenv("DB_PROFILE") or "").strip() or DEFAULT_PROFILE_ID
    factory = _PROFILE_FACTORIES.get(pid)
    if factory is None:
        raise KeyError(
            f"未知 Database Profile: {pid}（可用: {', '.join(PROFILE_IDS)}）"
        )
    return factory()
