/**
 * 统一 HTTP 请求层（P5）。
 *
 * 职责：
 * - API Base URL 集中管理（agent.ts 保留 re-export 以兼容既有导入）；
 * - 自动注入 `Authorization: Bearer <token>`（token 来自集中存储，调用方不手写）；
 * - 统一 JSON / 错误解析（后端统一以 `detail` 或 `error` 返回文案）；
 * - 401 统一处理：清空本地会话并广播事件（登录/注册接口豁免，避免重定向循环）。
 *
 * 安全约定：
 * - token 为 opaque bearer token，前端只负责保存与发送，绝不解析内容；
 * - password 任何情况下不进入存储；token 不进 URL、不打日志。
 */

/** 后端 Base URL：优先 VITE_API_BASE_URL，默认本地开发地址 */
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ??
  "http://127.0.0.1:8000";

/**
 * 会话存储（localStorage，key 集中定义；仅存 token/过期时间/用户摘要，
 * 绝不存 password）。前端不解析 token 内容。
 */
const AUTH_STORAGE_KEY = "ecom.auth.session";

export interface StoredAuthUser {
  id: number;
  username: string;
  email: string;
  is_active?: boolean;
}

export interface StoredAuthSession {
  accessToken: string;
  expiresAt: string;
  user?: StoredAuthUser;
}

export function loadStoredSession(): StoredAuthSession | null {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredAuthSession>;
    if (typeof parsed.accessToken !== "string" || !parsed.accessToken) return null;
    return parsed as StoredAuthSession;
  } catch {
    return null;
  }
}

export function saveStoredSession(session: StoredAuthSession): void {
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredSession(): void {
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

/** 后端统一错误（非 2xx）：携带状态码与安全文案（detail / error） */
export class HttpApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpApiError";
    this.status = status;
  }
}

/**
 * 网络层失败：请求**根本没有到达服务器**（后端未启动 / 端口不通 / 连接被重置 / DNS 失败）。
 *
 * 为什么必须与 `HttpApiError` 分开（第十阶段 P0-1）：在此之前 `/api/auth/me` 的
 * **任何**失败都被当成"未登录"，于是后端整个挂掉时用户看到的是**登录页** ——
 * 一个会让人反复输入正确密码的错误语义。
 *
 * 这是两件不同的事：
 * - HTTP 401：服务在，凭证无效 → 未登录；
 * - 连不上：服务不在 → 后端不可用。
 */
export class HttpNetworkError extends Error {
  constructor(message = "无法连接后端服务") {
    super(message);
    this.name = "HttpNetworkError";
  }
}

/** 请求失败的四种业务语义（与任务书 §二 的状态模型一一对应） */
export type RequestFailureKind =
  | "unauthorized"
  | "backend_unavailable"
  | "backend_error"
  | "other";

/**
 * 把任意请求错误归类。**唯一分类源** —— 调用方不得再自行 `instanceof TypeError`
 * 判网络故障（否则同一事实会有两个推导源，必然漂移）。
 */
export function classifyRequestFailure(err: unknown): RequestFailureKind {
  if (err instanceof HttpNetworkError) return "backend_unavailable";
  if (err instanceof HttpApiError) {
    if (err.status === 401 || err.status === 403) return "unauthorized";
    if (err.status >= 500) return "backend_error";
    return "other";
  }
  // 兜底：少数运行环境（或测试替身）仍以裸 TypeError 表示连接失败
  if (err instanceof TypeError) return "backend_unavailable";
  return "other";
}

/** 主动取消（AbortController）不是故障，必须原样透传，不得污染状态判断 */
function isAbortError(err: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && err instanceof DOMException && err.name === "AbortError") ||
    (err instanceof Error && err.name === "AbortError")
  );
}

// ---------- 401 统一处理 ----------

type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

/** 注册 401 监听（返回取消函数）；AuthContext 在此清理登录态并回到登录页 */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/** 这些路径的 401 属于登录/注册本身失败，不触发全局登出（避免循环） */
const UNAUTHORIZED_EXEMPT_PATHS = new Set(["/api/auth/login", "/api/auth/register"]);

function extractServerError(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string" && record.detail) return record.detail;
    if (typeof record.error === "string" && record.error) return record.error;
  }
  return fallback;
}

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** 是否携带 Bearer（登录/注册等匿名接口传 false；默认 true） */
  auth?: boolean;
}

/** 统一请求入口：所有 API 模块经由本函数，页面不得散落 fetch */
export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { method = "GET", body, signal, auth = true } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    const session = loadStoredSession();
    if (session?.accessToken) headers["Authorization"] = `Bearer ${session.accessToken}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    // 主动取消原样透传；其余（连不上 / DNS / 连接被重置）统一为 HttpNetworkError，
    // 让调用方能区分"后端不可用"与"未登录"。
    if (isAbortError(err)) throw err;
    throw new HttpNetworkError();
  }

  if (res.status === 401 && auth && !UNAUTHORIZED_EXEMPT_PATHS.has(path)) {
    clearStoredSession();
    for (const listener of unauthorizedListeners) listener();
  }

  let parsed: unknown = null;
  if (res.status !== 204) {
    try {
      parsed = await res.json();
    } catch {
      parsed = null;
    }
  }

  if (!res.ok) {
    throw new HttpApiError(res.status, extractServerError(parsed, `请求失败（HTTP ${res.status}）`));
  }

  return parsed as T;
}
