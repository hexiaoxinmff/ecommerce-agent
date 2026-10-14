/**
 * 第十二阶段 Result First：智能分析页验收测试。
 *
 * 覆盖任务书 §十二 的 8 个场景：
 *   1. success → Result First（KPI 第一视觉，流程/SQL/Trace 默认折叠）
 *   2. success → Trace collapsed
 *   3. expand Trace / 执行过程 / SQL → 内容正常
 *   4. SQL collapsed / expanded
 *   5. backend unavailable（不出现 Demo / 假结果）
 *   6. analysis error（Agent 级失败）
 *   7. loading
 *   8. chart result（多行结果，图表属于结果区）
 *
 * 全部走 mock fetch（不调真实 LLM），口径与 test/integration.test.tsx 一致。
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// jsdom 无 canvas 2D 上下文：mock 掉 echarts 渲染（ChartCard 仅需生命周期可用）
vi.mock("echarts", () => ({
  init: () => ({ setOption: () => undefined, resize: () => undefined, dispose: () => undefined }),
}));

import { AnalysisPage } from "./AnalysisPage";
import { jsonResponse } from "../test/helpers";

const HEALTH_OK = {
  status: "ok",
  service: "ecommerce-analysis-agent",
  database: { status: "ok", type: "sqlite", name: "ecommerce.db" },
};

function traceEvent(
  sequence: number,
  node: string,
  status: "success" | "error" = "success",
  outputSummary: Record<string, unknown> = {},
) {
  return {
    sequence,
    node,
    status,
    duration_ms: 1.5 * sequence,
    message: "",
    input_summary: {},
    output_summary: outputSummary,
  };
}

const SINGLE_EXEC = {
  columns: ["total_registered_users"],
  rows: [[2000]],
  row_count: 1,
  truncated: false,
  execution_time_ms: 2,
};

const MULTI_EXEC = {
  columns: ["product", "sales"],
  rows: [
    ["商品A", 944485.34],
    ["商品B", 812300.1],
    ["商品C", 755001.0],
  ],
  row_count: 3,
  truncated: false,
  execution_time_ms: 3,
};

/** AgentResult 基线（真实契约字段），按用例覆写 */
function agentResult(overrides: Record<string, unknown> = {}) {
  return {
    question: "平台注册用户有多少？",
    success: true,
    generated_sql: "SELECT COUNT(*) AS total_registered_users FROM users",
    repaired_sql: "",
    execution_result: null,
    execution_error: "",
    repair_reason: "",
    repair_error: "",
    execute_count: 1,
    repair_count: 0,
    final_error: "",
    trace: [traceEvent(1, "schema_link"), traceEvent(2, "sql_execute", "success", { row_count: 1 })],
    total_time_ms: 7400,
    http_status: null,
    error_type: "",
    ...overrides,
  };
}

const SINGLE_SUCCESS = agentResult({
  question: "平台注册用户有多少？",
  execution_result: SINGLE_EXEC,
});

const MULTI_SUCCESS = agentResult({
  question: "销售额最高的 5 个商品是什么？",
  generated_sql: "SELECT product, SUM(sales) AS sales FROM order_items GROUP BY product ORDER BY sales DESC LIMIT 3",
  execution_result: MULTI_EXEC,
  trace: [
    traceEvent(1, "schema_link"),
    traceEvent(2, "fewshot_retrieve"),
    traceEvent(3, "sql_generate"),
    traceEvent(4, "sql_safety"),
    traceEvent(5, "sql_execute", "success", { row_count: 3 }),
    traceEvent(6, "result"),
  ],
});

const AGENT_FAILURE = agentResult({
  success: false,
  execution_result: null,
  execute_count: 2,
  repair_count: 1,
  repair_error: "SQL 语法错误已修复一次",
  final_error: "生成的 SQL 无法执行：no such table: order_item",
  trace: [traceEvent(1, "schema_link"), traceEvent(2, "sql_execute", "error")],
  total_time_ms: 5120,
});

type FetchOptions = {
  /** analyze 请求直接网络失败（后端不可用） */
  rejectAnalyze?: boolean;
  /** analyze 请求永不返回（观察 loading 态） */
  hangAnalyze?: boolean;
  /** 后端整体不可达（连 /api/health 也失败） */
  backendDown?: boolean;
};

