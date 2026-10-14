import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartCard } from "../components/ChartCard";
import { DbStatus } from "../components/DbStatus";
import { Hero } from "../components/Hero";
import { IconCart, IconPrice, IconUsers, IconWallet } from "../components/Icons";
import { KpiCard } from "../components/KpiCard";
import { PresentationOverlay } from "../components/PresentationOverlay";
import { RecentActivity } from "../components/RecentActivity";
import { TopProducts } from "../components/TopProducts";
import { categorySalesOption, presentationChartOption, salesTrendOption } from "../data/charts";
import { agentStages } from "../data/uiCopy";
import { fetchOverview, toOverviewErrorHint, toOverviewErrorMessage, type OverviewDto } from "../api/insights";

/**
 * 首页（第九阶段 Phase D：接入真实业务数据）。
 *
 * 数据来源：`GET /api/insights/overview`（后端只读聚合 + Bearer 鉴权）。
 *
 * 访问控制：本页已纳入 `App.tsx` 的 `ProtectedRoute`（决策 D6 于 2026-09-28
 * 反转为「必须带 Bearer」），未登录时由路由守卫直接渲染登录页 ——
 * 因此**页面内部不做 `if (!user)` 判断**（与 AuthContext 的既有约定一致）。
 *
 * 三条硬约束（对应任务书 §八 / §九 / §十二）：
 * 1. **三态显式**：`loading` → `ready` → `error`，各自渲染不同内容；
 * 2. **失败禁止静默回退**：请求失败即清空 `overview` 并进入 `error` 态，
 *    **绝不回退到任何静态数据**（`data/demo.ts` 已于 Phase G 删除，
 *    `DbStatus.tsx` 已是同一模式）；
 * 3. **不编数字**：接口不返回趋势百分比，因此 KPI 卡**不显示涨跌箭头**。
 *
 * Phase 15（P0-3，2026-10-02）：**首页假分析已删除。** 原先首页提问框触发
 * 纯定时器动画（不调用任何 API），完成后固定显示「本月销售额」并打
 * 「真实只读聚合」徽标 —— 用户问任何问题都得到同一个数字，是最危险的
 * 欺骗性 UX。现在首页提问框是**真实入口**：携带问题跳转「智能分析」页，
 * 由 `AnalysisPage` 真实调用 Agent API（见 `App.tsx` 的 pendingQuestion 链路）。
 *
 * Phase 15（P0-2）：KPI 口径上屏 —— 销售额=商品明细金额合计（排除已取消
 * 订单）；客单价=订单实付金额均值。与后端 KPI Definition
 * （`backend/app/dbprofile/kpi_definitions.py`）完全一致。
 */

/** KPI 口径上屏文案（P0-2）：与后端 KPI Definition 完全一致 */
const SALES_CALIBER_NOTE = "口径：商品明细金额合计，排除已取消订单";
const AOV_CALIBER_NOTE = "口径：订单实付金额均值，排除已取消订单";

type LoadStatus = "loading" | "ready" | "error";

export type HomePageProps = {
  /**
   * Phase 15（P0-3）：首页提问的真实入口 —— 携带问题跳转「智能分析」页，
   * 由 AnalysisPage 真实调用 Agent API。
   */
  onStartAnalysis?: (question: string) => void;
};

/** KPI 卡在加载/失败态下的占位标题（纯 UI 文案，不承载任何数值） */
const KPI_PLACEHOLDER_LABELS = ["本月销售额", "订单量", "平台注册用户", "客单价"];

