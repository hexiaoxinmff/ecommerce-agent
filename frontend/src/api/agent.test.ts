/**
 * Agent API 测试：请求自动附加 Bearer token；非 2xx → AgentApiError（契约不变）。
 */

import { describe, expect, it, vi } from "vitest";

import { analyzeQuestion, AgentApiError } from "./agent";
import { headerOf, jsonResponse, seedSession } from "../test/helpers";

const AGENT_OK = {
  success: true,
  result: {
    question: "q",
    success: true,
    generated_sql: "SELECT 1",
    repaired_sql: "",
    execution_result: {
      columns: ["1"],
      rows: [["1"]],
      row_count: 1,
      truncated: false,
      execution_time_ms: 1,
    },
    execution_error: "",
    repair_reason: "",
    repair_error: "",
    execute_count: 1,
    repair_count: 0,
    final_error: "",
    trace: [],
    total_time_ms: 5,
    http_status: null,
    error_type: "",
  },
  error: "",
};

describe("analyzeQuestion", () => {
  it("已登录时自动携带 Bearer token", async () => {
    seedSession("tok_agent");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      jsonResponse(AGENT_OK),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await analyzeQuestion("哪个地区用户最多？");

    expect(res.success).toBe(true);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(headerOf(init, "Authorization")).toBe("Bearer tok_agent");
    expect((init.body as string)).toContain("哪个地区用户最多？");
  });

  it("未登录时不带 Authorization 头（由后端返回 401）", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ detail: "Invalid credentials" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(analyzeQuestion("q")).rejects.toBeInstanceOf(AgentApiError);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(headerOf(init, "Authorization")).toBeUndefined();
  });

  it("非 2xx 抛出 AgentApiError（status 与文案保留）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ error: "Mimo request failed" }, 503)),
    );

    const err = await analyzeQuestion("q").catch((e) => e);
    expect(err).toBeInstanceOf(AgentApiError);
    expect((err as AgentApiError).status).toBe(503);
    expect((err as AgentApiError).message).toBe("Mimo request failed");
  });
});
