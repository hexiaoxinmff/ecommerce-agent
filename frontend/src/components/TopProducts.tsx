import type { TopProductItemDto } from "../api/insights";

type TopProductsProps = {
  /** 真实数据（来自 GET /api/insights/overview 的 top_products） */
  items: TopProductItemDto[];
  /** 指标口径说明。**必须写明按哪个指标排序**，否则榜单无法解释 */
  subtitle: string;
};

/** 金额格式化（接口返回单位为元） */
function formatMoney(value: number): string {
  return `¥${value.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Top 商品：结构化列表（阶段 1 以列表承载，可视化属 P1）。
 *
 * 第九阶段 Phase D 改造：数据由 props 传入（原先直接 `import { topProducts }`
 * 自 `../data/demo`，该文件已于 Phase G 删除）。**本组件不再持有任何数据**，
 * 空数据时显示明确提示，绝不回退到任何静态/演示数据。
 */
export function TopProducts({ items, subtitle }: TopProductsProps) {
  return (
    <section className="card chart-card">
      <div className="chart-card__head">
        <h2 className="section-title">Top 商品</h2>
        <span className="section-sub">{subtitle}</span>
      </div>
      {items.length === 0 ? (
        <div style={{ padding: "40px 0", textAlign: "center" }}>
          <span className="section-sub">暂无数据</span>
        </div>
      ) : (
        <div className="top-products">
          {items.map((p) => (
            <div className="top-products__item" key={p.rank}>
              <div className={`top-products__rank${p.rank <= 3 ? " top-products__rank--top" : ""}`}>
                #{p.rank}
              </div>
              <div className="top-products__name" title={p.product}>
                {p.product}
              </div>
              <div className="top-products__meta">
                <span className="top-products__sales">销量 {p.quantity.toLocaleString("en-US")}</span>
                <span className="top-products__amount">销售额 {formatMoney(p.sales)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
