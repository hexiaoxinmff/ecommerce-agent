/**
 * HomePage 测试（第九阶段 Phase D）：真实数据 / API 失败 / 加载中 / 空数据 四态。
 *
 * 重点保护的契约：
 * 1. **失败绝不静默回退到任何静态数据**（`data/demo.ts` 已于第九阶段 Phase G 删除）
 *    —— 断言其历史静态常量（¥7,662,921 等）在任何状态下都不出现在页面上；
 * 2. **删除失真文案** —— 断言「Demo 模式：静态演示数据，未连接后端」不再出现；
 * 3. **overview 必须带 Bearer** —— 断言请求携带 Authorization（决策 D6
 *    于 2026-09-28 反转为「必须登录」）；
 * 4. **`as_of` 必须上屏** —— 断言出现「数据截至 2026-09-12」。
 *
 * Phase F（2026-09-28）新增：首页会同时请求 `GET /api/history`（最近动态），
 * 因此 fetch mock 必须为它提供路由；并新增一条断言「旧占位块已删除」。
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// jsdom 无 canvas 2D 上下文：mock 掉 echarts 渲染（ChartCard 仅需生命周期可用）
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => undefined, resize: () => undefined, dispose: () => undefined }),
}));

import { HomePage } from "./HomePage";
import { jsonResponse, seedSession } from "../test/helpers";

/** 与真实库一致的一组概览数据（值取自 2026-10-02 实测，Phase 15 P0-2 明细口径） */
const OVERVIEW = {
  as_of: "2026-09-12",
  generated_at: "2026-09-28T03:00:00+00:00",
  kpis: {
    month_sales: { label: "本月销售额", value: 826080.07, unit: "元", month: "2026-09" },
    month_orders: { label: "订单量", value: 234, unit: "单", month: "2026-09" },
    users_total: { label: "平台注册用户", value: 2000, unit: "人", month: null },
    avg_order_value: { label: "客单价", value: 3274.75, unit: "元/单", month: "2026-09" },
  },
  sales_trend: [
    { month: "2026-07", sales: 1867961.02 },
    { month: "2026-08", sales: 2314476.77 },
  ],
  category_distribution: [
    { category: "家用电器", sales: 8290243.71, quantity: 2959 },
    { category: "电脑办公", sales: 6556561.93, quantity: 2632 },
  ],
  top_products: [
    { rank: 1, product: "恒源祥笔记本电脑Plus", quantity: 101, sales: 944485.34 },
    { rank: 2, product: "良品铺子智能手机Air", quantity: 107, sales: 833577.08 },
  ],
};

const EMPTY_OVERVIEW = {
  as_of: null,
  generated_at: "2026-09-28T03:00:00+00:00",
  kpis: {
    month_sales: { label: "本月销售额", value: 0, unit: "元", month: null },
    month_orders: { label: "订单量", value: 0, unit: "单", month: null },
    users_total: { label: "平台注册用户", value: 0, unit: "人", month: null },
    avg_order_value: { label: "客单价", value: 0, unit: "元/单", month: null },
  },
  sales_trend: [],
  category_distribution: [],
  top_products: [],
};

const HEALTH = {
  status: "ok",
  service: "ecommerce-analysis-agent",
  database: { status: "ok", type: "sqlite", name: "ecommerce.db" },
  llm: { provider: "bailian", model: "qwen3.7-flash" },
};

const DB_INFO = {
  database: "ecommerce.db",
  tables: 5,
  users: 2000,
  categories: 30,
  products: 500,
  orders: 10000,
  order_items: 30457,
};

/** demo.ts 的静态假常量（审计报告 §2.4）—— 任何状态下都不允许出现在页面上 */
const DEMO_CONSTANTS = ["¥7,662,921", "1,284", "¥352.6", "星耀 AI 智能音箱 Pro", "Demo 模式"];

