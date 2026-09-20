import type { ReactNode } from "react";

type PlaceholderPageProps = {
  title: string;
  description: string;
  icon: ReactNode;
};

/** 占位页面：导航入口存在，功能按 PRD 分阶段实现（阶段 3 仅首页） */
export function PlaceholderPage({ title, description, icon }: PlaceholderPageProps) {
  return (
    <section className="placeholder fade-in">
      <div className="placeholder__icon">{icon}</div>
      <h2>{title}</h2>
      <p>{description}</p>
      <span className="badge badge-processing">
        <span className="dot" />
        页面结构已就绪 · 功能属于后续阶段（P1 或阶段 3 后续任务）
      </span>
    </section>
  );
}
