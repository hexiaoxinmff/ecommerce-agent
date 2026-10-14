import { useState } from "react";

type SqlPanelProps = {
  sql: string;
  /**
   * 默认**收起**（第十二阶段 Result First：SQL 属于证据/审计层，
   * 默认不与结果争夺第一视觉；需要审计时点「查看 SQL」展开）
   */
  defaultOpen?: boolean;
  /** 面板副标题（区分演示/真实） */
  subtitle?: string;
};

/** SQL 查询面板：展开/收起 + 复制（UI/UX v1.0 第 10.5、11 节） */
export function SqlPanel({ sql, defaultOpen = false, subtitle = "Agent 生成 · SQLite 只读执行" }: SqlPanelProps) {
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
          <button
            type="button"
            className="btn-ghost"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "收起 SQL" : "查看 SQL"}
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
