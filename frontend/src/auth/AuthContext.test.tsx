/**
 * 认证状态管理测试：登录成功/失败、token 保存（password 不入存储）、
 * 登出清理、/me 恢复登录态、/me 失败清理、401 事件自动登出、ProtectedRoute 守卫。
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider, ProtectedRoute, useAuth } from "./AuthContext";
import { apiRequest } from "../api/http";
import { jsonResponse, seedSession } from "../test/helpers";

const LOGIN_OK = {
  access_token: "tok_login",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00+00:00",
  user: { id: 1, username: "alice", email: "alice@example.com" },
};

function AuthProbe() {
  const {
    user,
    isAuthenticated,
    isLoading,
    status,
    login,
    logout,
    refreshCurrentUser,
    retryBackendCheck,
  } = useAuth();
  if (isLoading) return <p>loading</p>;
  return (
    <div>
      <p data-testid="status">{isAuthenticated ? "authenticated" : "anonymous"}</p>
      <p data-testid="auth-status">{status}</p>
      <p data-testid="username">{user?.username ?? "none"}</p>
      <button type="button" onClick={() => void login("alice", "pw123456").catch(() => {})}>
        do-login
      </button>
      <button type="button" onClick={() => void logout()}>
        do-logout
      </button>
      <button
        type="button"
        onClick={() => void refreshCurrentUser().catch(() => {})}
      >
        do-refresh
      </button>
      <button
        type="button"
        onClick={() => void apiRequest("/api/secure-thing").catch(() => {})}
      >
        fire-401
      </button>
      <button type="button" onClick={() => void retryBackendCheck()}>
        do-retry-backend
      </button>
    </div>
  );
}

function renderAuth() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  );
}

function mockAuthFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/auth/login")) return jsonResponse(LOGIN_OK);
    if (url.includes("/api/auth/me")) return jsonResponse({ id: 1, username: "alice", email: "alice@example.com", is_active: true });
    if (url.includes("/api/auth/logout")) return new Response(null, { status: 204 });
    if (url.includes("/api/secure-thing")) return jsonResponse({ detail: "Invalid credentials" }, 401);
    throw new Error(`unhandled ${url}`);
  });
}

describe("AuthContext", () => {
  it("登录成功：保存 token + user，password 不进入存储", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockAuthFetch());
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    await user.click(screen.getByRole("button", { name: "do-login" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("username")).toHaveTextContent("alice");

    const raw = window.localStorage.getItem("ecom.auth.session") ?? "";
    expect(raw).toContain("tok_login");
    expect(raw).toContain("alice@example.com");
    expect(raw).not.toContain("pw123456"); // password 永不入存储
  });

  it("登录失败（401）：保持未登录、不保存 token", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/api/auth/login")) {
          return jsonResponse({ detail: "Invalid credentials" }, 401);
        }
        throw new Error("unhandled");
      }),
    );
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    await user.click(screen.getByRole("button", { name: "do-login" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(window.localStorage.getItem("ecom.auth.session")).toBeNull();
  });

  it("登出：调用后端并清理本地会话", async () => {
    const user = userEvent.setup();
    const fetchMock = mockAuthFetch();
    vi.stubGlobal("fetch", fetchMock);
    seedSession("tok_existing");
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    await user.click(screen.getByRole("button", { name: "do-logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(window.localStorage.getItem("ecom.auth.session")).toBeNull();
    const logoutCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/auth/logout"));
    expect(logoutCall).toBeDefined();
  });

  it("启动时有 token：GET /me 成功恢复登录态", async () => {
    seedSession("tok_stored");
    vi.stubGlobal("fetch", mockAuthFetch());
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("username")).toHaveTextContent("alice");
  });

  it("启动时有 token 但 /me 失败（401）：清理登录态", async () => {
    seedSession("tok_stale");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/api/auth/me")) {
          return jsonResponse({ detail: "Invalid credentials" }, 401);
        }
        throw new Error("unhandled");
      }),
    );
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(window.localStorage.getItem("ecom.auth.session")).toBeNull();
  });

  it("已登录期间任意请求 401：自动清理登录态（统一 401 处理）", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockAuthFetch());
    seedSession("tok_will_die");
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    await user.click(screen.getByRole("button", { name: "fire-401" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(window.localStorage.getItem("ecom.auth.session")).toBeNull();
  });
});

describe("ProtectedRoute", () => {
  it("未认证 → 渲染 LoginPage，不渲染受保护内容", async () => {
    render(
      <AuthProvider>
        <ProtectedRoute>
          <p>PROTECTED_CONTENT</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument());
    expect(screen.queryByText("PROTECTED_CONTENT")).not.toBeInTheDocument();
  });

  it("已认证 → 渲染受保护内容", async () => {
    seedSession("tok_ok");
    vi.stubGlobal("fetch", mockAuthFetch());
    render(
      <AuthProvider>
        <ProtectedRoute>
          <p>PROTECTED_CONTENT</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByText("PROTECTED_CONTENT")).toBeInTheDocument());
  });
});

// ---------------------------------------------------------------------------
// 第十阶段 P0-1：认证状态模型 —— 「未登录」与「后端不可用」必须分开
// ---------------------------------------------------------------------------

/** 网络层失败：请求根本没到服务器（后端未启动 / 端口不通） */
function networkFailure() {
  return vi.fn(async () => {
    throw new TypeError("Failed to fetch");
  });
}

