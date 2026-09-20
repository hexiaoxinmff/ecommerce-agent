"""Schema Metadata / Linking / Validation 单元测试（mock LLMProvider，不真实调用 Mimo）。

覆盖：
- SchemaCatalog 来自真实数据库（5 张表，字段真实存在）；
- Prompt 文本包含 Schema、业务语义、cancelled 规则；
- 正常问题链接成功（tables/columns 复核通过）；
- JSON 围栏解析、非 JSON、缺字段、confidence 越界；
- 非法表（payments）/ 非法字段（orders.xxx）/ 字段表不在 tables -> 拒绝；
- 无关问题（空匹配）正常返回空结果；
- Provider 异常原样透传（LLMError）。
"""

import json

import pytest

from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
)
from app.schema.linker import SchemaLinker, build_link_prompt
from app.schema.metadata import SchemaCatalog
from app.schema.validation import SchemaLinkingInvalidError

EXPECTED_TABLES = ("users", "categories", "products", "orders", "order_items")

VALID_JSON = json.dumps(
    {
        "tables": ["orders", "order_items", "products"],
        "columns": [
            "orders.order_date",
            "orders.status",
            "orders.total_amount",
            "order_items.product_id",
            "order_items.subtotal",
            "products.id",
            "products.name",
        ],
        "reasons": [
            "按 order_date 筛选近30天订单",
            "total_amount/subtotal 计算销售额，status 排除 cancelled 订单",
        ],
        "confidence": 0.92,
    },
    ensure_ascii=False,
)


class _FakeProvider:
    """固定输出的模拟 Provider；仅用于逻辑测试，不发起网络请求。"""

    name = "mimo"
    model = "mimo-v2.5-pro"

    def __init__(self, output: str, error: Exception | None = None) -> None:
        self._output = output
        self._error = error
        self.last_messages: list[dict[str, str]] | None = None

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        self.last_messages = messages
        if self._error is not None:
            raise self._error
        return self._output


def _linker_with(output: str):
    return SchemaLinker(provider=_FakeProvider(output))


# ---------- SchemaCatalog ----------


def test_catalog_from_database_has_real_tables() -> None:
    catalog = SchemaCatalog.from_database()
    assert catalog.table_names == EXPECTED_TABLES


def test_catalog_columns_match_real_schema() -> None:
    catalog = SchemaCatalog.from_database()
    for table, columns in {
        "users": ["id", "username", "email", "region", "register_date", "status"],
        "categories": ["id", "name", "parent_id"],
        "products": ["id", "name", "category_id", "price", "status"],
        "orders": [
            "id",
            "user_id",
            "order_date",
            "status",
            "region",
            "discount_amount",
            "shipping_fee",
            "total_amount",
        ],
        "order_items": [
            "id",
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
            "subtotal",
        ],
    }.items():
        meta = catalog.get_table(table)
        assert meta is not None
        assert [c.name for c in meta.columns] == columns


def test_catalog_rejects_nonexistent_column() -> None:
    catalog = SchemaCatalog.from_database()
    assert not catalog.has_table("payments")
    assert not catalog.has_column("orders", "xxx")


def test_build_link_prompt_contains_schema_and_rules() -> None:
    catalog = SchemaCatalog.from_database()
    prompt = build_link_prompt(catalog, "近30天销售额最高的商品有哪些")
    assert "orders" in prompt and "total_amount" in prompt
    assert "cancelled" in prompt  # 业务语义必须出现在 Prompt 中
    assert "禁止创造" in prompt


# ---------- 正常链接 ----------


def test_link_valid_question() -> None:
    result = _linker_with(VALID_JSON).link("近30天销售额最高的商品有哪些？")
    assert result.question == "近30天销售额最高的商品有哪些？"
    assert set(result.tables) == {"orders", "order_items", "products"}
    assert all("." in c for c in result.columns)
    assert result.reasons
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence == 0.92


