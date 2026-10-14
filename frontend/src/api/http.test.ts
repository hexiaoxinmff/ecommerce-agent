/**
 * 统一 HTTP 层测试：Bearer 自动注入、401 清理与广播、登录/注册豁免、204 处理。
 */

import { describe, expect, it, vi } from "vitest";

import {
  HttpApiError,
  HttpNetworkError,
  apiRequest,
  classifyRequestFailure,
  clearStoredSession,
  loadStoredSession,
  onUnauthorized,
  saveStoredSession,
} from "./http";
import { emptyResponse, jsonResponse, seedSession } from "../test/helpers";

describe("apiRequest", () => {
  it("存储会话后自动注入 Bearer 头", async () => {
    seedSession("tok_abc");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/secure", { method: "GET" });

    expect(fetchMock).toHaveBeenCalledOnce();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok_abc");
  });

  it("auth:false 时不注入 Authorization（登录/注册场景）", async () => {
    seedSession("tok_abc");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/auth/login", { method: "POST", auth: false });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("401 → 清空本地会话并广播事件", async () => {
    seedSession("tok_dead");
    const listener = vi.fn();
    onUnauthorized(listener);
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ detail: "Invalid credentials" }, 401)));

    await expect(apiRequest("/api/secure")).rejects.toBeInstanceOf(HttpApiError);
    expect(loadStoredSession()).toBeNull();
    expect(listener).toHaveBeenCalledOnce();
    clearStoredSession();
  });

  it("登录/注册路径的 401 不触发全局登出（避免循环）", async () => {
    seedSession("tok_keep");
    const listener = vi.fn();
    onUnauthorized(listener);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ detail: "Invalid credentials" }, 401)),
    );

    await expect(
      apiRequest("/api/auth/login", { method: "POST", auth: false }),
    ).rejects.toBeInstanceOf(HttpApiError);

    expect(listener).not.toHaveBeenCalled();
    expect(loadStoredSession()?.accessToken).toBe("tok_keep");
    clearStoredSession();
  });

  it("非 2xx 抛出带状态码与后端文案的 HttpApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "History not found" }, 404)),
    );

    const err = await apiRequest("/api/history/9").catch((e) => e);
    expect(err).toBeInstanceOf(HttpApiError);
    expect((err as HttpApiError).status).toBe(404);
    expect((err as HttpApiError).message).toBe("History not found");
  });

  it("204 空响应返回 null 且不解析 JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => emptyResponse(204)));

    await expect(apiRequest("/api/auth/logout", { method: "POST" })).resolves.toBeNull();
  });

  it("无 token 时请求不带 Authorization 头", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/anything");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["Authorization"]).toBeUndefined();
  });
});

describe("session storage", () => {  it("保存/读取/清理集中 key 的会话（不含 password 字段）", () => {
    saveStoredSession({
      accessToken: "tok_1",
      expiresAt: "2099-01-01T00:00:00+00:00",
      user: { id: 1, username: "alice", email: "a@example.com" },
    });

    const session = loadStoredSession();
    expect(session?.accessToken).toBe("tok_1");
    const raw = window.localStorage.getItem("ecom.auth.session") ?? "";
    expect(raw).not.toContain("password");

    clearStoredSession();
    expect(loadStoredSession()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 第十阶段 P0-1：网络失败必须与 HTTP 错误分开
// ---------------------------------------------------------------------------

describe("网络层失败：HttpNetworkError", () => {
  it("fetch 自身抛错 → HttpNetworkError（不是裸 TypeError）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const err = await apiRequest("/api/secure").catch((e) => e);
    expect(err).toBeInstanceOf(HttpNetworkError);
    expect(err).not.toBeInstanceOf(HttpApiError);
  });

  it("网络失败不清理本地会话（连不上 ≠ 登出）", async () => {
    seedSession("tok_alive");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await expect(apiRequest("/api/secure")).rejects.toBeInstanceOf(HttpNetworkError);
    expect(loadStoredSession()?.accessToken).toBe("tok_alive");
    clearStoredSession();
  });

  it("主动取消（AbortError）原样透传，不被当成后端不可用", async () => {
    const abortError = new Error("The operation was aborted.");
    abortError.name = "AbortError";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw abortError;
      }),
    );

    const err = await apiRequest("/api/secure").catch((e) => e);
    expect(err).toBe(abortError);
    expect(err).not.toBeInstanceOf(HttpNetworkError);
  });
});

describe("classifyRequestFailure：唯一分类源", () => {
  it("四种业务语义逐一映射正确", () => {
    expect(classifyRequestFailure(new HttpNetworkError())).toBe("backend_unavailable");
    expect(classifyRequestFailure(new HttpApiError(401, "Invalid credentials"))).toBe("unauthorized");
    expect(classifyRequestFailure(new HttpApiError(403, "Forbidden"))).toBe("unauthorized");
    expect(classifyRequestFailure(new HttpApiError(500, "boom"))).toBe("backend_error");
    expect(classifyRequestFailure(new HttpApiError(503, "degraded"))).toBe("backend_error");
    expect(classifyRequestFailure(new HttpApiError(422, "bad"))).toBe("other");
    expect(classifyRequestFailure(new Error("something else"))).toBe("other");
  });

  it("反向自查：分类器不是恒返回同一值（否则四态等于没分）", () => {
    const kinds = new Set([
      classifyRequestFailure(new HttpNetworkError()),
      classifyRequestFailure(new HttpApiError(401, "x")),
      classifyRequestFailure(new HttpApiError(500, "x")),
    ]);
    expect(kinds.size).toBe(3);
  });
});