/** /me 返回指定 HTTP 状态码 */
function meFailsWith(status: number) {
  return vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/auth/me")) {
      return jsonResponse({ detail: "boom" }, status);
    }
    throw new Error(`unhandled ${String(input)}`);
  });
}

describe("AuthContext 状态模型：200 / 401 / 网络失败 / 5xx", () => {
  it("200 → authenticated", async () => {
    seedSession("tok_200");
    vi.stubGlobal("fetch", mockAuthFetch());
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated"));
  });

  it("401 → anonymous（服务在，凭证无效）", async () => {
    seedSession("tok_401");
    vi.stubGlobal("fetch", meFailsWith(401));
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent("anonymous"));
    expect(window.localStorage.getItem("ecom.auth.session")).toBeNull();
  });

  it("网络失败 → backend_unavailable，且**保留**会话（不是登出）", async () => {
    seedSession("tok_net");
    vi.stubGlobal("fetch", networkFailure());
    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("auth-status")).toHaveTextContent("backend_unavailable"),
    );
    // 关键：网络故障不得被记成"用户登出"，否则后端恢复后还要重新登录
    expect(window.localStorage.getItem("ecom.auth.session")).not.toBeNull();
  });

  it("5xx → backend_error，且**保留**会话", async () => {
    seedSession("tok_500");
    vi.stubGlobal("fetch", meFailsWith(500));
    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("auth-status")).toHaveTextContent("backend_error"),
    );
    expect(window.localStorage.getItem("ecom.auth.session")).not.toBeNull();
  });

  it("后端不可用 ≠ 未登录：不渲染登录页，渲染不可用页并给出重试", async () => {
    seedSession("tok_offline");
    vi.stubGlobal("fetch", networkFailure());
    render(
      <AuthProvider>
        <ProtectedRoute>
          <p>PROTECTED_CONTENT</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("backend-unavailable")).toBeInTheDocument());
    expect(screen.getByText(/请检查后端是否启动/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    // 不得把用户丢到登录页（那会让人以为是自己密码错了）
    expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
    expect(screen.queryByText("PROTECTED_CONTENT")).not.toBeInTheDocument();
  });

  it("重试：后端恢复后 → authenticated（会话未被清掉，无需重新登录）", async () => {
    const user = userEvent.setup();
    let backendDown = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/api/auth/me")) {
          if (backendDown) throw new TypeError("Failed to fetch");
          return jsonResponse({
            id: 1,
            username: "alice",
            email: "alice@example.com",
            is_active: true,
          });
        }
        throw new Error(`unhandled ${String(input)}`);
      }),
    );
    seedSession("tok_retry");
    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("auth-status")).toHaveTextContent("backend_unavailable"),
    );

    backendDown = false;
    await user.click(screen.getByRole("button", { name: "do-retry-backend" }));

    await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("username")).toHaveTextContent("alice");
  });

  it("重试仍失败 → 保持 backend_unavailable（不假装成功）", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", networkFailure());
    seedSession("tok_still_down");
    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("auth-status")).toHaveTextContent("backend_unavailable"),
    );
    await user.click(screen.getByRole("button", { name: "do-retry-backend" }));

    await waitFor(() =>
      expect(screen.getByTestId("auth-status")).toHaveTextContent("backend_unavailable"),
    );
  });
});