def test_link_deduplicates_tables_and_columns() -> None:
    payload = json.dumps(
        {
            "tables": ["orders", "orders", "products"],
            "columns": ["orders.order_date", "orders.order_date", "products.name"],
            "reasons": ["r1"],
            "confidence": 0.8,
        },
        ensure_ascii=False,
    )
    result = _linker_with(payload).link("问题")
    assert result.tables == ["orders", "products"]
    assert result.columns == ["orders.order_date", "products.name"]


def test_link_accepts_json_fence() -> None:
    result = _linker_with(f"```json\n{VALID_JSON}\n```").link("问题")
    assert result.tables == ["orders", "order_items", "products"]


def test_link_out_of_domain_returns_empty() -> None:
    payload = json.dumps(
        {
            "tables": [],
            "columns": [],
            "reasons": ["问题与电商数据库无关"],
            "confidence": 0.1,
        },
        ensure_ascii=False,
    )
    result = _linker_with(payload).link("今天天气怎么样？")
    assert result.tables == []
    assert result.columns == []
    assert result.confidence == 0.1


# ---------- 非法输出 ----------


def test_non_json_output_rejected() -> None:
    with pytest.raises(SchemaLinkingInvalidError):
        _linker_with("抱歉，我无法回答这个问题。").link("问题")


def test_empty_output_rejected() -> None:
    with pytest.raises(SchemaLinkingInvalidError):
        _linker_with("").link("问题")


def test_missing_fields_rejected() -> None:
    with pytest.raises(SchemaLinkingInvalidError):
        _linker_with('{"tables": ["orders"]}').link("问题")


def test_invalid_table_rejected() -> None:
    payload = json.dumps(
        {
            "tables": ["orders", "payments"],
            "columns": ["orders.total_amount"],
            "reasons": ["r"],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
    with pytest.raises(SchemaLinkingInvalidError, match="payments"):
        _linker_with(payload).link("问题")


def test_invalid_column_rejected() -> None:
    payload = json.dumps(
        {
            "tables": ["orders"],
            "columns": ["orders.xxx", "orders.total_amount"],
            "reasons": ["r"],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
    with pytest.raises(SchemaLinkingInvalidError, match="orders.xxx"):
        _linker_with(payload).link("问题")


def test_column_format_without_dot_rejected() -> None:
    payload = json.dumps(
        {
            "tables": ["orders"],
            "columns": ["total_amount"],
            "reasons": ["r"],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
    with pytest.raises(SchemaLinkingInvalidError):
        _linker_with(payload).link("问题")


def test_column_table_not_in_tables_rejected() -> None:
    payload = json.dumps(
        {
            "tables": ["orders"],
            "columns": ["products.name"],
            "reasons": ["r"],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
    with pytest.raises(SchemaLinkingInvalidError, match="products"):
        _linker_with(payload).link("问题")


@pytest.mark.parametrize("bad_confidence", [1.5, -0.2, "高", None])
def test_confidence_out_of_range_rejected(bad_confidence) -> None:
    payload = json.dumps(
        {
            "tables": ["orders"],
            "columns": ["orders.total_amount"],
            "reasons": ["r"],
            "confidence": bad_confidence,
        },
        ensure_ascii=False,
    )
    with pytest.raises(SchemaLinkingInvalidError):
        _linker_with(payload).link("问题")


# ---------- Provider 异常透传 ----------


def test_provider_auth_error_propagates() -> None:
    provider = _FakeProvider("", error=LLMAuthenticationError("auth failed"))
    with pytest.raises(LLMAuthenticationError):
        SchemaLinker(provider=provider).link("问题")


def test_provider_key_missing_propagates() -> None:
    provider = _FakeProvider(
        "", error=LLMApiKeyNotConfiguredError("Mimo API key is not configured")
    )
    with pytest.raises(LLMApiKeyNotConfiguredError):
        SchemaLinker(provider=provider).link("问题")


def test_empty_question_rejected() -> None:
    with pytest.raises(SchemaLinkingInvalidError):
        _linker_with(VALID_JSON).link("   ")