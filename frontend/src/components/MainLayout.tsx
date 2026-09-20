import type { ReactNode } from "react";
import { Header } from "./Header";
import { Sidebar, type PageKey } from "./Sidebar";

type MainLayoutProps = {
  active: PageKey;
  onNavigate: (key: PageKey) => void;
  children: ReactNode;
};

export function MainLayout({ active, onNavigate, children }: MainLayoutProps) {
  return (
    <div className="layout">
      <Sidebar active={active} onNavigate={onNavigate} />
      <div className="layout__main">
        <Header />
        <main className="layout__content">
          <div className="layout__content-inner">{children}</div>
        </main>
      </div>
    </div>
  );
}
