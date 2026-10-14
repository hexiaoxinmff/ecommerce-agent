/**
 * 集成测试（App 级）：login → 受保护 HistoryPage → 删除 → logout 守卫；
 * 以及 Agent 查询 → HistoryPage 出现记录的链路（API mock，不调真实 LLM）。
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// jsdom 无 canvas 2D 上下文：集成测试 mock 掉 echarts 渲染（ChartCard 仅需生命周期可用）
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => undefined, resize: () => undefined, dispose: () => undefined }),
}));

import App from "../App";
import { analyzeQuestion } from "../api/agent";
import { HistoryPage } from "../pages/HistoryPage";
import { jsonResponse, seedSession } from "./helpers";

const LOGIN_OK = {
  access_token: "tok_flow",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00+00:00",
  user: { id: 1, username: "alice", email: "alice@example.com" },
};

const HISTORY_ONE = {
  items: [
    {
      id: 7,
      question: "上个月总销售额",
      sql: "SELECT SUM(total_amount) FROM orders",
      success: true,
      error_message: "",
      result_summary: "1 行 · 列: SUM(total_amount)",
      row_count: 1,
      total_time_ms: 120.5,
      created_at: "2026-09-25T11:00:00+00:00",
    },
  ],
  page: 1,
  page_size: 50,
  total: 1,
};

/** 安装 App 全量 mock：首页只读接口 + 登录 + 历史 */
function installAppFetch(options: { history?: typeof HISTORY_ONE } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/api/auth/login")) return jsonResponse(LOGIN_OK);
    if (url.includes("/api/auth/me")) {
      return jsonResponse({ id: 1, username: "alice", email: "alice@example.com", is_active: true });
    }
    if (url.includes("/api/auth/logout")) return new Response(null, { status: 204 });
    if (method === "GET" && url.includes("/api/history")) {
      return jsonResponse(options.history ?? HISTORY_ONE);
    }
    if (method === "DELETE" && url.includes("/api/history/7")) {
      return new Response(null, { status: 204 });
    }
    if (url.includes("/api/health")) {
      return jsonResponse({ status: "ok", service: "ecommerce-analysis-agent", database: { status: "ok", type: "sqlite", name: "ecommerce.db" } });
    }
    if (url.includes("/api/insights/overview")) {
      // 第九阶段 Phase D：首页 KPI / 图表 / Top 商品改为真实聚合接口
      return jsonResponse({
        as_of: "2026-09-12",
        generated_at: "2026-09-28T03:00:00+00:00",
        kpis: {
          month_sales: { label: "本月销售额", value: 766292.18, unit: "元", month: "2026-09" },
          month_orders: { label: "订单量", value: 234, unit: "单", month: "2026-09" },
          users_total: { label: "平台注册用户", value: 2000, unit: "人", month: null },
          avg_order_value: { label: "客单价", value: 3274.75, unit: "元/单", month: "2026-09" },
        },
        sales_trend: [{ month: "2026-08", sales: 2206807.1 }],
        category_distribution: [{ category: "家用电器", sales: 8290243.71, quantity: 2959 }],
        top_products: [
          { rank: 1, product: "恒源祥笔记本电脑Plus", quantity: 101, sales: 944485.34 },
        ],
      });
    }
    if (url.includes("/api/system/database")) {
      return jsonResponse({ database: "ecommerce.db", tables: 5, users: 2000, categories: 30, products: 500, orders: 10000, order_items: 30457 });
    }
    if (url.includes("/api/system/schema")) {
      return jsonResponse({ database: "ecommerce.db", tables: [] });
    }
    throw new Error(`unhandled ${method} ${url}`);
  });
}

describe("首页访问控制（决策 D6 反转：overview 必须带 Bearer）", () => {
  it("未登录访问首页 → 渲染登录页，且不发出任何 overview 请求", async () => {
    const fetchMock = installAppFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    // 匿名 → ProtectedRoute 直接渲染登录页（首页已不再是公开页）
    await waitFor(() =>
      expect(screen.getByText("登录后使用智能分析与历史记录")).toBeInTheDocument(),
    );

    // 关键：未登录时根本不该去拉业务数据（拉也是 401，属于无谓请求）
    const overviewCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/insights/overview"),
    );
    expect(overviewCalls).toHaveLength(0);

    // 且页面上不得出现任何 demo 静态常量
    expect(screen.queryByText("¥7,662,921")).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo 模式/)).not.toBeInTheDocument();
  });
});

describe("认证完整链路（App 级）", () => {
  it("未登录访问历史 → 登录页 → 登录成功回到历史 → 删除记录 → 退出登录回到登录页", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installAppFetch());
    render(<App />);

    // 首页已是受保护页 → 匿名时同样呈现登录页；侧边栏仍在（MainLayout 包裹）
    await waitFor(() => expect(screen.getByText("首页")).toBeInTheDocument());

    // 点击侧边栏「历史记录」（匿名时 Header 无同名按钮，可唯一定位）→ 登录页
    await user.click(screen.getByRole("button", { name: "历史记录" }));
    await waitFor(() => expect(screen.getByText("登录后使用智能分析与历史记录")).toBeInTheDocument());

    // 填写登录表单（表单内提交按钮，避免与 Header 的「登录」入口混淆）
    await user.type(screen.getByLabelText("用户名"), "alice");
    await user.type(screen.getByLabelText("密码"), "pw123456");
    const submit = document.querySelector(".login__submit") as HTMLButtonElement;
    await user.click(submit);

    // 登录成功 → 回到历史页 → 出现记录
    await waitFor(() => expect(screen.getByText("上个月总销售额")).toBeInTheDocument());
    expect(screen.getByText("alice")).toBeInTheDocument(); // Header 显示用户名

    // 删除记录
    const row = screen.getByText("上个月总销售额").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(screen.getByText("暂无查询历史")).toBeInTheDocument());

    // 退出登录 → 受保护页回到登录页
    await user.click(screen.getByRole("button", { name: "退出登录" }));
    await waitFor(() => expect(screen.getByText("登录后使用智能分析与历史记录")).toBeInTheDocument());
  });
});

describe("Agent 查询 → 历史记录链路", () => {
  it("Agent 分析成功后，HistoryPage 展示该记录（API 链路，mock LLM）", async () => {
    seedSession("tok_chain");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (method === "POST" && url.includes("/api/agent/analyze")) {
          return jsonResponse({
            success: true,
            result: {
              question: "上个月总销售额",
              success: true,
              generated_sql: "SELECT SUM(total_amount) FROM orders",
              repaired_sql: "",
              execution_result: { columns: ["SUM(total_amount)"], rows: [["123"]], row_count: 1, truncated: false, execution_time_ms: 2 },
              execution_error: "",
              repair_reason: "",
              repair_error: "",
              execute_count: 1,
              repair_count: 0,
              final_error: "",
              trace: [],
              total_time_ms: 120.5,
              http_status: null,
              error_type: "",
            },
            error: "",
          });
        }
        if (method === "GET" && url.includes("/api/history")) return jsonResponse(HISTORY_ONE);
        throw new Error(`unhandled ${method} ${url}`);
      }),
    );

    // Agent 查询（Bearer 自动注入）
    const analysis = await analyzeQuestion("上个月总销售额");
    expect(analysis.success).toBe(true);

    // HistoryPage 展示对应记录
    render(<HistoryPage />);
    await waitFor(() => expect(screen.getByText("上个月总销售额")).toBeInTheDocument());
    expect(screen.getByText(/SUM\(total_amount\) FROM orders/)).toBeInTheDocument();
  });
});
