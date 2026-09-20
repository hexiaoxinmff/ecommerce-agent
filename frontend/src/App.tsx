import { useState } from "react";
import { IconDatabase, IconHistory, IconSettings } from "./components/Icons";
import { MainLayout } from "./components/MainLayout";
import { type PageKey } from "./components/Sidebar";
import { AnalysisPage } from "./pages/AnalysisPage";
import { HomePage } from "./pages/HomePage";
import { PlaceholderPage } from "./components/PlaceholderPage";

const PLACEHOLDERS: Record<"datasets" | "history" | "settings", { title: string; desc: string; icon: React.ReactNode }> = {
  datasets: {
    title: "数据集管理",
    desc: "展示 ecommerce.db · SQLite · 已连接，以及 5 张表、Schema 与数据规模概览（P1）。",
    icon: <IconDatabase />,
  },
  history: {
    title: "历史记录",
    desc: "展示历史问题、执行状态、SQL 摘要与结果摘要（P1）。",
    icon: <IconHistory />,
  },
  settings: {
    title: "系统设置",
    desc: "Runtime LLM（Mimo V2.5 Pro）、API Base URL、API Key 遮蔽、模型信息与系统状态。",
    icon: <IconSettings />,
  },
};

export default function App() {
  const [page, setPage] = useState<PageKey>("home");

  return (
    <MainLayout active={page} onNavigate={setPage}>
      {page === "home" ? (
        <HomePage />
      ) : page === "analysis" ? (
        <AnalysisPage />
      ) : (
        <PlaceholderPage
          title={PLACEHOLDERS[page].title}
          description={PLACEHOLDERS[page].desc}
          icon={PLACEHOLDERS[page].icon}
        />
      )}
    </MainLayout>
  );
}
