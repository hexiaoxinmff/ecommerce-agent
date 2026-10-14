/**
 * RecentActivity 测试（第九阶段 Phase F）：真实数据 / 加载中 / 失败 / 空数据 四态。
 *
 * 重点保护的契约：
 * 1. **失败绝不静默回退** —— 失败态下不得出现任何静态/占位记录；
 * 2. **旧占位文案彻底消失** —— 「阶段 1 保留占位结构」在任何状态下都不出现；
 * 3. **必须带 Bearer** —— 请求携带 Authorization（后端强制 user_id 隔离）；
 * 4. **不泄漏用户身份** —— 即使响应体里夹带了 username，也不得渲染；
 * 5. **点击回填** —— 点击一条记录以该条 question 调用 onPickQuestion。
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecentActivity } from "./RecentActivity";
import { installFetchMock, jsonResponse, seedSession } from "../test/helpers";

const HOUR_MS = 3_600_000;

function item(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    question: "上月各品类销售额排名？",
    sql: "SELECT 1",
    success: true,
    error_message: "",
    result_summary: "5 行",
    row_count: 5,
    total_time_ms: 120.5,
    created_at: new Date(Date.now() - 3 * HOUR_MS).toISOString(),
    ...overrides,
  };
}

function historyRoute(route: () => Response | Promise<Response>) {
  return installFetchMock([
    {
      match: (url) => url.includes("/api/history"),
      response: route,
    },
  ]);
}

describe("RecentActivity 四态", () => {
  it("loading：显示加载中，且不出现任何假记录或旧占位文案", () => {
    historyRoute(() => new Promise<Response>(() => undefined /* 挂起 */));
    render(<RecentActivity onPickQuestion={() => undefined} />);

    expect(screen.getByText("正在加载最近查询")).toBeInTheDocument();
    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.queryByText(/阶段 1 保留占位结构/)).not.toBeInTheDocument();
    expect(screen.queryByText(/P1 · 历史记录能力/)).not.toBeInTheDocument();
  });

  it("data：渲染真实问题、成功/失败徽标与相对时间，并标明来源接口", async () => {
    historyRoute(() =>
      jsonResponse({
        items: [
          item({ id: 1, question: "上月各品类销售额排名？" }),
          item({ id: 2, question: "哪类商品退货最多？", success: false, error_message: "boom" }),
        ],
        page: 1,
        page_size: 5,
        total: 2,
      }),
    );
    render(<RecentActivity onPickQuestion={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByText("上月各品类销售额排名？")).toBeInTheDocument(),
    );
    expect(screen.getByText("哪类商品退货最多？")).toBeInTheDocument();
    expect(screen.getByText("成功")).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
    // 相对时间由 utils/datetime.ts 统一渲染
    expect(screen.getAllByText("3 小时前").length).toBe(2);
    // 状态行必须指向真实接口
    expect(screen.getByText(/共 2 条 · 仅当前账号 · 来源 GET \/api\/history/)).toBeInTheDocument();
  });

  it("empty：显示「暂无查询历史」，不伪造任何记录", async () => {
    historyRoute(() => jsonResponse({ items: [], page: 1, page_size: 5, total: 0 }));
    render(<RecentActivity onPickQuestion={() => undefined} />);

    await waitFor(() => expect(screen.getByText("暂无查询历史")).toBeInTheDocument());
    expect(screen.getByText("暂无记录")).toBeInTheDocument();
  });

  it("error：显示失败态与重试，**不回退任何静态数据**", async () => {
    historyRoute(() => jsonResponse({ detail: "Invalid credentials" }, 401));
    render(<RecentActivity onPickQuestion={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByText("最近动态加载失败")).toBeInTheDocument(),
    );
    expect(screen.getByText("这里不会回退到任何静态数据。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.queryByText(/阶段 1 保留占位结构/)).not.toBeInTheDocument();
  });

  it("error → 重试成功：切回 data 并渲染真实记录", async () => {
    const user = userEvent.setup();
    let calls = 0;
    historyRoute(() => {
      calls += 1;
      return calls === 1
        ? jsonResponse({ detail: "boom" }, 500)
        : jsonResponse({ items: [item({ question: "重试之后的问题" })], page: 1, page_size: 5, total: 1 });
    });
    render(<RecentActivity onPickQuestion={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByText("最近动态加载失败")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => expect(screen.getByText("重试之后的问题")).toBeInTheDocument());
    expect(screen.queryByText("最近动态加载失败")).not.toBeInTheDocument();
  });
});

describe("RecentActivity 契约", () => {
  it("请求必须携带 Authorization（后端强制 user_id 隔离）", async () => {
    seedSession("tok_recent");
    const fetchMock = historyRoute(() =>
      jsonResponse({ items: [item()], page: 1, page_size: 5, total: 1 }),
    );
    render(<RecentActivity onPickQuestion={() => undefined} />);
    await waitFor(() =>
      expect(screen.getByText("上月各品类销售额排名？")).toBeInTheDocument(),
    );

    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/history"))!;
    const headers = (call[1] as RequestInit | undefined)?.headers as
      | Record<string, string>
      | undefined;
    expect(headers?.["Authorization"]).toBe("Bearer tok_recent");
  });

  it("点击一条记录：以该条 question 调用 onPickQuestion", async () => {
    const user = userEvent.setup();
    const onPickQuestion = vi.fn();
    historyRoute(() =>
      jsonResponse({
        items: [item({ id: 1, question: "第一个问题" }), item({ id: 2, question: "第二个问题" })],
        page: 1,
        page_size: 5,
        total: 2,
      }),
    );
    render(<RecentActivity onPickQuestion={onPickQuestion} />);

    await waitFor(() => expect(screen.getByText("第二个问题")).toBeInTheDocument());
    await user.click(screen.getByText("第二个问题"));

    expect(onPickQuestion).toHaveBeenCalledTimes(1);
    expect(onPickQuestion).toHaveBeenCalledWith("第二个问题");
  });

  it("即使响应体夹带用户身份字段，也不得渲染（§十 隔离）", async () => {
    historyRoute(() =>
      jsonResponse({
        items: [item({ user_id: 42, username: "alice", session_id: "sess-1" })],
        page: 1,
        page_size: 5,
        total: 1,
        user_id: 42,
        username: "alice",
      }),
    );
    render(<RecentActivity onPickQuestion={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByText("上月各品类销售额排名？")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/alice/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sess-1/)).not.toBeInTheDocument();
  });
});
