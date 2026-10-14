/**
 * 认证状态管理（P5；第十阶段 P0-1 扩展为四态）。
 *
 * - user / accessToken / expiresAt / isAuthenticated / isLoading / status；
 * - login()：POST /api/auth/login → 保存会话（localStorage，单 key 集中于 http.ts）；
 * - register()：注册成功后自动登录；
 * - logout()：尽力调用后端登出，随后无条件清理本地会话；
 * - refreshCurrentUser() / retryBackendCheck()：启动或重试时 GET /api/auth/me；
 * - ProtectedRoute：统一路由守卫，按状态分派（登录页 / 后端不可用页 / 内容）。
 *
 * ★ 状态模型（第十阶段 P0-1）：
 *
 *     200          → authenticated       已登录
 *     401 / 403    → anonymous           未登录（服务在，凭证无效）
 *     网络失败      → backend_unavailable 后端不可用（服务不在）
 *     5xx          → backend_error       后端异常（服务在但坏了）
 *
 *   在此之前，`/api/auth/me` 的**任何**失败都被当成"未登录"，于是后端整个挂掉时
 *   用户看到的是登录页 —— 一个会让人反复输入正确密码的错误语义。
 *
 * ★ 会话保留策略：只有 401/403（以及无法归类的其它 4xx）才清理本地会话。
 *   网络失败与 5xx **保留** token —— 服务恢复后刷新页面即可回到真实系统，
 *   而不是被迫重新登录。"服务挂了"不等于"你登出了"。
 *
 * 安全：password 不落任何存储；token 为 opaque bearer，仅保存与发送。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getCurrentUser,
  login as loginApi,
  logout as logoutApi,
  register as registerApi,
  type AuthUserDto,
} from "../api/auth";
import {
  classifyRequestFailure,
  clearStoredSession,
  loadStoredSession,
  onUnauthorized,
  saveStoredSession,
} from "../api/http";
import { BackendUnavailable, type BackendIssue } from "../components/BackendUnavailable";
import { LoginPage } from "../pages/LoginPage";

export type AuthStatus =
  | "loading"
  | "authenticated"
  | "anonymous"
  | "backend_unavailable"
  | "backend_error";

/** 哪些状态属于"后端出问题"（此时不得渲染登录页） */
const BACKEND_ISSUES: Record<string, BackendIssue> = {
  backend_unavailable: "backend_unavailable",
  backend_error: "backend_error",
};

interface AuthContextValue {
  user: AuthUserDto | null;
  accessToken: string | null;
  expiresAt: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** 五态认证状态（未登录与后端不可用严格区分） */
  status: AuthStatus;
  login(username: string, password: string): Promise<void>;
  register(username: string, email: string, password: string): Promise<void>;
  logout(): Promise<void>;
  refreshCurrentUser(): Promise<void>;
  /** 后端不可用 / 异常时的重试：重新校验会话，成功后回到 authenticated */
  retryBackendCheck(): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  return loadStoredSession()?.accessToken ?? null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUserDto | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const clearSession = useCallback(() => {
    clearStoredSession();
    setUser(null);
    setToken(null);
    setExpiresAt(null);
    setStatus("anonymous");
  }, []);

  const applySession = useCallback(
    (accessToken: string, sessionExpiresAt: string, sessionUser: AuthUserDto) => {
      saveStoredSession({ accessToken, expiresAt: sessionExpiresAt, user: sessionUser });
      setToken(accessToken);
      setExpiresAt(sessionExpiresAt);
      setUser(sessionUser);
      setStatus("authenticated");
    },
    [],
  );

  /**
   * 把 `/api/auth/me` 的失败翻译成正确的业务语义。
   * 这里是**唯一**的分类点，页面不得再自行判断错误类型。
   */
  const applySessionFailure = useCallback(
    (err: unknown) => {
      switch (classifyRequestFailure(err)) {
        case "unauthorized":
          // 服务在、凭证无效 → 真的未登录（http 层已清 storage 并广播）
          clearSession();
          break;
        case "backend_unavailable":
          // 服务不在：**保留会话**，只改状态。
          // 清掉会话等于把"后端挂了"记成"用户登出了"。
          setStatus("backend_unavailable");
          break;
        case "backend_error":
          setStatus("backend_error");
          break;
        default:
          // 无法归类的失败：宁可回到登录页，也不假装还登录着
          clearSession();
      }
    },
    [clearSession],
  );

