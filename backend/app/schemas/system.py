"""系统信息相关 Pydantic 模型。"""

from pydantic import BaseModel


class DatabaseInfo(BaseModel):
    """GET /api/system/database 响应结构（各表行数来自真实查询）。"""

    database: str
    tables: int
    users: int
    categories: int
    products: int
    orders: int
    order_items: int


class SchemaColumn(BaseModel):
    """单个字段（类型 / 非空 / 主键来自真实 PRAGMA table_info）。"""

    name: str
    type: str
    description: str
    not_null: bool
    primary_key: bool


class SchemaForeignKey(BaseModel):
    """单条外键（来自真实 PRAGMA foreign_key_list）。"""

    from_column: str
    to_table: str
    to_column: str


class SchemaTable(BaseModel):
    """单张业务表的完整结构。"""

    table: str
    description: str
    columns: list[SchemaColumn]
    row_count: int
    foreign_keys: list[SchemaForeignKey]


class SchemaResponse(BaseModel):
    """GET /api/system/schema 响应结构（表集合与行数均来自真实数据库）。"""

    database: str
    tables: list[SchemaTable]