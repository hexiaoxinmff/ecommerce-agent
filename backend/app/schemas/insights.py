"""业务洞察（Dashboard）相关 Pydantic 模型。

`GET /api/insights/overview` 的响应结构。设计约束（第九阶段 Phase C）：

- 所有数值均来自真实数据库的**固定只读 SQL** 聚合结果，接口不接收任何用户输入；
- **不返回任何"趋势百分比"**：`data/demo.ts` 里的 `+12.4% / -1.8%` 没有任何真实来源
  （既非环比也非同比，无法回溯），第一版不编这类数字；
- **不返回任何用户私有数据**：查询历史属于用户私有，走 `GET /api/history` 的既有
  `user_id` 隔离，绝不塞进这个全局聚合接口；
- `as_of` = `MAX(orders.order_date)`，即**数据截止日**。前端**必须展示**它，
  否则「本月销售额」会被误读为完整自然月（真实库 2026-09 只到 09-12）。
"""

from pydantic import BaseModel


class KpiValue(BaseModel):
    """单个 KPI：真实聚合值 + 单位 + 口径标注。

    `value` 在无数据时为 `0.0`（不是 `null`），避免前端出现 `NaN` 展示；
    `month` 仅在按「本月」统计的指标上出现，无数据时为 `None`。
    """

    label: str
    value: float
    unit: str
    month: str | None = None


class OverviewKpis(BaseModel):
    """首页 4 张 KPI 卡。口径见 `app/api/routes/insights.py` 模块 docstring。"""

    month_sales: KpiValue
    month_orders: KpiValue
    users_total: KpiValue
    avg_order_value: KpiValue


class SalesTrendPoint(BaseModel):
    """销售趋势的一个月份点（单位：元，原始值；前端自行决定展示精度）。"""

    month: str
    sales: float


class CategoryDistributionItem(BaseModel):
    """类目分布项（叶子类目）。`sales` 单位：元。"""

    category: str
    sales: float
    quantity: int


class TopProductItem(BaseModel):
    """Top 商品项。口径为**销售额**（`SUM(order_items.subtotal)`），与类目分布统一。"""

    rank: int
    product: str
    quantity: int
    sales: float


class OverviewResponse(BaseModel):
    """`GET /api/insights/overview` 响应。

    `as_of` / `kpis.*.month` 在库为空时为 `None`（空库必须返回 200 + 空结构，
    而不是 500 —— 见 `backend/tests/test_insights_api.py`）。
    """

    as_of: str | None
    generated_at: str
    kpis: OverviewKpis
    sales_trend: list[SalesTrendPoint]
    category_distribution: list[CategoryDistributionItem]
    top_products: list[TopProductItem]
