"""SQL Generator 单元测试（mock SchemaLinker / FewShotRetriever / LLMProvider，不真实调用 Mimo）。

覆盖：正常生成、非法 SQL（DELETE/DROP/UPDATE/多语句）拒绝、
非法表（payments）拒绝、非法 JSON 拒绝、代码块可解析、
SQL 解析（SELECT / WITH）成功、SQL 表引用越界拒绝、
columns 格式与字段校验、question 原始保留。
"""

import json

import pytest

from app.fewshot.models import FewShotMatch, FewShotResult
from app.schemas.schema_link import SchemaLinkResult
from app.sqlgen.errors import (
    SQLGenOutputInvalidError,
    SQLGenSchemaMismatchError,
    SQLTableMismatchError,
    SQLUnsafeError,
)
from app.sqlgen.generator import SQLGenerator
from app.sqlgen.safety import check_sql_safety, extract_referenced_tables

VALID_LINK = SchemaLinkResult(
    question="近30天销售额最高的商品有哪些？",
    tables=["orders", "order_items", "products"],
    columns=[
        "orders.order_date",
        "orders.status",
        "order_items.product_id",
        "order_items.subtotal",
        "products.id",
        "products.name",
    ],
    reasons=["按 order_date 筛选近30天", "计算销售额并排除 cancelled 订单"],
    confidence=0.9,
)

VALID_FEWSHOT = FewShotResult(
    question="近30天销售额最高的商品有哪些？",
    matches=[
        FewShotMatch(
            example_id="ex_001",
            score=0.88,
            question="近30天销售额最高的商品有哪些？",
            scenario="product_sales_ranking",
            tables=["orders", "order_items", "products"],
            columns=["orders.order_date"],
            sql="SELECT 1",
            explanation="按商品汇总销售额",
        ),
        FewShotMatch(
            example_id="ex_006",
            score=0.4,
            question="销量最高的商品 Top 5 是哪些？",
            scenario="product_volume_ranking",
            tables=["orders", "order_items", "products"],
            columns=["orders.status"],
            sql="SELECT 1",
            explanation="按商品汇总销量",
        ),
        FewShotMatch(
            example_id="ex_003",
            score=0.36,
            question="哪个商品类别销售额最高？",
            scenario="category_sales_ranking",
            tables=["orders", "order_items", "products", "categories"],
            columns=["orders.status"],
            sql="SELECT 1",
            explanation="按类别汇总销售额",
        ),
    ],
)

VALID_SQL = (
    "SELECT p.name AS product_name, ROUND(SUM(oi.subtotal), 2) AS total_sales "
    "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "JOIN products p ON p.id = oi.product_id "
    "WHERE o.order_date >= date('now', '-30 day') AND o.status != 'cancelled' "
    "GROUP BY p.id ORDER BY total_sales DESC"
)


class _FakeProvider:
    name = "mimo"
    model = "mimo-v2.5-pro"

    def __init__(self, output: str = "", error: Exception | None = None):
        self._output = output
        self._error = error
        self.last_messages: list[dict[str, str]] | None = None

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        self.last_messages = messages
        if self._error is not None:
            raise self._error
        return self._output


class _FakeLinker:
    def __init__(self, result: SchemaLinkResult):
        self._result = result

    def link(self, question: str) -> SchemaLinkResult:
        return self._result


class _FakeRetriever:
    def __init__(self, result: FewShotResult):
        self._result = result

    def retrieve(self, query) -> FewShotResult:
        return self._result


def _payload(sql: str = VALID_SQL, tables=None, columns=None, explanation="按商品汇总销售额"):
    return json.dumps(
        {
            "sql": sql,
            "explanation": explanation,
            "tables": tables if tables is not None else VALID_LINK.tables,
            "columns": columns if columns is not None else VALID_LINK.columns,
        },
        ensure_ascii=False,
    )


def _generator(output: str | None = None) -> SQLGenerator:
    return SQLGenerator(
        provider=_FakeProvider(output if output is not None else _payload()),
        schema_linker=_FakeLinker(VALID_LINK),
        fewshot_retriever=_FakeRetriever(VALID_FEWSHOT),
    )


def test_generate_valid_sql() -> None:
    result = _generator().generate("近30天销售额最高的商品有哪些？")
    assert result.question == "近30天销售额最高的商品有哪些？"  # 原始问题保留
    assert result.sql.strip() != ""
    assert result.tables == VALID_LINK.tables
    assert result.columns == VALID_LINK.columns
    assert result.fewshot_examples == ["ex_001", "ex_006", "ex_003"]
    assert result.explanation == "按商品汇总销售额"


def test_generate_accepts_json_fence() -> None:
    wrapped = f"```json\n{_payload()}\n```"
    result = _generator(wrapped).generate("问题")
    assert result.sql.strip() != ""


# ---------- 非法 SQL ----------


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "UPDATE orders SET total_amount = 0",
        "SELECT 1; DELETE FROM orders",
        "INSERT INTO orders (id) VALUES (1)",
        "ALTER TABLE orders ADD COLUMN x INTEGER",
        "CREATE TABLE x (id INTEGER)",
        "PRAGMA journal_mode=WAL",
    ],
)
def test_unsafe_sql_rejected(bad_sql: str) -> None:
    with pytest.raises(SQLUnsafeError):
        _generator(_payload(sql=bad_sql)).generate("问题")


