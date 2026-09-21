"""系统信息路由。

GET /api/system/database
仅用于验证 SQLite 只读连接真实打通：返回数据库名称与各表行数。
内部只执行固定 SQL，不接收、不执行任何用户提交的 SQL。

GET /api/system/schema
返回各业务表的真实字段结构、行数、外键与业务口径注释（只读）。
数据来源：
- 表集合 / 字段 / 类型 / 主键 / 非空：SchemaCatalog（真实 PRAGMA table_info）
- 业务口径注释：app.schema.metadata 中的既有描述常量
- 行数：get_database_info()（与 /api/system/database 同一访问路径）
- 外键：introspect_foreign_keys()（真实 PRAGMA foreign_key_list）

本模块不导入 app.llm / app.agent，不发起任何 LLM 调用，也不修改数据库。
"""

from fastapi import APIRouter, HTTPException

from app.db.sqlite import DatabaseError, get_database_info
from app.schema.introspector import introspect_foreign_keys
from app.schema.metadata import SchemaCatalog
from app.schemas.system import (
    DatabaseInfo,
    SchemaColumn,
    SchemaForeignKey,
    SchemaResponse,
    SchemaTable,
)

router = APIRouter(tags=["system"])


@router.get("/database", response_model=DatabaseInfo, summary="数据库信息（只读验证）")
def database_info() -> DatabaseInfo:
    """返回数据库名称与 5 张业务表真实行数。"""
    try:
        info = get_database_info()
    except DatabaseError as exc:
        raise HTTPException(
            status_code=503,
            detail="数据库不可用，请确认 db/ecommerce.db 存在且可读。",
        ) from exc
    return DatabaseInfo(**info)


@router.get(
    "/schema",
    response_model=SchemaResponse,
    summary="数据库 Schema 元数据（只读）",
)
def database_schema() -> SchemaResponse:
    """返回各业务表的真实字段结构、行数、外键与业务口径注释。

    表集合取自 SchemaCatalog（不写死表名）；字段、类型、主键、非空来自真实
    PRAGMA table_info；业务口径注释复用 metadata.py 既有常量；行数复用
    get_database_info()；外键来自真实 PRAGMA foreign_key_list。
    """
    try:
        info = get_database_info()
        catalog = SchemaCatalog.get_cached()
        tables: list[SchemaTable] = []
        for name in catalog.table_names:
            table_meta = catalog.get_table(name)
            if table_meta is None:
                # 不可达：name 来自 catalog 自身。出现即 Schema 目录自相矛盾，
                # 宁可显式失败也不静默丢表（丢表会直接误导页面使用者）。
                raise HTTPException(
                    status_code=500,
                    detail="Schema 元数据不一致，请重启服务后重试。",
                )
            tables.append(
                SchemaTable(
                    table=table_meta.name,
                    description=table_meta.description,
                    columns=[
                        SchemaColumn(
                            name=column.name,
                            type=column.type,
                            description=column.description,
                            not_null=column.not_null,
                            primary_key=column.primary_key,
                        )
                        for column in table_meta.columns
                    ],
                    row_count=int(info[table_meta.name]),
                    foreign_keys=[
                        SchemaForeignKey(**fk)
                        for fk in introspect_foreign_keys(table_meta.name)
                    ],
                )
            )
    except DatabaseError as exc:
        raise HTTPException(
            status_code=503,
            detail="数据库不可用，请确认 db/ecommerce.db 存在且可读。",
        ) from exc
    return SchemaResponse(database=str(info["database"]), tables=tables)
