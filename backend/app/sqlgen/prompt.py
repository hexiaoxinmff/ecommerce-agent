"""SQL Generation Prompt 构建。

将用户问题 + Schema Linking 结果 + Few-shot Examples（完整内容）
拼接为给 LLM 的 Prompt；要求模型严格输出 JSON，不放 SQL 代码块。

专项规则版本（Task 14.2，通过环境变量 SQLGEN_EXTRA_RULES 启用，
逗号分隔，如 "E4,E6"；缺省为空 = SQLGENERATOR_PROMPT_V1.1 基础规则）：
    E4  Output Contract  （输出列契约）
    E5  Metric Semantics （金额/销售口径）
    E6  Nested Aggregation（分层聚合）
    E7  CASE Boundary     （分段边界）

Task 38（E8）：条件性统计实体 / 驱动表约束。
默认**关闭** —— 关闭时 Prompt 与冻结基线逐字节相同。
启用后，仅当题目被识别为「按行为分档统计实体」时才追加约束段；
其余题目即使 E8 开启也不注入（条件性局部生效）。

Task 44（E9/E10/E11）：条件性语义契约（修复 Task 43 已确证的生成层失败机制）。
同样默认**关闭**，且同样是**条件性**注入 —— 只有题目被确定性识别为对应
场景时才追加，其余题目即使 flag 打开也不注入：

    E9  Global Scope      （全局口径不得继承外层时间过滤）  —— E-0065
    E10 Ratio Direction   （ratio 分子/分母方向必须先确定） —— E-0075
    E11 Ranking Tiebreak  （Top-N 必须含确定性破平键）      —— E-0098

E4（Output Contract）在 Task 44 中**增强 wording**（新增「实体维度契约」条款），
flag 与注入时机不变。
"""

import os

from app.fewshot.models import FewShotResult
from app.schemas.schema_link import SchemaLinkResult
from app.sqlgen.date_window import detect_date_window
from app.sqlgen.entity_constraint import detect_analysis_entity_constraint
from app.sqlgen.semantic_contracts import (
    detect_global_scope,
    detect_ranking_tiebreak,
    detect_ratio_direction,
)

SYSTEM_PROMPT = (
    "你是电商智能数据分析 Agent 的 SQL Generator。"
    "任务：根据用户问题、Schema Linking 结果与 Few-shot Examples，"
    "生成一条只读的 SQLite SQL。只生成 SQL，不执行 SQL。"
)


def system_prompt_for(domain: str = "电商") -> str:
    """按 Profile 领域词生成 System Prompt（Phase 13）。

    domain 为 "电商"（或未指定）时返回值与 SYSTEM_PROMPT 逐字节相同。
    """
    if not domain or domain == "电商":
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT.replace("电商", domain, 1)

# 业务语义（与 docs/database-schema.md 保持一致）
# 版本：SQLGENERATOR_PROMPT_V1.3（Task 14.3：枚举分表 + 金额口径统一；相对 V1.1 无功能回退）
BUSINESS_RULES = (
    "【业务语义-金额字段】（口径唯一权威）\n"
    "- order_items.subtotal = 商品明细行金额（line-item amount）——「商品/类目/明细销售额、销售金额」"
    "以及未特别注明“实付”的「销售额」一律用此字段；\n"
    "- orders.total_amount = 订单最终支付金额（明细合计 - 优惠 + 运费）——仅当题面明确说"
    "「实付金额 / 订单支付金额 / 客单价 / 平均实付 / 累计消费金额」时使用；\n"
    "- products.price = 商品当前售价（“商品标价 / 平均售价”用此字段）；order_items.unit_price = 成交单价快照"
    "（一般不用于销售额 / 平均售价）；\n"
    "- order_items.quantity = 购买件数（“销量 / 件数”聚合用）；\n"
    "- 地区维度「销售额」默认指商品明细口径（order_items.subtotal，与分类销售额一致）；"
    "若题面明确写「实付销售额」才用 orders.total_amount；\n"
    "\n"
    "【业务语义-取消订单口径】（重要）\n"
    "- “销售额 / 销量 / 客单价 / 类目销售 / 商品销售 / 实际收入”等实际销售类指标："
    "必须排除取消订单（WHERE o.status != 'cancelled'）；\n"
    "- “订单数 / 订单量 / 状态分布 / 各地区订单量 / 月度订单量 / 上下半年订单量比 / 用户下单次数”"
    " 等结构统计（计数类）指标：不要排除取消订单；\n"
    "- 若问题按状态统计（如高/低金额订单数），金额口径部分排除 cancelled，但结构统计（总订单数）包含 cancelled；\n"
    "\n"
    "【业务语义-枚举值】（按表分开，来自数据库 CHECK 约束，禁止跨表混用）\n"
    "- orders.status ∈ {'pending', 'paid', 'shipped', 'completed', 'cancelled'}；\n"
    "- products.status ∈ {'on_sale', 'off_sale'}（商品在售/下架）；\n"
    "- users.status ∈ {'active', 'inactive'}（用户活跃/停用）；\n"
    "- users.region 与 orders.region：如下 15 个省级地区原值，不加“省/市”后缀："
    "广东、江苏、浙江、山东、北京、上海、四川、河南、福建、湖北、辽宁、湖南、安徽、陕西、重庆；\n"
    "\n"
    "【业务语义-聚合粒度】\n"
    "- “用户平均累计消费”：先按用户 GROUP BY 求和，再对这些“每用户累计值”求 AVG（两阶段聚合），"
    "不能直接用订单金额 AVG 代替；\n"
    "- “日均销售额”：分母 = 时间区间内实际有订单的不同日期数（COUNT(DISTINCT order_date)），"
    "不要用固定天数硬除；\n"
    "- “占比”：分子分母必须同一统计口径与时间窗口；\n"
    "- 涉及 order_items 的多表 JOIN 后统计「订单数」时必须用 COUNT(DISTINCT o.id)；"
    "订单级金额（total_amount）必须在订单粒度聚合（避免 JOIN 放大重复累计）；\n"
    "\n"
    "【业务语义-日期】\n"
    "- 日期字段为 ISO YYYY-MM-DD 字符串；季度分组用 substr(order_date,6,2) + CASE，"
    "禁止使用不存在的 strftime 格式（如 %Q）；\n"
)

