"""Schema Metadata：把真实数据库结构 + 代码内业务描述组装为结构化元数据。

- 表名 / 字段名 / 字段类型：来自 introspector（真实 SQLite 数据库）；
- 业务描述：保存在本文件（TABLE_DESCRIPTIONS / COLUMN_DESCRIPTIONS）。

用途：
1. 提供给 Schema Linking Prompt；
2. 供 Schema 合法性校验复核 LLM 输出；
3. 后续 SQL Generator 可复用。
"""

import json
from dataclasses import dataclass

from app.schema import introspector

TABLE_DESCRIPTIONS: dict[str, str] = {
    "users": "平台注册用户",
    "categories": "商品分类（支持一级/叶子两级层级）",
    "products": "平台在售商品，统一挂在叶子分类下",
    "orders": "用户订单（含订单状态、金额、收货区域）",
    "order_items": "订单商品明细行（每个商品一行）",
}

COLUMN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "users": {
        "id": "用户 ID（主键）",
        "username": "用户名（唯一）",
        "email": "邮箱（唯一）",
        "region": "用户所在省份",
        "register_date": "注册日期（ISO YYYY-MM-DD）",
        "status": "用户状态：active 活跃 / inactive 停用",
    },
    "categories": {
        "id": "分类 ID（主键）",
        "name": "分类名称（唯一）",
        "parent_id": "父分类 ID（一级分类为 NULL）",
    },
    "products": {
        "id": "商品 ID（主键）",
        "name": "商品名称（唯一）",
        "category_id": "所属叶子分类 ID",
        "price": "商品当前售价（元）",
        "status": "商品状态：on_sale 在售 / off_sale 下架",
    },
    "orders": {
        "id": "订单 ID（主键）",
        "user_id": "下单用户 ID",
        "order_date": "下单日期（ISO YYYY-MM-DD）",
        "status": "订单状态：pending/paid/shipped/completed/cancelled",
        "region": "收货省份",
        "discount_amount": "订单优惠金额（取消订单为 0）",
        "shipping_fee": "运费（取消订单为 0）",
        "total_amount": "订单最终支付金额（取消订单为 0）",
    },
    "order_items": {
        "id": "明细 ID（主键）",
        "order_id": "所属订单 ID",
        "product_id": "商品 ID",
        "quantity": "购买数量",
        "unit_price": "成交单价（元）",
        "subtotal": "明细行金额（quantity * unit_price）",
    },
}


@dataclass(frozen=True)
class ColumnMeta:
    name: str
    type: str
    description: str
    not_null: bool
    primary_key: bool


@dataclass(frozen=True)
class TableMeta:
    name: str
    description: str
    columns: tuple[ColumnMeta, ...]


# 进程级 Schema 目录缓存。
# 背景（Task 29 Phase 1 实测）：SchemaCatalog.from_database() 每次调用会建立
# 6 条 SQLite 连接，而单个请求会调用它 2 次（SchemaLinker.link 与
# SQLGenerator.generate_with_context 各一次）→ 每请求 12 条连接。
# 数据库为只读且 Schema 已冻结，故可安全缓存。
_CATALOG_CACHE: "SchemaCatalog | None" = None

# from_database() 参数缺省哨兵：区分「未传 allowed_tables」（用默认白名单）
# 与「显式传 None」（不做白名单过滤）。
_UNSET = object()


class SchemaCatalog:
    """项目数据库的 Schema 元数据目录（来自真实数据库 + 业务描述）。"""

    def __init__(self, tables: dict[str, TableMeta]) -> None:
        self._tables = tables

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(self._tables.keys())

    def get_table(self, name: str) -> TableMeta | None:
        return self._tables.get(name)

    def has_table(self, name: str) -> bool:
        return name in self._tables

    def has_column(self, table: str, column: str) -> bool:
        table_meta = self._tables.get(table)
        return table_meta is not None and any(c.name == column for c in table_meta.columns)

    def to_prompt_text(self) -> str:
        """格式化为 Prompt 用 JSON 文本。"""
        schema_list = []
        for table_meta in self._tables.values():
            schema_list.append(
                {
                    "table": table_meta.name,
                    "description": table_meta.description,
                    "columns": [
                        {
                            "name": col.name,
                            "type": col.type,
                            "description": col.description,
                        }
                        for col in table_meta.columns
                    ],
                }
            )
        return json.dumps(schema_list, ensure_ascii=False, indent=2)

    @classmethod
    def from_database(
        cls,
        *,
        connection_factory=None,
        allowed_tables: "tuple[str, ...] | None | object" = _UNSET,
        table_descriptions: "dict[str, str] | None" = None,
        column_descriptions: "dict[str, dict[str, str]] | None" = None,
    ) -> "SchemaCatalog":
        """从真实 SQLite 数据库构建目录（表/字段名与数据库完全一致）。

        Phase 13（跨数据库适配）新增可选参数（全部缺省 = 原全局行为）：
        - connection_factory：连接来源（默认 app.db.sqlite.get_connection）；
        - allowed_tables：表白名单（默认 introspector.TABLE_NAMES；
          显式传 None 表示不过滤，内省库内全部业务表）；
        - table_descriptions / column_descriptions：业务描述
          （默认本模块 TABLE_DESCRIPTIONS / COLUMN_DESCRIPTIONS）。
        """
        tables_desc = (
            table_descriptions if table_descriptions is not None else TABLE_DESCRIPTIONS
        )
        cols_desc = (
            column_descriptions
            if column_descriptions is not None
            else COLUMN_DESCRIPTIONS
        )
        introspect_kwargs: dict[str, object] = {}
        if connection_factory is not None:
            introspect_kwargs["connection_factory"] = connection_factory
        if allowed_tables is not _UNSET:
            introspect_kwargs["allowed_tables"] = allowed_tables
        tables: dict[str, TableMeta] = {}
        for table_name in introspector.introspect_table_names(**introspect_kwargs):
            columns = tuple(
                ColumnMeta(
                    name=col["name"],
                    type=col["type"],
                    description=cols_desc.get(table_name, {}).get(col["name"], ""),
                    not_null=col["not_null"],
                    primary_key=col["primary_key"],
                )
                for col in introspector.introspect_columns(
                    table_name, connection_factory=connection_factory
                )
            )
            tables[table_name] = TableMeta(
                name=table_name,
                description=tables_desc.get(table_name, ""),
                columns=columns,
            )
        return cls(tables)

    @classmethod
    def get_cached(cls) -> "SchemaCatalog":
        """返回进程级缓存的 Schema 目录（首次调用时构建）。

        语义与 from_database() 完全一致，仅避免重复 introspection。
        数据库为只读且 Schema 已冻结，因此缓存不引入正确性风险。
        若运行期数据库结构发生变化，需先调用 clear_cache()。
        """
        global _CATALOG_CACHE
        if _CATALOG_CACHE is None:
            _CATALOG_CACHE = cls.from_database()
        return _CATALOG_CACHE

    @classmethod
    def clear_cache(cls) -> None:
        """清空进程级 Schema 缓存（测试或数据库变更后调用）。"""
        global _CATALOG_CACHE
        _CATALOG_CACHE = None