function installFetch(result: Record<string, unknown>, options: FetchOptions = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (options.backendDown) throw new TypeError("fetch failed");
    if (url.includes("/api/health")) return jsonResponse(HEALTH_OK);
    if (method === "POST" && url.includes("/api/agent/analyze")) {
      if (options.rejectAnalyze) throw new TypeError("fetch failed");
      if (options.hangAnalyze) return new Promise<Response>(() => {});
      return jsonResponse({ success: true, result, error: "" });
    }
    throw new Error(`unhandled ${method} ${url}`);
  });
}

async function askAndAwaitResult(user: ReturnType<typeof userEvent.setup>, question: string) {
  await user.type(screen.getByLabelText("输入自然语言查询问题"), question);
  await user.click(screen.getByRole("button", { name: "开始分析" }));
}

describe("AnalysisPage（第十二阶段 Result First）", () => {
  it("场景1+2：success 单值结果 → KPI 第一视觉；执行流程 / SQL / Trace 默认折叠", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(SINGLE_SUCCESS));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "平台注册用户有多少？");

    // KPI 第一视觉：值 + 列名 + 完成态 + 真实耗时
    await waitFor(() => expect(screen.getByTestId("result-kpi")).toBeInTheDocument());
    expect(screen.getByTestId("result-kpi")).toHaveTextContent("2,000");
    expect(screen.getByTestId("result-kpi")).toHaveTextContent("total_registered_users");
    expect(screen.getByText("分析完成")).toBeInTheDocument();
    expect(screen.getByText("7.4 s")).toBeInTheDocument();
    // 结果表（SQL 查询结果）也在结果卡内
    expect(document.querySelector(".result-table__grid")).not.toBeNull();

    // Result First：流程 / SQL / Trace 默认全部折叠
    expect(screen.queryByText("Agent 执行流程")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent Trace")).not.toBeInTheDocument();
    expect(screen.queryByText(/SELECT COUNT/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看执行过程/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "查看 SQL" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /查看 Trace/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("场景3+4：展开 SQL / 执行过程 / Trace 内容正常，且可再次收起", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(SINGLE_SUCCESS));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "平台注册用户有多少？");
    await waitFor(() => expect(screen.getByTestId("result-kpi")).toBeInTheDocument());

    // SQL：先展开（此时执行过程仍折叠，SELECT 语句只出现一处）
    const sqlToggle = screen.getByRole("button", { name: /查看 SQL/ });
    await user.click(sqlToggle);
    expect(screen.getByText(/SELECT COUNT/i)).toBeInTheDocument();
    expect(sqlToggle).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "收起 SQL" }));
    expect(screen.queryByText(/SELECT COUNT/i)).not.toBeInTheDocument();

    // 执行过程：7 阶段完整展开
    await user.click(screen.getByRole("button", { name: /查看执行过程/ }));
    expect(screen.getByText("Agent 执行流程")).toBeInTheDocument();
    expect(screen.getByText("问题理解")).toBeInTheDocument();
    expect(screen.getByText("SQL 执行", { selector: ".wf-stage__name" })).toBeInTheDocument();

    // Trace：真实节点渲染
    await user.click(screen.getByRole("button", { name: /查看 Trace/ }));
    expect(screen.getByText("Agent Trace")).toBeInTheDocument();
    expect(screen.getByText("schema_link")).toBeInTheDocument();
    expect(screen.getByText("sql_execute")).toBeInTheDocument();
  });

  it("场景5：backend unavailable → 后端不可用 + 重新加载，不出现 Demo / 假结果", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(SINGLE_SUCCESS, { backendDown: true }));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "平台注册用户有多少？");

    await waitFor(() => expect(screen.getByText("后端服务不可用")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("请检查后端是否启动");

    // 三条硬红线：无 Demo 横幅、无假 KPI、无静态结果
    expect(screen.queryByTestId("result-kpi")).not.toBeInTheDocument();
    expect(screen.queryByText("2,000")).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo 模式/)).not.toBeInTheDocument();
  });

  it("场景6：Agent 级分析失败 → 显示原因与重新分析，证据可展开，无假结果", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(AGENT_FAILURE));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "平台注册用户有多少？");

    await waitFor(() => expect(screen.getByText("分析未完成")).toBeInTheDocument());
    expect(screen.getByText(/no such table: order_item/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新分析" })).toBeInTheDocument();
    expect(screen.queryByTestId("result-kpi")).not.toBeInTheDocument();

    // 失败诊断证据保留：SQL / 执行过程 / Trace 可展开
    expect(screen.getByRole("button", { name: "查看 SQL" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看执行过程/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看 Trace/ })).toBeInTheDocument();
  });

  it("场景7：loading → 显示分析中状态与进度流程，无任何结果", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(SINGLE_SUCCESS, { hangAnalyze: true }));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "平台注册用户有多少？");

    expect(screen.getByText("分析中")).toBeInTheDocument();
    expect(screen.getByText("Agent 正在理解问题并生成 SQL")).toBeInTheDocument();
    // 进度流程在 loading 期间可见（成功后折叠进证据区）
    expect(screen.getByText("Agent 执行流程")).toBeInTheDocument();
    expect(screen.queryByTestId("result-kpi")).not.toBeInTheDocument();
  });

  it("场景8：chart result 多行结果 → 表格 + 图表属于结果区，且位于证据区之前，无 KPI", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(MULTI_SUCCESS));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "销售额最高的 5 个商品是什么？");

    await waitFor(() => expect(screen.getByText("结果可视化")).toBeInTheDocument());
    expect(screen.queryByTestId("result-kpi")).not.toBeInTheDocument();
    expect(document.querySelector(".result-table__grid tbody tr")).not.toBeNull();

    // DOM 顺序：结果 → 图表 → 证据（执行证据在图表之后）
    const resultHead = screen.getByText("分析结果");
    const chartHead = screen.getByText("结果可视化");
    const evidenceHead = screen.getByText("执行证据");
    expect(
      resultHead.compareDocumentPosition(chartHead) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    expect(
      chartHead.compareDocumentPosition(evidenceHead) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    // 流程默认折叠
    expect(screen.queryByText("Agent 执行流程")).not.toBeInTheDocument();
  });

  it("可访问性：折叠面板可键盘操作（Enter 展开，aria-expanded 同步）", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", installFetch(SINGLE_SUCCESS));
    render(<AnalysisPage />);

    await askAndAwaitResult(user, "平台注册用户有多少？");
    await waitFor(() => expect(screen.getByTestId("result-kpi")).toBeInTheDocument());

    const toggle = screen.getByRole("button", { name: /查看执行过程/ });
    toggle.focus();
    await user.keyboard("{Enter}");

    expect(screen.getByText("Agent 执行流程")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看执行过程/ })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("Phase 15 P0-3：首页问题自动执行（真实 Agent 链路）", () => {
  it("initialQuestion 挂载即自动分析，且消费回调恰好一次", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/agent/analyze")) {
        return jsonResponse({ success: true, result: SINGLE_SUCCESS, data_as_of: "2026-09-12" });
      }
      if (url.includes("/api/health")) return jsonResponse(HEALTH_OK);
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onConsumed = vi.fn();

    render(
      <AnalysisPage initialQuestion="哪个地区的用户最多？" onInitialQuestionConsumed={onConsumed} />,
    );

    // 输入框自动带上首页问题
    await waitFor(() =>
      expect(screen.getByLabelText("输入自然语言查询问题")).toHaveValue("哪个地区的用户最多？"),
    );
    // 真实调用了 Agent API（载荷携带该问题）
    await waitFor(() => expect(screen.getByText("分析完成")).toBeInTheDocument());
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/agent/analyze"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      question: "哪个地区的用户最多？",
    });
    expect(onConsumed).toHaveBeenCalledTimes(1);
  });

  it("结果区展示数据截至（P0-1 最小版 as_of）", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/agent/analyze")) {
        return jsonResponse({ success: true, result: SINGLE_SUCCESS, data_as_of: "2026-09-12" });
      }
      if (url.includes("/api/health")) return jsonResponse(HEALTH_OK);
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AnalysisPage initialQuestion="本月销售额是多少？" />);
    await waitFor(() =>
      expect(screen.getByText(/数据截至 2026-09-12/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/销售额口径：商品明细金额合计（排除已取消订单）/)).toBeInTheDocument();
  });
});