# ---------------- Task 14.2 专项规则（各自独立，按环境变量选择性启用） ----------------

# E4: Output Contract（专项 A：E-0082/E-0083/E-0090）
# Task 44 增强：新增第 5 条「实体维度契约」（靶题 E-0082：数值正确但丢了分类名列）。
# 该条款刻意带**反例例外**，避免把「同表列直接限定的标量比值」也强行加列
# （反例 E-0081「广东省的用户占全部用户的比例」gold 只有 1 列）。
OUTPUT_CONTRACT_RULES = (
    "【输出列契约】（重要）\n"
    "1. 生成 SQL 前先枚举问题要求返回的所有信息，SELECT 的每一列都必须对应用户问题中要求给的一项字段；\n"
    "2. 数量占比/比例题：若问题要求「给出分类与占比」，必须同时输出「分类名称」与「占比」两列；\n"
    "3. 结构统计题若问题注明「含取消订单的结构统计 / 总订单数」，必须额外输出总计数列（如 COUNT(*) AS total_cnt）；\n"
    "4. SELECT 列数必须与问题要求完全匹配，禁止遗漏列（列数缺失会导致结果无法对齐判错）。\n"
    "5. 实体维度契约：当题目要求的比例/指标针对某个**需要 JOIN 维度表才能限定**的实体时"
    "（如「某类别」的名称来自 categories、「某商品」来自 products、「某用户」来自 users），"
    "SELECT 必须同时输出该实体的标识列（名称或 ID）与指标列；"
    "不得用 SUM(CASE WHEN 维度列 = '常量' THEN …) 把维度折叠掉、只返回一个标量；\n"
    "6. 第 5 条的反例（不适用）：实体由**同一张表的列**直接限定、且题目只要求一个标量比值时"
    "（如 users.region = '广东' 的占比），不要凭空增加实体列 —— 多输出一列同样会判错。\n"
)

# E5: Metric Semantics（专项 B：E-0077/E-0097）
METRIC_SEMANTICS_RULES = (
    "【金额/销售口径-字段选择决策】\n"
    "- 「商品/类目销售额、销售金额、明细销售额」→ 用 order_items.subtotal；\n"
    "- 「销量、件数、购买数量」→ 用 order_items.quantity；\n"
    "- 「订单实付金额、客单价、订单金额、用户消费额」→ 用 orders.total_amount；\n"
    "- 「商品标价、商品售价、平均售价」→ 用 products.price；\n"
    "- 「成交单价快照」→ 用 order_items.unit_price（一般不用于销售额/平均售价）；\n"
    "- 涉及 order_items 的多表 JOIN 后统计「订单数」时，必须用 COUNT(DISTINCT o.id) 防止 JOIN 放大重复计数；\n"
    "- 「销售额」类指标一律排除取消订单（WHERE o.status != 'cancelled'）。\n"
)

