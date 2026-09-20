import { topProducts } from "../data/demo";

/** Top 商品：结构化列表（阶段 1 以列表承载，可视化属 P1） */
export function TopProducts() {
  return (
    <section className="card chart-card">
      <div className="chart-card__head">
        <h2 className="section-title">Top 商品</h2>
        <span className="section-sub">按销量排序 · Demo 数据</span>
      </div>
      <div className="top-products">
        {topProducts.map((p) => (
          <div className="top-products__item" key={p.rank}>
            <div className={`top-products__rank${p.rank <= 3 ? " top-products__rank--top" : ""}`}>
              #{p.rank}
            </div>
            <div className="top-products__name" title={p.name}>
              {p.name}
            </div>
            <div className="top-products__meta">
              <span className="top-products__sales">销量 {p.sales}</span>
              <span className="top-products__amount">销售额 {p.amount}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