def test_unparseable_sql_rejected() -> None:
    with pytest.raises(SQLUnsafeError):
        _generator(_payload(sql="SELEC 123")).generate("问题")


def test_empty_sql_rejected() -> None:
    with pytest.raises(SQLGenOutputInvalidError):
        _generator(_payload(sql="   ")).generate("问题")


# ---------- 非法 Schema ----------


def test_nonexistent_table_rejected() -> None:
    out = _payload(tables=["orders", "payments"])
    with pytest.raises(SQLGenSchemaMismatchError, match="payments"):
        _generator(out).generate("问题")


def test_table_not_in_schema_linking_rejected() -> None:
    # users 真实存在但 Schema Linking 未提供
    out = _payload(tables=["users"], columns=["users.region"])
    with pytest.raises(SQLGenSchemaMismatchError, match="users"):
        _generator(out).generate("问题")


def test_column_format_rejected() -> None:
    out = _payload(columns=["orders.order_date", "total_amount"])
    with pytest.raises(SQLGenSchemaMismatchError):
        _generator(out).generate("问题")


def test_nonexistent_column_rejected() -> None:
    out = _payload(columns=["orders.xxx"])
    with pytest.raises(SQLGenSchemaMismatchError, match="orders.xxx"):
        _generator(out).generate("问题")


# ---------- 非法 JSON ----------


def test_non_json_rejected() -> None:
    with pytest.raises(SQLGenOutputInvalidError):
        _generator("这不是 JSON").generate("问题")


def test_missing_fields_rejected() -> None:
    with pytest.raises(SQLGenOutputInvalidError):
        _generator('{"sql": "SELECT 1"}').generate("问题")


# ---------- SQL 表引用一致性 ----------


def test_sql_referencing_unallowed_table_rejected() -> None:
    sql = "SELECT u.username FROM users u"
    out = _payload(sql=sql)  # tables 声明仍是 orders/order_items/products
    with pytest.raises(SQLTableMismatchError, match="users"):
        _generator(out).generate("问题")


def test_sql_with_cte_allowed_and_cte_names_filtered() -> None:
    sql = (
        "WITH x AS (SELECT region, COUNT(*) AS c FROM users GROUP BY region) "
        "SELECT * FROM x"
    )
    link = SchemaLinkResult(
        question="哪个地区的用户最多？",
        tables=["users"],
        columns=["users.region"],
        reasons=["按地区统计用户"],
        confidence=0.9,
    )
    out = _payload(
        sql=sql,
        tables=["users"],
        columns=["users.region"],
        explanation="按地区统计用户",
    )
    generator = SQLGenerator(
        provider=_FakeProvider(out),
        schema_linker=_FakeLinker(link),
        fewshot_retriever=_FakeRetriever(VALID_FEWSHOT),
    )
    result = generator.generate("哪个地区的用户最多？")
    assert "WITH x" in result.sql

    # CTE 名称不应被当作表引用
    assert extract_referenced_tables(sql) == {"users"}


def test_simple_select_sql_parses() -> None:
    sql = "SELECT region, COUNT(*) FROM users GROUP BY region"
    assert extract_referenced_tables(sql) == {"users"}
    link = SchemaLinkResult(
        question="哪个地区的用户最多？",
        tables=["users"],
        columns=["users.region"],
        reasons=["按地区统计用户"],
        confidence=0.9,
    )
    out = _payload(sql=sql, tables=["users"], columns=["users.region"])
    generator = SQLGenerator(
        provider=_FakeProvider(out),
        schema_linker=_FakeLinker(link),
        fewshot_retriever=_FakeRetriever(VALID_FEWSHOT),
    )
    assert generator.generate("哪个地区的用户最多？").sql.strip() != ""


# ---------- safety 直接测试 ----------


def test_check_sql_safety_allows_readonly() -> None:
    check_sql_safety("SELECT 1")
    check_sql_safety("WITH x AS (SELECT 1) SELECT * FROM x")


def test_check_sql_safety_rejects_writes() -> None:
    for bad in [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "SELECT 1; DELETE FROM orders",
    ]:
        with pytest.raises(SQLUnsafeError):
            check_sql_safety(bad)


def test_generate_prompt_received_question_and_fewshot() -> None:
    provider = _FakeProvider(_payload())
    generator = SQLGenerator(
        provider=provider,
        schema_linker=_FakeLinker(VALID_LINK),
        fewshot_retriever=_FakeRetriever(VALID_FEWSHOT),
    )
    generator.generate("近30天销售额最高的商品有哪些？")
    assert provider.last_messages is not None
    user_content = provider.last_messages[1]["content"]
    assert "近30天销售额最高的商品有哪些？" in user_content
    assert "ex_001" in user_content  # Few-shot 内容必须进入 Prompt
    assert "cancelled" in user_content  # 业务语义必须保留