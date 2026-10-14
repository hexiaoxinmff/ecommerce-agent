/**
 * Header 测试（第九阶段 Phase E：Health / Runtime 状态统一）。
 *
 * 保护的核心契约：
 * 1. **绝不硬编码「已连接」** —— 没有拿到 `database.status === "ok"` 的证据时，
 *    页面上不得出现「已连接」；
 * 2. **`unknown` 不降级** —— health 请求失败时显示「状态未知」，
 *    而不是继续挂着绿色「已连接」（这正是本次要消灭的失真状态）；
 * 3. **LLM 只说「已配置」** —— `/api/health` 不发起 LLM 网络请求，
 *    它没有能力证明上游可达，因此徽标文案不得出现「可用 / 已连接」这类可用性断言。
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { jsonResponse } from "../test/helpers";
import { Header } from "./Header";

function renderHeader() {
  return render(
    <AuthProvider>
      <Header />
    </AuthProvider>,
  );
}

function stubHealth(response: () => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/health")) return await response();
    throw new Error(`unhandled fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const HEALTH_OK = {
  status: "ok",
  service: "ecommerce-analysis-agent",
  database: { status: "ok", type: "sqlite", name: "ecommerce.db" },
  llm: { provider: "bailian", model: "qwen3.7-flash" },
};

/** LLM 徽标（靠 tooltip 精确定位，避免与数据库徽标串味） */
function llmTag(): HTMLElement {
  return screen.getByTitle(/只反映后端环境配置/);
}

describe("Header 连接状态（Phase E）", () => {
  it("请求未返回时显示「连接中」，不得先显示「已连接」", () => {
    stubHealth(() => new Promise<Response>(() => undefined /* 挂起 */));
    renderHeader();

    expect(screen.getByText(/连接中/)).toBeInTheDocument();
    expect(screen.queryByText(/已连接/)).not.toBeInTheDocument();
  });

  it("health 返回 ok：显示「SQLite · 已连接」与「已配置 · provider · model」", async () => {
    stubHealth(() => jsonResponse(HEALTH_OK));
    renderHeader();

    await waitFor(() => expect(screen.getByText(/SQLite · 已连接/)).toBeInTheDocument());
    expect(llmTag()).toHaveTextContent("已配置 · bailian · qwen3.7-flash");
    // 已配置 ≠ 可用：不得出现可用性断言
    expect(llmTag().textContent ?? "").not.toMatch(/可用|已连接/);
  });

  it("health 请求失败：显示「状态未知」，绝不降级成「已连接」", async () => {
    stubHealth(() => Promise.reject(new TypeError("Failed to fetch")));
    renderHeader();

    await waitFor(() => expect(screen.getByText(/状态未知/)).toBeInTheDocument());
    expect(screen.queryByText(/已连接/)).not.toBeInTheDocument();
  });

  it("health 200 但 database.status = error：显示「不可用」而非「已连接」", async () => {
    stubHealth(() =>
      jsonResponse({
        ...HEALTH_OK,
        status: "degraded",
        database: { status: "error", type: "sqlite", name: "ecommerce.db" },
      }),
    );
    renderHeader();

    await waitFor(() => expect(screen.getByText(/SQLite · 不可用/)).toBeInTheDocument());
    expect(screen.queryByText(/已连接/)).not.toBeInTheDocument();
  });

  it("llm 字段缺失：显示中性占位「—」，不伪造模型名", async () => {
    stubHealth(() =>
      jsonResponse({
        status: "ok",
        service: "ecommerce-analysis-agent",
        database: { status: "ok", type: "sqlite", name: "ecommerce.db" },
      }),
    );
    renderHeader();

    await waitFor(() => expect(llmTag()).toHaveTextContent("—"));
    expect(llmTag().textContent ?? "").not.toMatch(/bailian|qwen/);
  });
});
