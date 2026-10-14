import { useId, useState } from "react";
import type { ReactNode } from "react";

type CollapsiblePanelProps = {
  /** 折叠状态下的可点击标题（如「查看执行过程」） */
  title: string;
  /** 标题右侧的补充说明（如节点数） */
  subtitle?: string;
  defaultOpen?: boolean;
  children: ReactNode;
};

/**
 * 证据折叠面板（第十二阶段 Result First）。
 *
 * 定位：Trace / 执行流程属于**解释层 / 审计层**，默认折叠，
 * 不与「结果」争夺第一视觉。原生 button 承载展开态（aria-expanded），
 * 键盘 Enter / Space 即可操作，不引入任何新 UI 框架。
 */
export function CollapsiblePanel({
  title,
  subtitle,
  defaultOpen = false,
  children,
}: CollapsiblePanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  return (
    <section className="card collapsible-panel">
      <button
        type="button"
        className="collapsible-panel__toggle"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className={`collapsible-panel__arrow${open ? " collapsible-panel__arrow--open" : ""}`}
          aria-hidden="true"
        >
          ▶
        </span>
        <span className="collapsible-panel__title">{title}</span>
        {subtitle && <span className="collapsible-panel__sub">{subtitle}</span>}
      </button>
      {open && (
        <div id={contentId} className="collapsible-panel__content fade-in">
          {children}
        </div>
      )}
    </section>
  );
}
