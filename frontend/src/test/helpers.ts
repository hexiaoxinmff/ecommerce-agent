/**
 * 测试公共工具：fetch mock 路由安装与响应构造。
 */

import { vi } from "vitest";

export interface MockRoute {
  /** URL / method 匹配 */
  match: (url: string, init: RequestInit | undefined) => boolean;
  /** 响应（可返回 pending Promise 模拟挂起） */
  response: () => Response | Promise<Response>;
}

export function installFetchMock(routes: MockRoute[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const route of routes) {
      if (route.match(url, init)) return await route.response();
    }
    throw new Error(`Unhandled fetch in test: ${url} ${String(init?.method ?? "GET")}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function emptyResponse(status = 204): Response {
  return new Response(null, { status });
}

export function headerOf(init: RequestInit | undefined, name: string): string | undefined {
  const headers = init?.headers as Record<string, string> | undefined;
  return headers?.[name];
}

export function seedSession(accessToken = "tok_test"): void {
  window.localStorage.setItem(
    "ecom.auth.session",
    JSON.stringify({
      accessToken,
      expiresAt: "2099-01-01T00:00:00+00:00",
      user: { id: 1, username: "alice", email: "alice@example.com", is_active: true },
    }),
  );
}