function installHomeFetch(
  overviewRoute: () => Response | Promise<Response>,
  historyRoute: () => Response | Promise<Response> = () =>
    jsonResponse({ items: [], page: 1, page_size: 5, total: 0 }),
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/insights/overview")) return await overviewRoute();
    if (url.includes("/api/history")) return await historyRoute();
    if (url.includes("/api/health")) return jsonResponse(HEALTH);
    if (url.includes("/api/system/database")) return jsonResponse(DB_INFO);
    throw new Error(`unhandled fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function expectNoDemoConstants() {
  for (const constant of DEMO_CONSTANTS) {
    expect(screen.queryByText(constant)).not.toBeInTheDocument();
  }
}

describe("HomePage 三态", () => {
  it("loading：KPI 显示占位、状态文案为加载中，且不出现任何 demo 常量", async () => {
    installHomeFetch(() => new Promise<Response>(() => undefined /* 挂起 */));
    render(<HomePage />);

    expect(screen.getByText("正在加载实时业务数据…")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    expectNoDemoConstants();
  });

  it("ready：KPI / Top5 / 图表副标题全部来自真实数据，并展示数据截止日", async () => {
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage />);

    // KPI：真实值（非 demo 的 7,662,921）
    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());
    expect(screen.getByText("234")).toBeInTheDocument();
    expect(screen.getByText("¥3,274.75")).toBeInTheDocument();
    // Top5：真实商品名（非 demo 的「星耀 AI 智能音箱 Pro」）
    expect(screen.getByText("恒源祥笔记本电脑Plus")).toBeInTheDocument();
    expect(screen.getByText("良品铺子智能手机Air")).toBeInTheDocument();
    // 数据截止日必须上屏
    expect(screen.getAllByText(/数据截至 2026-09-12/).length).toBeGreaterThan(0);
    // 状态文案指向真实接口
    expect(screen.getByText(/来源 GET \/api\/insights\/overview/)).toBeInTheDocument();

    expectNoDemoConstants();
  });

  it("ready：Top 商品副标题写明排序指标口径", async () => {
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage />);
    await waitFor(() =>
      expect(screen.getByText(/按销售额排序（商品明细口径） · 真实业务数据/)).toBeInTheDocument(),
    );
  });

  it("error：显示失败态与重试入口，**不回退到任何静态数据**", async () => {
    installHomeFetch(() =>
      jsonResponse({ detail: "数据库不可用，请确认 db/ecommerce.db 存在且可读。" }, 503),
    );
    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText("实时业务数据加载失败")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
    expect(screen.getByText(/页面不会回退到任何静态演示数据/)).toBeInTheDocument();
    expect(screen.getAllByText("加载失败").length).toBeGreaterThan(0);
    // 关键：失败时页面上不得出现 demo 常量
    expectNoDemoConstants();
    // 也不得出现「未连接后端」这类失真文案
    expect(screen.queryByText(/未连接后端/)).not.toBeInTheDocument();
  });

  it("error → 重试成功：切回 ready 并渲染真实数据", async () => {
    const user = userEvent.setup();
    let calls = 0;
    installHomeFetch(() => {
      calls += 1;
      return calls === 1
        ? jsonResponse({ detail: "数据库不可用" }, 503)
        : jsonResponse(OVERVIEW);
    });
    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText("实时业务数据加载失败")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "重新加载" }));

    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());
    expect(screen.queryByText("实时业务数据加载失败")).not.toBeInTheDocument();
  });

  it("空数据：as_of 为空 + 空数组时显示 0 与「暂无数据」，不抛错也不造假", async () => {
    installHomeFetch(() => jsonResponse(EMPTY_OVERVIEW));
    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("暂无数据")).toBeInTheDocument());
    // 本月销售额与客单价在空数据下都是 ¥0.00（两处）
    expect(screen.getAllByText("¥0.00").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    expectNoDemoConstants();
  });
});

describe("HomePage 契约", () => {
  it("overview 请求必须携带 Authorization（决策 D6 反转：必须带 Bearer）", async () => {
    seedSession("tok_must_be_sent");
    const fetchMock = installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage />);
    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());

    const call = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/insights/overview"),
    )!;
    const headers = (call[1] as RequestInit | undefined)?.headers as
      | Record<string, string>
      | undefined;
    // 反向保护：若有人把 auth 改回 false，这条会立刻变红
    expect(headers?.["Authorization"]).toBe("Bearer tok_must_be_sent");
  });

  it("401：提示会话失效而非「后端故障」，且仍不回退任何静态数据", async () => {
    seedSession("tok_expired");
    installHomeFetch(() =>
      jsonResponse({ detail: "Invalid credentials" }, 401),
    );
    render(<HomePage />);

    // 同一文案会出现在「错误卡片」与底部状态栏两处，故用 getAllByText
    await waitFor(() =>
      expect(screen.getAllByText(/登录状态已失效，请重新登录后查看业务数据/).length).toBeGreaterThan(0),
    );
    // 不得把鉴权失败误报成后端/数据库故障
    expect(screen.queryByText(/请确认后端已启动/)).not.toBeInTheDocument();
    expect(screen.queryByText(/数据库不可用/)).not.toBeInTheDocument();
    expectNoDemoConstants();
  });

  it("已删除失真文案「Demo 模式：静态演示数据，未连接后端」", async () => {
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage />);
    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());

    expect(screen.queryByText("Demo 模式：静态演示数据，未连接后端")).not.toBeInTheDocument();
    expect(screen.queryByText(/未连接后端/)).not.toBeInTheDocument();
  });

  it("未拿到数据时禁用「进入汇报模式」，ready 后可用", async () => {
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage />);
    const button = screen.getByRole("button", { name: "进入汇报模式" });
    expect(button).toBeDisabled();
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("最近动态（Phase F）：渲染真实 /api/history 记录，且旧占位块已删除", async () => {
    installHomeFetch(
      () => jsonResponse(OVERVIEW),
      () =>
        jsonResponse({
          items: [
            {
              id: 7,
              question: "上月各品类销售额排名？",
              sql: "SELECT 1",
              success: true,
              error_message: "",
              result_summary: "5 行",
              row_count: 5,
              total_time_ms: 120.5,
              created_at: "2026-09-28T09:10:20+00:00",
            },
          ],
          page: 1,
          page_size: 5,
          total: 1,
        }),
    );
    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText("上月各品类销售额排名？")).toBeInTheDocument(),
    );
    // 状态行必须指向真实接口，而不是任何占位说法
    expect(screen.getByText(/来源 GET \/api\/history/)).toBeInTheDocument();
    // 旧占位块（失真文案）必须彻底消失
    expect(screen.queryByText(/阶段 1 保留占位结构/)).not.toBeInTheDocument();
    expect(screen.queryByText(/P1 · 历史记录能力/)).not.toBeInTheDocument();
    expectNoDemoConstants();
  });
});

describe("Phase 15 P0-3：首页真实 Agent 链路（假分析已删除）", () => {
  it("提问提交 → 携带问题回调 onStartAnalysis（真实入口，非固定结果）", async () => {
    const user = userEvent.setup();
    const onStartAnalysis = vi.fn();
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage onStartAnalysis={onStartAnalysis} />);

    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());
    const input = screen.getByLabelText("输入自然语言查询问题");
    await user.type(input, "哪个地区的用户最多？");
    await user.click(screen.getByRole("button", { name: "开始分析" }));

    expect(onStartAnalysis).toHaveBeenCalledTimes(1);
    expect(onStartAnalysis).toHaveBeenCalledWith("哪个地区的用户最多？");
  });

  it("空输入提交 → 以默认示例问题进入真实链路", async () => {
    const user = userEvent.setup();
    const onStartAnalysis = vi.fn();
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage onStartAnalysis={onStartAnalysis} />);

    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "开始分析" }));
    expect(onStartAnalysis).toHaveBeenCalledWith("本月销售额是多少？");
  });

  it("假分析结果区已删除：页面不存在旧假链路的固定结果与演示进度文案", async () => {
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage onStartAnalysis={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());

    // 旧假链路文案（AnalysisFlow 假结果区/演示说明）必须彻底消失
    expect(screen.queryByText(/真实只读聚合接口/)).not.toBeInTheDocument();
    expect(screen.queryByText(/未真实执行 Agent/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Agent 正在执行/)).not.toBeInTheDocument();
  });

  it("KPI 口径上屏（P0-2）：销售额与客单价卡片分别标注口径", async () => {
    installHomeFetch(() => jsonResponse(OVERVIEW));
    render(<HomePage onStartAnalysis={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("¥826,080.07")).toBeInTheDocument());

    expect(screen.getByText(/口径：商品明细金额合计，排除已取消订单/)).toBeInTheDocument();
    expect(screen.getByText(/口径：订单实付金额均值，排除已取消订单/)).toBeInTheDocument();
  });
});
