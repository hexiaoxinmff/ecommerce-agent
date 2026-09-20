"""SQL Repair Prompt 构建。

Repair 输入上下文（缺一不可）：
用户问题 + 原始 SQL + SQLite 错误（已清洗）+ Schema Linking（允许对象）
+ 当前真实 Schema + Few-shot 参考。

核心原则：Repair ≠ 重新生成。只修复导致执行失败的具体问题，
尽可能保持原始 SQL 其余部分不变。
"""

from app.fewshot.models import FewShotResult
from app.schema.metadata import SchemaCatalog

SYSTEM_PROMPT = (
    "你是电商智能数据分析 Agent 的 SQL Repair 组件。"
    "你的任务：修复一条已经生成但执行失败的 SQLite SQL。"
    "只做修复，不执行 SQL。"
)

BUSINESS_RULES = (
    "【业务语义】\n"
    "- order_items.subtotal = 商品明细行金额；\n"
    "- orders.total_amount = 订单最终支付金额（明细合计 - 优惠 + 运费）；\n"
    ' - “实际销售额 / 实际销量”类指标默认排除 orders.status = "cancelled" 的订单；\n'
    "- 日期字段为 ISO YYYY-MM-DD 字符串格式。\n"
)

_CONSTRAINTS = (
    "【硬性约束】\n"
    "1. 保留用户原始分析意图；\n"
    "2. 只允许使用「Schema Linking 结果」提供的表与字段，不得创造表/字段；\n"
    "3. 只允许 SELECT / WITH；禁止 INSERT / UPDATE / DELETE / DROP / ALTER / "
    "CREATE / REPLACE / TRUNCATE / PRAGMA；\n"
    "4. 不得生成多语句 SQL；\n"
    "5. 不执行 SQL；\n"
    "6. 只输出一个严格 JSON 对象，不要把 SQL 放入代码块。\n"
)

_REPAIR_PRINCIPLE = (
    "【修复原则（重要）】\n"
    "原始 SQL 应尽可能保持不变，只修复导致执行失败的具体问题（如错误的表名、"
    "字段名）。不要换一种完全不同的分析方案。\n"
)


def format_schema_linking(tables: list[str], columns: list[str]) -> str:
    lines = ["相关表："] + [f"  - {t}" for t in tables]
    if columns:
        lines.append("相关字段：")
        lines.extend(f"  - {c}" for c in columns)
    return "\n".join(lines)


def format_fewshot(fs_result: FewShotResult) -> str:
    if not fs_result.matches:
        return "（无匹配 Few-shot 示例）"
    blocks = []
    for i, match in enumerate(fs_result.matches, start=1):
        blocks.append(
            f"Example {i}: 问题：{match.question}  SQL：{match.sql}"
        )
    return "\n".join(blocks)


def build_repair_prompt(
    request_sql: str,
    error_message: str,
    question: str,
    tables: list[str],
    columns: list[str],
    catalog: SchemaCatalog,
    fewshot_text: str,
) -> str:
    return (
        f"【用户问题】{question}\n\n"
        f"【原始 SQL】\n{request_sql}\n\n"
        f"【SQLite 执行错误】\n{error_message}\n\n"
        f"【Schema Linking 结果】\n{format_schema_linking(tables, columns)}\n\n"
        f"【当前真实 Schema（只可使用这些表与字段）】\n{catalog.to_prompt_text()}\n\n"
        f"【Few-shot 参考】\n{fewshot_text}\n\n"
        f"{BUSINESS_RULES}\n"
        f"{_REPAIR_PRINCIPLE}\n"
        f"{_CONSTRAINTS}\n"
        '【输出】严格 JSON：{"repaired_sql": "...", "repair_reason": "..."}\n'
    )