# E6: Nested Aggregation（专项 C：E-0086/E-0095）
NESTED_AGGREGATION_RULES = (
    "【分层聚合思维】复杂多阶段题目按以下步骤组织，最终只输出一条合法 SQL：\n"
    "1. 最终分析实体是什么（用户/订单/地区/分类…）？\n"
    "2. 第一层聚合（先 GROUP BY 实体并求和/计数）时，若涉及多表 JOIN（如 orders×order_items），"
    "计数用 COUNT(DISTINCT 主键) 防止一对多行数膨胀、求和用正确的明细金额字段；\n"
    "3. 第二层再对「第一层聚合法结果」求 AVG/比较（如用户平均累计消费 = 先按用户求和再求平均）；\n"
    "4. 题目中显式给出的过滤阈值（如「组合金额 > 30000」）必须作为 HAVING/WHERE 保留在 SQL 中，"
    "不能省略（否则过滤后平均基准会失真）。\n"
)

# E7: CASE Boundary（专项 D：E-0057）
CASE_BOUNDARY_RULES = (
    "【CASE WHEN 分段边界】\n"
    "- 先定义各区间与边界包含关系（是否含端点），相邻区间不得重叠；\n"
    "- 区间必须覆盖全部取值域，从可能的最小值（如 0 或 1）开始，不要漏掉下界；\n"
    "- 建议用连续比较（如 cnt <= 3 / cnt <= 10 / ELSE）确保边界连续覆盖，"
    "避免 BETWEEN 使 0 或边值落入错误的 ELSE 分支；\n"
    "- 每个值必须且只能落入一个分段；\n"
    "- 分段标签与输出列名保持业务含义清晰。\n"
)

# 环境变量 → 规则段映射
_EXTRA_RULE_TABLE = {
    "E4": OUTPUT_CONTRACT_RULES,
    "E5": METRIC_SEMANTICS_RULES,
    "E6": NESTED_AGGREGATION_RULES,
    "E7": CASE_BOUNDARY_RULES,
}


def enabled_extra_rules() -> str:
    """返回按 SQLGEN_EXTRA_RULES 启用的规则段文本（FEWSHOT 实验通过环境变量控制）。"""
    raw = os.getenv("SQLGEN_EXTRA_RULES", "").strip()
    if not raw:
        return ""
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    return "\n".join(_EXTRA_RULE_TABLE[p] for p in parts if p in _EXTRA_RULE_TABLE)

_OUTPUT_RULES = (
    "【输出要求】\n"
    "1. 只输出一个严格 JSON 对象，不要输出任何解释性文字；\n"
    "2. SQL 不要放在 ```sql 代码块中，直接作为 JSON 的 sql 字段值；\n"
    '3. JSON 结构：{"sql": "...", "explanation": "...", '
    '"tables": ["..."], "columns": ["table.column", ...]}；\n'
    "4. explanation 用中文一句话说明生成思路。\n"
)

_CONSTRAINTS = (
    "【硬性约束】\n"
    "1. 只能使用下面「Schema Linking 结果」中提供的表和字段，禁止创造不存在的表或字段；\n"
    "2. SQL 必须适用于 SQLite，只允许只读 SQL；\n"
    "3. 禁止 INSERT / UPDATE / DELETE / DROP / ALTER / CREATE / REPLACE / TRUNCATE；\n"
    "4. 禁止多语句 SQL（只允许一条语句）；\n"
    "5. 不执行 SQL；\n"
)


def entity_constraint_block(question: str) -> str:
    """Task 38：按题目条件产出统计实体约束段。

    仅当 SQLGEN_EXTRA_RULES 含 "E8" **且** 题目被识别为
    「按行为分档统计实体」时返回约束文本；否则返回空串。

    默认（未设置 E8）恒返回空串 —— 保证 Prompt 与冻结基线逐字节一致。
    """
    raw = os.getenv("SQLGEN_EXTRA_RULES", "").strip()
    if not raw:
        return ""
    flags = {p.strip().upper() for p in raw.split(",") if p.strip()}
    if "E8" not in flags:
        return ""
    constraint = detect_analysis_entity_constraint(question)
    if constraint is None:
        return ""
    return constraint.to_prompt_block()


# ---------------- Task 44：条件性语义契约（E9 / E10 / E11） ----------------


def _enabled_flags() -> set[str]:
    """解析当前 SQLGEN_EXTRA_RULES 的 flag 集合（空集 = 全部关闭）。"""
    raw = os.getenv("SQLGEN_EXTRA_RULES", "").strip()
    if not raw:
        return set()
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def global_scope_block(question: str) -> str:
    """E9：全局口径 / 参照基准约束段（默认关闭，条件性注入）。"""
    if "E9" not in _enabled_flags():
        return ""
    contract = detect_global_scope(question)
    return "" if contract is None else contract.to_prompt_block()


