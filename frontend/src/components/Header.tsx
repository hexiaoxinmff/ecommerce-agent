/**
 * 全局 Header（P5）：接入认证状态。
 *
 * - 已登录：avatar + 用户名 + 「历史记录」「退出登录」操作；
 * - 未登录：显示「登录」入口；
 * - 不改动既有左侧标题与 Runtime LLM 徽标样式；
 * - **数据库徽标与 Runtime LLM 徽标均取自 `GET /api/health` 的真实返回值**
 *   （第九阶段 Phase E）。原先第 53-56 行硬编码「SQLite · 已连接」——
 *   数据库挂掉时它依然是绿的，已删除。状态推导统一走 `useHealthStatus`
 *   + `utils/connection.ts`，与 `AnalysisPage` / `DbStatus` / `DatasetsPage` 同源。
 * - ⚠️ LLM 徽标只显示「**已配置**」，**绝不显示「可用 / 已连接」**：
 *   `/api/health` 只读后端环境配置，不发起任何 LLM 网络请求，
 *   它没有能力证明上游可达（用户 2026-09-28 决策：只读配置 + 措辞降级）。
 *   取不到配置时显示中性占位「—」，绝不伪造模型名。
 */

import { useAuth } from "../auth/AuthContext";
import { useHealthStatus } from "../hooks/useHealthStatus";
import {
  DB_CONNECTION_BADGE,
  DB_CONNECTION_WORD,
  LLM_CONFIG_TITLE,
} from "../utils/connection";
import type { PageKey } from "./Sidebar";

type HeaderProps = {
  onNavigate?: (key: PageKey) => void;
};

export function Header({ onNavigate }: HeaderProps) {
  const { user, isAuthenticated, logout } = useAuth();
  // 连接态与 LLM 配置标签全部来自真实探活；初始即 loading（「连接中」），
  // 在拿到证据之前不显示任何「已连接」
  const { tone, llmLabel } = useHealthStatus();

  return (
    <header className="header">
      <div className="header__left">
        <h1 className="header__title">电商智能数据分析 Agent</h1>
        <span className={`badge ${DB_CONNECTION_BADGE[tone]}`}>
          <span className="dot" />
          SQLite · {DB_CONNECTION_WORD[tone]}
        </span>
      </div>

      <div className="header__right">
        <div className="header__llm">
          <span>Runtime LLM</span>
          <span className="ai-tag" title={LLM_CONFIG_TITLE}>
            {llmLabel}
          </span>
        </div>

        {isAuthenticated && user ? (
          <div className="header__user">
            <div className="header__avatar">{user.username.slice(0, 1)}</div>
            <span>{user.username}</span>
            {onNavigate && (
              <button
                className="btn-ghost"
                type="button"
                onClick={() => onNavigate("history")}
              >
                历史记录
              </button>
            )}
            <button className="btn-ghost" type="button" onClick={() => void logout()}>
              退出登录
            </button>
          </div>
        ) : (
          <div className="header__user">
            {onNavigate && (
              <button
                className="btn-ghost"
                type="button"
                onClick={() => onNavigate("login")}
              >
                登录
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