  /** `/me` 成功后的统一落地：期间若已被 401 清理，则不复活登录态 */
  const applyMe = useCallback((me: AuthUserDto) => {
    if (!loadStoredSession()?.accessToken) return;
    setUser(me);
    setStatus("authenticated");
  }, []);

  // 启动恢复：有 token → GET /me；按失败类型分派（不再一律清理）
  useEffect(() => {
    const stored = loadStoredSession();
    if (!stored?.accessToken) {
      setStatus("anonymous");
      return;
    }
    setUser(stored.user ?? null);
    setToken(stored.accessToken);
    setExpiresAt(stored.expiresAt ?? null);
    let cancelled = false;
    getCurrentUser()
      .then((me) => {
        if (!cancelled) applyMe(me);
      })
      .catch((err: unknown) => {
        if (!cancelled) applySessionFailure(err);
      });
    return () => {
      cancelled = true;
    };
  }, [applyMe, applySessionFailure]);

  // 401 统一处理：任何带认证请求返回 401 → 清理登录态（受保护页自动回到登录）
  useEffect(() => onUnauthorized(() => clearSession()), [clearSession]);

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await loginApi({ username, password });
      applySession(res.access_token, res.expires_at, res.user);
    },
    [applySession],
  );

  const register = useCallback(
    async (username: string, email: string, password: string) => {
      await registerApi({ username, email, password });
      // 注册成功后自动登录，直接进入受保护流程
      const res = await loginApi({ username, password });
      applySession(res.access_token, res.expires_at, res.user);
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await logoutApi();
    } catch {
      // 后端会话可能已失效：无论结果如何都清理本地登录态
    }
    clearSession();
  }, [clearSession]);

  const refreshCurrentUser = useCallback(async () => {
    const me = await getCurrentUser();
    applyMe(me);
  }, [applyMe]);

  const retryBackendCheck = useCallback(async () => {
    setStatus("loading");
    try {
      applyMe(await getCurrentUser());
    } catch (err) {
      applySessionFailure(err);
    }
  }, [applyMe, applySessionFailure]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      accessToken: token,
      expiresAt,
      isAuthenticated: status === "authenticated",
      isLoading: status === "loading",
      status,
      login,
      register,
      logout,
      refreshCurrentUser,
      retryBackendCheck,
    }),
    [
      user,
      token,
      expiresAt,
      status,
      login,
      register,
      logout,
      refreshCurrentUser,
      retryBackendCheck,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}

/** 有 token 即视为可能已登录（供守卫外需要轻量判断的场合） */
export function hasStoredToken(): boolean {
  return readStoredToken() !== null;
}

/** 会话恢复中的轻量加载态 */
function RestoringSession() {
  return (
    <section className="placeholder fade-in">
      <span className="badge badge-processing">
        <span className="dot" />
        正在恢复登录状态…
      </span>
    </section>
  );
}

/**
 * 统一路由守卫：按状态分派。
 *
 * - `loading`              → 恢复中提示；
 * - `backend_unavailable`  → 后端不可用页（**不跳登录页**，保留重试）；
 * - `backend_error`        → 后端异常页（同上）；
 * - `anonymous`            → LoginPage（登录成功后执行 onLoginSuccess 回到原目标）。
 *
 * 页面内部不得再散落 `if (!user)` 判断。
 */
export function ProtectedRoute({
  children,
  onLoginSuccess,
}: {
  children: ReactNode;
  onLoginSuccess?: () => void;
}) {
  const { status, isAuthenticated, isLoading, retryBackendCheck } = useAuth();
  if (isLoading) {
    return <RestoringSession />;
  }
  const issue = BACKEND_ISSUES[status];
  if (issue) {
    return <BackendUnavailable reason={issue} onRetry={retryBackendCheck} />;
  }
  if (!isAuthenticated) {
    return <LoginPage onSuccess={onLoginSuccess} />;
  }
  return <>{children}</>;
}
