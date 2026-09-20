import { dbStatus } from "../data/demo";

/** 数据库状态（UI/UX v1.0 第 9.5 节；规模来自 database-schema.md 真实开发库） */
export function DbStatus() {
  return (
    <section className="card db-card">
      <div className="db-card__head">
        <div>
          <div className="db-card__file">
            {dbStatus.file}
            <span className="db-card__type">{dbStatus.type}</span>
          </div>
          <span className="section-sub">当前开发数据库 · 合成数据</span>
        </div>
        <span className="badge badge-success">
          <span className="dot" />
          已连接
        </span>
      </div>
      <div className="db-card__stats">
        {dbStatus.stats.map((s) => (
          <div className="db-card__stat" key={s.label}>
            <span className="db-card__stat-label">{s.label}</span>
            <span className="db-card__stat-value num">{s.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
