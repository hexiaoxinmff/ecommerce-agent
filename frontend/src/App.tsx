import { useState, type ReactNode } from "react";
import { IconSettings } from "./components/Icons";
import { AuthProvider, ProtectedRoute, useAuth } from "./auth/AuthContext";
import { MainLayout } from "./components/MainLayout";
import { type PageKey } from "./components/Sidebar";
import { AnalysisPage } from "./pages/AnalysisPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { PlaceholderPage } from "./components/PlaceholderPage";

const PLACEHOLDERS: Record<"settings", { title: string; desc: string; icon: ReactNode }> = {
  settings: {
    title: "系统设置",
    desc: "Runtime LLM（Mimo V2.5 Pro）、API Base URL、API Key 遮蔽、模型信息与系统状态。",
    icon: <IconSettings />,
  },
};

function AppShell() {
  const [page, setPage] = useState<PageKey>("home");
  const { isLoading } = useAuth();
  // Phase 15（P0-3）：首页提问 → 智能分析页的真实链路。
  // HomePage 提交问题时记录 here 并切页；AnalysisPage 挂载后消费并自动执行，
  // 消费完成即回调清空，避免重复触发。
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);

  const startAnalysisFromHome = (question: string) => {
    setPendingQuestion(question);
    setPage("analysis");
  };

  let content: ReactNode;
  if (page === "login") {
    // 显式访问登录页：登录成功回到首页
    content = <LoginPage onSuccess={() => setPage("home")} />;
  } else if (isLoading) {
    content = (
      <section className="placeholder fade-in">
        <span className="badge badge-processing">
          <span className="dot" />
          正在恢复登录状态…
        </span>
      </section>
    );
  } else if (page === "history") {
    // 受保护页：未认证统一由 ProtectedRoute 呈现登录页，登录后回到原目标
    content = (
      <ProtectedRoute onLoginSuccess={() => setPage("history")}>
        <HistoryPage />
      </ProtectedRoute>
    );
  } else if (page === "analysis") {
    content = (
      <ProtectedRoute onLoginSuccess={() => setPage("analysis")}>
        <AnalysisPage
          initialQuestion={pendingQuestion}
          onInitialQuestionConsumed={() => setPendingQuestion(null)}
        />
      </ProtectedRoute>
    );
  } else if (page === "home") {
    // 受保护页：overview 已改为**必须带 Bearer**（决策 D6 于 2026-09-28 反转），
    // 因此首页与 history / analysis 同级，未认证统一由 ProtectedRoute
    // 呈现登录页，登录成功后回到首页。
    content = (
      <ProtectedRoute onLoginSuccess={() => setPage("home")}>
        <HomePage onStartAnalysis={startAnalysisFromHome} />
      </ProtectedRoute>
    );
  } else if (page === "datasets") {
    content = <DatasetsPage />;
  } else {
    const meta = PLACEHOLDERS[page];
    content = (
      <PlaceholderPage title={meta.title} description={meta.desc} icon={meta.icon} />
    );
  }

  return (
    <MainLayout active={page} onNavigate={setPage}>
      {content}
    </MainLayout>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}
