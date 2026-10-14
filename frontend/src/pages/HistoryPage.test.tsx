/**
 * HistoryPage 测试：loading / empty / error / data 四态，删除成功 / 404 / 失败 / 防重复点击。
 */

import { StrictMode } from "react";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";
import { jsonResponse, seedSession } from "../test/helpers";

const ITEMS = [
  {
    id: 2,
    question: "最新的提问",
    sql: "SELECT 2",
    success: true,
    error_message: "",
    result_summary: "3 行 · 列: region",
    row_count: 3,
    total_time_ms: 88.8,
    created_at: "2026-09-25T10:00:00+00:00",
  },
  {
    id: 1,
    question: "较早的失败提问",
    sql: "SELECT bad",
    success: false,
    error_message: "SQL execution failed",
    result_summary: "",
    row_count: null,
    total_time_ms: 12.5,
    created_at: "2026-09-25T09:00:00+00:00",
  },
];

function historyResponse(items = ITEMS, total = items.length) {
  return { items, page: 1, page_size: 50, total };
}

function installHistoryFetch(overrides: {
  list?: () => Response | Promise<Response>;
  onDelete?: (id: number) => Response | Promise<Response>;
} = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (method === "GET" && url.includes("/api/history")) {
      return overrides.list ? overrides.list() : jsonResponse(historyResponse());
    }
    if (method === "DELETE" && url.includes("/api/history/")) {
      const id = Number(url.split("/").pop());
      return overrides.onDelete ? overrides.onDelete(id) : new Response(null, { status: 204 });
    }
    throw new Error(`unhandled ${method} ${url}`);
  });
}

describe("HistoryPage 状态", () => {
  it("loading：显示正在加载", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>(() => {
            /* 挂起 */
          }),
      ),
    );
    render(<HistoryPage />);
    expect(screen.getByText("正在加载历史记录")).toBeInTheDocument();
  });

  it("empty：暂无查询历史", async () => {
    vi.stubGlobal(
      "fetch",
      installHistoryFetch({ list: () => jsonResponse(historyResponse([], 0)) }),
    );
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("暂无查询历史")).toBeInTheDocument());
  });

  it("error：加载失败 + 重试入口", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 500)));
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("历史记录加载失败")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("data：展示 question / 成功失败标签 / 摘要 / 耗时 / SQL 折叠", async () => {
    vi.stubGlobal("fetch", installHistoryFetch());
    render(<HistoryPage />);

    await waitFor(() => expect(screen.getByText("最新的提问")).toBeInTheDocument());
    expect(screen.getByText("较早的失败提问")).toBeInTheDocument();
    expect(screen.getAllByText("成功").length).toBe(1);
    expect(screen.getAllByText("失败").length).toBe(1);
    expect(screen.getByText(/3 行 · 列: region/)).toBeInTheDocument();
    expect(screen.getByText(/88\.8 ms/)).toBeInTheDocument();
    expect(screen.getByText("失败原因：SQL execution failed")).toBeInTheDocument();
    // SQL 默认折叠在 details 内
    expect(screen.getAllByText("SQL").length).toBe(2);
  });
});

describe("HistoryPage 删除", () => {
  it("删除成功：从列表移除", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      installHistoryFetch({
        onDelete: () => new Response(null, { status: 204 }),
      }),
    );
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("最新的提问")).toBeInTheDocument());

    const row = screen.getByText("最新的提问").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(screen.queryByText("最新的提问")).not.toBeInTheDocument());
    expect(screen.getByText("较早的失败提问")).toBeInTheDocument();
  });

  it("删除 404（记录已不存在）：同样从列表移除", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      installHistoryFetch({
        onDelete: () => jsonResponse({ detail: "History not found" }, 404),
      }),
    );
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("最新的提问")).toBeInTheDocument());

    const row = screen.getByText("最新的提问").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(screen.queryByText("最新的提问")).not.toBeInTheDocument());
    expect(screen.queryByText("删除失败，请重试")).not.toBeInTheDocument();
  });

  it("删除失败（500）：提示错误且条目保留", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      installHistoryFetch({ onDelete: () => jsonResponse({}, 500) }),
    );
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("最新的提问")).toBeInTheDocument());

    const row = screen.getByText("最新的提问").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(screen.getByText("删除失败，请重试")).toBeInTheDocument());
    expect(screen.getByText("最新的提问")).toBeInTheDocument();
  });

  it("删除中：按钮禁用防重复点击", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      installHistoryFetch({
        onDelete: () => new Promise<Response>(() => undefined /* 挂起 */),
      }),
    );
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("最新的提问")).toBeInTheDocument());

    const row = screen.getByText("最新的提问").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));
    await waitFor(() =>
      expect(within(row).getByRole("button", { name: "删除中…" })).toBeDisabled(),
    );
  });

  it("请求自动携带 Bearer token", async () => {
    seedSession("tok_hist");
    const fetchMock = installHistoryFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("最新的提问")).toBeInTheDocument());

    const listCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/history"))!;
    const headers = (listCall[1] as RequestInit).headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok_hist");
  });

  it("StrictMode 下删除：计数恰好减 1（Phase 4 双重递减竞态回归）", async () => {
    // 背景：removeItem 曾在 setItems 的 updater 内调用 setTotal；
    // React 18 StrictMode 开发模式双重调用 updater，导致 total 被连减两次
    // （删除 1 条后瞬时显示「少 2 条」）。本用例在 StrictMode 下锁定修复：
    // 删除 1 条后计数必须立即为 2-1=1。
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installHistoryFetch());
    render(
      <StrictMode>
        <HistoryPage />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.getByText("共 2 条")).toBeInTheDocument());

    const row = screen.getByText("最新的提问").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(screen.getByText("共 1 条")).toBeInTheDocument());
    expect(screen.queryByText("共 0 条")).not.toBeInTheDocument();
  });

  it("StrictMode 下删除最后一条：列表与计数同时清空进入 empty 态", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installHistoryFetch());
    render(
      <StrictMode>
        <HistoryPage />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.getByText("共 2 条")).toBeInTheDocument());

    await user.click(within(screen.getByText("最新的提问").closest("li")!).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(screen.getByText("共 1 条")).toBeInTheDocument());
    await user.click(within(screen.getByText("较早的失败提问").closest("li")!).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(screen.getByText("暂无查询历史")).toBeInTheDocument());
  });
});