def ratio_direction_block(question: str) -> str:
    """E10：比值方向契约段（默认关闭，条件性注入）。"""
    if "E10" not in _enabled_flags():
        return ""
    contract = detect_ratio_direction(question)
    return "" if contract is None else contract.to_prompt_block()


def ranking_tiebreak_block(question: str) -> str:
    """E11：Top-N 确定性排序契约段（默认关闭，条件性注入）。"""
    if "E11" not in _enabled_flags():
        return ""
    contract = detect_ranking_tiebreak(question)
    return "" if contract is None else contract.to_prompt_block()


def semantic_contract_block(question: str) -> str:
    """按 E9 -> E10 -> E11 固定顺序拼接已启用且已命中的语义契约段。

    全部未启用或全部未命中时返回空串 ⇒ build_prompt 与基线逐字节相同。
    """
    blocks = [
        global_scope_block(question),
        ratio_direction_block(question),
        ranking_tiebreak_block(question),
    ]
    return "\n".join(b for b in blocks if b)


# ---------------- Task 60：E12 时间窗口语义保持（条件性注入，默认关闭） ----------------

def date_window_block(question: str) -> str:
    """E12：时间窗口语义保持契约段（默认关闭，条件性注入）。

    仅当 `SQLGEN_EXTRA_RULES` 含 `E12` **且**题目被确定性识别为
    「已给出时间范围」时返回约束文本；否则返回空串。

    未开启 E12 时恒返回空串 ⇒ `build_prompt` 与冻结基线逐字节相同。
    本函数与 E9/E10/E11 完全独立，不修改任何既有语义契约。
    """
    if "E12" not in _enabled_flags():
        return ""
    contract = detect_date_window(question)
    return "" if contract is None else contract.to_prompt_block()


def format_schema_linking(link_result: SchemaLinkResult) -> str:
    lines = [f"相关表：\n{chr(10).join('  - ' + t for t in link_result.tables)}"]
    if link_result.columns:
        lines.append(
            "相关字段：\n" + "\n".join("  - " + c for c in link_result.columns)
        )
    return "\n".join(lines)


def format_fewshot(fs_result: FewShotResult) -> str:
    if not fs_result.matches:
        return "（无匹配的 Few-shot 示例）"
    blocks = []
    for index, match in enumerate(fs_result.matches, start=1):
        blocks.append(
            f"Example {index}（example_id: {match.example_id}）\n"
            f"问题：{match.question}\n"
            f"SQL：{match.sql}\n"
            f"说明：{match.explanation}"
        )
    return "\n\n".join(blocks)


def build_prompt(
    question: str,
    link_result: SchemaLinkResult,
    fs_result: FewShotResult,
    *,
    business_rules: str | None = None,
    appendix_rules: str | None = None,
) -> str:
    """构建 SQL 生成 Prompt。

    Phase 13（跨数据库适配）：business_rules 允许由 Database Profile 注入
    当前数据库的业务口径文本；缺省 None = 使用本模块 BUSINESS_RULES
    （冻结基线逐字节不变）。

    Phase 15（P0-1/P0-2）：appendix_rules 为运行时附录（KPI 口径定义 +
    数据时效契约），渲染在业务口径之后；缺省 None = 不追加（冻结基线
    逐字节不变）。
    """
    rules = business_rules if business_rules is not None else BUSINESS_RULES
    appendix = f"{appendix_rules}\n" if appendix_rules else ""
    extra = enabled_extra_rules()
    extra_block = f"{extra}\n\n" if extra else ""
    # Task 38：条件性统计实体约束（默认关闭，仅 E8 开启且命中目标场景时非空）
    entity_block = entity_constraint_block(question)
    entity_text = f"{entity_block}\n" if entity_block else ""
    # Task 44：条件性语义契约（默认关闭，仅对应 flag 开启且命中目标场景时非空）
    semantic_block = semantic_contract_block(question)
    semantic_text = f"{semantic_block}\n" if semantic_block else ""
    # Task 60：条件性时间窗口契约（默认关闭，仅 E12 开启且题目已给出时间范围时非空）
    date_block = date_window_block(question)
    date_text = f"{date_block}\n" if date_block else ""
    return (
        f"【用户问题】{question}\n\n"
        f"【Schema Linking 结果】\n{format_schema_linking(link_result)}\n\n"
        f"【Few-shot Examples】\n{format_fewshot(fs_result)}\n\n"
        f"{rules}\n"
        f"{appendix}"
        f"{extra_block}"
        f"{entity_text}"
        f"{semantic_text}"
        f"{date_text}"
        f"{_CONSTRAINTS}\n"
        f"{_OUTPUT_RULES}\n"
        f"【请生成】针对用户问题生成唯一一条只读 SQLite SQL。\n"
    )