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