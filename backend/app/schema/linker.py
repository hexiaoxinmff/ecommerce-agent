"""Schema Linking：用户问题 -> LLMProvider -> 相关表/字段/理由/置信度。

职责边界：
- 只做 Schema Linking，不生成 SQL、不执行 SQL；
- 表/字段识别由 LLMProvider（当前 MimoProvider）完成；
- LLM 输出必须通过真实 Schema 复核（validation.py），
  非法 JSON 或非法 Schema 一律明确报错，禁止静默降级。

上层只能依赖 LLMProvider 抽象，禁止直接 import openai / Mimo API。
"""

import json
import re
from typing import TYPE_CHECKING

from app.llm.provider import LLMProvider, get_llm_provider
from app.schema.metadata import SchemaCatalog
from app.schema.validation import (
    SchemaLinkingInvalidError,
    validate_schema_link,
)
from app.schemas.schema_link import SchemaLinkResult

if TYPE_CHECKING:  # 仅类型标注；运行时由调用方注入，避免反向依赖
    from app.dbprofile.adapter import DatabaseAdapter

SYSTEM_PROMPT = (
    "你是电商智能数据分析 Agent 的 Schema Linking 组件。"
    "你的任务是根据用户的问题，从给定数据库 Schema 中识别最相关的表与字段。"
    "当前只做 Schema Linking，不生成 SQL，不执行 SQL，不修改数据库。"
)

# 业务语义（与 docs/database-schema.md 一致，禁止模型违背）
BUSINESS_RULES = (
    "【业务语义】\n"
    "- order_items.subtotal = 商品明细行金额；\n"
    "- orders.total_amount = 订单最终支付金额（明细合计 - 优惠 + 运费）；\n"
    ' - “实际销售额 / 实际销量”类指标默认排除 orders.status = "cancelled" 的订单；\n'
    "- 日期字段为 ISO YYYY-MM-DD 字符串格式。\n"
)

_LINK_INSTRUCTIONS = (
    "【任务要求】\n"
    "1. 只能使用上述 Schema 中的表与字段，禁止创造不存在的表或字段；\n"
    "2. 识别与用户问题直接相关的表和字段，每个字段用「表名.字段名」表示；\n"
    "3. reasons 用中文简要说明为什么需要这些表/字段（1~5 条）；\n"
    "4. confidence 为 0~1 之间的小数，表示该匹配的把握；\n"
    "5. 只输出一个严格 JSON 对象，不要输出任何解释、代码块标记或其他文字，格式：\n"
    '{\n  "tables": ["..."],\n  "columns": ["table.column", ...],\n'
    '  "reasons": ["...", ...],\n  "confidence": 0.9\n}\n'
    "6. 如果问题与电商数据库完全无关（如天气、闲聊），tables 与 columns 返回空数组，"
    "confidence 给出低值（如 0.1），reasons 说明未匹配原因。\n"
)

_EXAMPLE = (
    "【示例】用户问题：近30天销售额最高的商品有哪些？\n"
    '输出：{"tables": ["orders", "order_items", "products"], '
    '"columns": ["orders.order_date", "orders.status", "orders.total_amount", '
    '"order_items.product_id", "order_items.subtotal", "products.id", "products.name"], '
    '"reasons": ["按 order_date 筛选近30天订单", '
    '"total_amount/subtotal 用于计算销售额，status 排除 cancelled 订单", '
    '"通过 order_items 关联商品获取名称"], "confidence": 0.92}\n'
)


def _fence_strip(text: str) -> str:
    """去除 ```json ... ``` 围栏。"""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return fence.group(1).strip() if fence else text


def _extract_json(text: str) -> str | None:
    """提取最外层 { ... } 块；找不到返回 None。"""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return None