/** 金额格式化（接口单位为元） */
function formatMoney(value: number): string {
  return `¥${value.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** 计数格式化 */
function formatCount(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

/** 非 ready 态的图表占位（明确显示原因，不画任何假数据） */
function ChartPlaceholder({ title, message }: { title: string; message: string }) {
  return (
    <section className="card chart-card">
      <div className="chart-card__head">
        <h2 className="section-title">{title}</h2>
        <span className="section-sub">{message}</span>
      </div>
      <div
        className="chart-card__body"
        style={{
          height: 280,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span className="section-sub">—</span>
      </div>
    </section>
  );
}

export function HomePage({ onStartAnalysis }: HomePageProps) {
  const [query, setQuery] = useState("");
  const [presentation, setPresentation] = useState(false);

  // ---- 真实业务数据（三态） ----
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [overview, setOverview] = useState<OverviewDto | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [errorHint, setErrorHint] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    void (async () => {
      try {
        const data = await fetchOverview(controller.signal);
        if (controller.signal.aborted) return;
        setOverview(data);
        setErrorMessage("");
        setErrorHint("");
        setStatus("ready");
      } catch (err) {
        if (controller.signal.aborted) return;
        // 失败即清空：不留缓存，也不回退到任何静态/演示数据
        setOverview(null);
        setStatus("error");
        setErrorMessage(toOverviewErrorMessage(err));
        // 提示按错误类型分派：401 不得说成「后端故障」（见 insights.ts 注释）
        setErrorHint(toOverviewErrorHint(err) ?? "");
      }
    })();

    return () => controller.abort();
  }, [reloadToken]);

  const retry = useCallback(() => {
    setStatus("loading");
    setErrorMessage("");
    setErrorHint("");
    setReloadToken((token) => token + 1);
  }, []);

  /**
   * 「最近动态」点击回填：只把问题写进提问框，**不自动发起查询**。
   * 自动执行会直接产生一次真实 LLM 调用，不该由一次误点触发。
   */
  const pickQuestion = useCallback((question: string) => {
    setQuery(question);
  }, []);

  // Phase 15（P0-3）：首页提问 = 真实入口。空输入回退默认示例问题；
  // 真正的 Agent 执行发生在「智能分析」页（AnalysisPage 挂载后自动运行）。
  const startAnalysis = useCallback(() => {
    const question = query.trim() || "本月销售额是多少？";
    if (query.trim() !== question) setQuery(question);
    onStartAnalysis?.(question);
  }, [query, onStartAnalysis]);

  const kpiIcons = [
    <IconWallet key="s" />,
    <IconCart key="o" />,
    <IconUsers key="u" />,
    <IconPrice key="p" />,
  ];

  const asOfNote = overview?.as_of ? `截至 ${overview.as_of}` : undefined;
  const salesNote = [SALES_CALIBER_NOTE, asOfNote].filter(Boolean).join(" · ");
  const payNote = [AOV_CALIBER_NOTE, asOfNote].filter(Boolean).join(" · ");

  const kpis = useMemo(() => {
    if (!overview) return null;
    const k = overview.kpis;
    return [
      { key: "sales", label: k.month_sales.label, value: formatMoney(k.month_sales.value), unit: k.month_sales.unit, note: salesNote },
      { key: "orders", label: k.month_orders.label, value: formatCount(k.month_orders.value), unit: k.month_orders.unit, note: asOfNote },
      { key: "users", label: k.users_total.label, value: formatCount(k.users_total.value), unit: k.users_total.unit, note: undefined },
      { key: "arpu", label: k.avg_order_value.label, value: formatMoney(k.avg_order_value.value), unit: k.avg_order_value.unit, note: payNote },
    ];
  }, [overview, asOfNote, salesNote, payNote]);

  const trendOption = useMemo(
    () => (overview ? salesTrendOption(overview.sales_trend) : null),
    [overview],
  );
  const categoryOption = useMemo(
    () => (overview ? categorySalesOption(overview.category_distribution) : null),
    [overview],
  );
  const presentationOption = useMemo(
    () => (overview ? presentationChartOption(overview.sales_trend) : null),
    [overview],
  );

  const statusText =
    status === "loading"
      ? "正在加载实时业务数据…"
      : status === "error"
        ? `实时数据加载失败：${errorMessage}`
        : `实时业务数据 · 数据截至 ${overview?.as_of ?? "—"} · 来源 GET /api/insights/overview`;

  return (
    <>
      <Hero query={query} onQueryChange={setQuery} onSubmit={startAnalysis} disabled={false} />

      <section className="kpi-grid fade-in">
        {status === "ready" && kpis
          ? kpis.map((k, i) => (
              <KpiCard
                key={k.key}
                label={k.label}
                value={k.value}
                unit={k.unit}
                note={k.note}
                icon={kpiIcons[i]}
              />
            ))
          : KPI_PLACEHOLDER_LABELS.map((label, i) => (
              <KpiCard
                key={label}
                label={label}
                value="—"
                unit="—"
                note={status === "loading" ? "加载中" : "加载失败"}
                icon={kpiIcons[i]}
              />
            ))}
      </section>

      {status === "error" && (
        <section className="card" style={{ padding: "20px 24px" }}>
          <span className="badge badge-error">
            <span className="dot" />
            实时业务数据加载失败
          </span>
          <p className="section-sub" style={{ margin: "12px 0" }}>
            {errorMessage}
          </p>
          <p className="section-sub" style={{ margin: "0 0 12px" }}>
            页面不会回退到任何静态演示数据。{errorHint}
          </p>
          <button type="button" className="btn-primary" onClick={retry}>
            重新加载
          </button>
        </section>
      )}

      {status === "ready" && overview && trendOption && categoryOption ? (
        <section className="analysis-grid fade-in">
          <ChartCard
            title="销售趋势"
            subtitle={`近 ${overview.sales_trend.length} 个月 · 商品明细口径 · 单位万元 · 数据截至 ${overview.as_of ?? "—"}`}
            option={trendOption}
          />
          <ChartCard
            title="分类销售"
            subtitle={`叶子类目 Top ${overview.category_distribution.length} · 按销售额（商品明细口径） · 单位万元`}
            option={categoryOption}
          />
        </section>
      ) : (
        <section className="analysis-grid fade-in">
          <ChartPlaceholder
            title="销售趋势"
            message={status === "loading" ? "加载中…" : "加载失败，未回退到静态数据"}
          />
          <ChartPlaceholder
            title="分类销售"
            message={status === "loading" ? "加载中…" : "加载失败，未回退到静态数据"}
          />
        </section>
      )}

      <section className="analysis-grid fade-in" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <TopProducts
          items={overview?.top_products ?? []}
          subtitle={`按销售额排序（商品明细口径） · 真实业务数据${overview?.as_of ? `（截至 ${overview.as_of}）` : ""}`}
        />
        <RecentActivity onPickQuestion={pickQuestion} />
      </section>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setPresentation(true)}
          disabled={status !== "ready"}
        >
          进入汇报模式
        </button>
        <span className="section-sub">{statusText}</span>
      </div>

      <DbStatus />

      {presentation && overview && presentationOption && (
        <PresentationOverlay
          question={query || "本月销售额是多少？"}
          stages={agentStages.map((name) => ({ name, status: "done" as const }))}
          resultValue={formatMoney(overview.kpis.month_sales.value)}
          resultUnit={overview.kpis.month_sales.unit}
          chartOption={presentationOption}
          chartAriaLabel="近 7 个月销售趋势"
          footer={`数值来源：GET /api/insights/overview · 数据截至 ${overview.as_of ?? "—"} · 图表单位万元  |  7 阶段链路为界面示意图  |  SQL / Trace 详情默认折叠`}
          onExit={() => setPresentation(false)}
        />
      )}
    </>
  );
}
