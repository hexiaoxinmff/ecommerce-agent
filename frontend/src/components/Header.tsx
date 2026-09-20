export function Header() {
  return (
    <header className="header">
      <div className="header__left">
        <h1 className="header__title">电商智能数据分析 Agent</h1>
        <span className="badge badge-success">
          <span className="dot" />
          SQLite · 已连接
        </span>
      </div>

      <div className="header__right">
        <div className="header__llm">
          <span>Runtime LLM</span>
          <span className="ai-tag">Mimo V2.5 Pro</span>
        </div>
        <div className="header__user">
          <div className="header__avatar">管</div>
          <span>管理者</span>
        </div>
      </div>
    </header>
  );
}