def _parse_llm_output(raw: str, catalog: SchemaCatalog, question: str) -> SchemaLinkResult:
    extracted = _extract_json(_fence_strip(raw))
    if extracted is None:
        raise SchemaLinkingInvalidError("LLM 输出中未找到 JSON")
    try:
        data = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise SchemaLinkingInvalidError("LLM 输出 JSON 解析失败") from exc
    if not isinstance(data, dict):
        raise SchemaLinkingInvalidError("LLM 输出不是 JSON 对象")

    tables_raw = data.get("tables")
    columns_raw = data.get("columns")
    reasons_raw = data.get("reasons")
    confidence_raw = data.get("confidence")

    if not isinstance(tables_raw, list) or not all(isinstance(t, str) for t in tables_raw):
        raise SchemaLinkingInvalidError("tables 字段必须是字符串数组")
    if not isinstance(columns_raw, list) or not all(
        isinstance(c, str) for c in columns_raw
    ):
        raise SchemaLinkingInvalidError("columns 字段必须是字符串数组")
    if not isinstance(reasons_raw, list) or not all(
        isinstance(r, str) for r in reasons_raw
    ):
        raise SchemaLinkingInvalidError("reasons 字段必须是字符串数组")

    try:
        confidence = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        raise SchemaLinkingInvalidError("confidence 必须是数字") from None

    tables, columns = validate_schema_link(tables_raw, columns_raw, confidence, catalog)

    return SchemaLinkResult(
        question=question,
        tables=tables,
        columns=columns,
        reasons=reasons_raw[:5],
        confidence=confidence if confidence is not None else 0.0,
    )


def build_link_prompt(
    catalog: SchemaCatalog,
    question: str,
    *,
    business_rules: str | None = None,
    example: str | None = None,
    appendix_rules: str | None = None,
) -> str:
    """构造 Schema Linking 用户侧 Prompt。

    Phase 13（跨数据库适配）：business_rules / example 允许由 Database
    Profile 注入当前数据库的业务口径与示例；缺省 None = 本模块常量
    （冻结基线逐字节不变）。

    Phase 15（P0-2）：appendix_rules 为 KPI 口径定义 —— Linking 必须与
    生成阶段共享同一口径（否则「销售额 → order_items」会在生成阶段被
    Schema 校验拒绝）；缺省 None = 不追加（冻结基线逐字节不变）。
    """
    rules = business_rules if business_rules is not None else BUSINESS_RULES
    example_text = example if example is not None else _EXAMPLE
    appendix = f"\n{appendix_rules}\n" if appendix_rules else ""
    return (
        "【数据库 Schema】（来自真实 SQLite 数据库，只允许使用这些表与字段）\n"
        f"{catalog.to_prompt_text()}\n"
        f"{rules}\n"
        f"{appendix}"
        f"{_LINK_INSTRUCTIONS}\n"
        f"{example_text}\n"
        f"【用户问题】{question}\n"
    )


class SchemaLinker:
    """Schema Linking 服务：通过 LLMProvider 识别相关表与字段。"""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        adapter: "DatabaseAdapter | None" = None,
        appendix_rules: str = "",
    ) -> None:
        self._provider = provider or get_llm_provider()
        # Phase 13：注入 DatabaseAdapter 后，Schema 目录 / 业务口径 / 示例
        # 全部来自 Profile；缺省 None = 原全局行为（默认业务库 + 本模块常量）。
        self._adapter = adapter
        # Phase 15（P0-2）：无 adapter 路径的 KPI 口径附录（default_components 注入）。
        self._appendix_rules = appendix_rules

    def _prompt_texts(self) -> tuple[str, str, str]:
        if self._adapter is None:
            return BUSINESS_RULES, _EXAMPLE, self._appendix_rules
        return (
            self._adapter.profile.business_rules.schema_link_rules,
            self._adapter.profile.business_rules.schema_link_example,
            self._adapter.profile.business_rules.kpi_rules,
        )

    def link(self, question: str) -> SchemaLinkResult:
        """执行 Schema Linking，返回经过真实 Schema 复核的结构化结果。

        Raises:
            SchemaLinkingInvalidError: 输入为空 / LLM 输出非法。
            LLMError: Provider 调用失败（原样透传，由上层路由映射）。
        """
        if not question or not question.strip():
            raise SchemaLinkingInvalidError("question 不能为空")
        if self._adapter is not None:
            catalog = self._adapter.get_cached_catalog()
        else:
            catalog = SchemaCatalog.from_database()
        business_rules, example, appendix = self._prompt_texts()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_link_prompt(
                catalog,
                question,
                business_rules=business_rules,
                example=example,
                appendix_rules=appendix or None,
            )},
        ]
        raw = self._provider.generate(messages, temperature=0.0)
        return _parse_llm_output(raw, catalog, question)