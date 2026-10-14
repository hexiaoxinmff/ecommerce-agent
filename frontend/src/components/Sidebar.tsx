import { IconChart, IconDatabase, IconHistory, IconHome, IconSettings, IconSpark } from "./Icons";

export type PageKey = "home" | "analysis" | "datasets" | "history" | "settings" | "login";

export const NAV_ITEMS: { key: PageKey; label: string; icon: React.ReactNode; hint: string }[] = [
  { key: "home", label: "首页", icon: <IconHome />, hint: "首页：数据概览与快速提问" },
  { key: "analysis", label: "智能分析", icon: <IconChart />, hint: "智能分析：用自然语言提问并查看分析链路" },
  { key: "datasets", label: "数据集管理", icon: <IconDatabase />, hint: "数据集管理：数据库与 Schema 概览" },
  { key: "history", label: "历史记录", icon: <IconHistory />, hint: "历史记录：历史问题与执行状态" },
  { key: "settings", label: "系统设置", icon: <IconSettings />, hint: "系统设置：运行时配置与系统状态" },
];

type SidebarProps = {
  active: PageKey;
  onNavigate: (key: PageKey) => void;
};

export function Sidebar({ active, onNavigate }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="全局导航">
      <div className="sidebar__brand">
        <div className="sidebar__logo">
          <IconSpark size={18} />
        </div>
        <div className="sidebar__title">电商智能数据<br />分析 Agent</div>
      </div>

      <nav className="sidebar__nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`nav-item${active === item.key ? " nav-item--active" : ""}`}
            title={item.hint}
            onClick={() => onNavigate(item.key)}
          >
            <span className="nav-item__icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar__foot">
        <div className="version">UI/UX v1.0 · 汇报演示优化版</div>
      </div>
    </aside>
  );
}
