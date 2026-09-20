import { useState } from "react";

type SqlPanelProps = {
  sql: string;
  /** 默认展开（答辩时 SQL 是重要证据，但视觉层级低于结果） */
  defaultOpen?: boolean;
  /** 面板副标题（区分演示/真实） */
  subtitle?: string;
};

/** SQL 查询面板：展开/收起 + 复制（UI/UX v1.0 第 10.5、11 节） */
export function SqlPanel({ sql, defaultOpen = true, subtitle = "Agent 生成 · SQLite 只读执行" }: SqlPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = sql;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <section className="card sql-panel">
      <div className="sql-panel__head">
        <div>
          <h2 className="section-title">SQL 查询</h2>
          <span className="section-sub">{subtitle}</span>
        </div>
        <div className="sql-panel__actions">
          <button type="button" className="btn-ghost" onClick={copy}>
            {copied ? "已复制 ✓" : "复制 SQL"}
          </button>
          <button type="button" className="btn-ghost" onClick={() => setOpen((v) => !v)}>
            {open ? "收起" : "展开"}
          </button>
        </div>
      </div>
      {open && (
        <pre className="sql-panel__code fade-in">
          <code>{sql}</code>
        </pre>
      )}
    </section>
  );
}
