import { useCallback, useEffect, useRef, useState } from "react";
import { AnalysisFlow, type FlowPhase } from "../components/AnalysisFlow";
import { ChartCard } from "../components/ChartCard";
import { DbStatus } from "../components/DbStatus";
import { Hero } from "../components/Hero";
import { IconCart, IconPrice, IconUsers, IconWallet } from "../components/Icons";
import { KpiCard } from "../components/KpiCard";
import { PresentationOverlay } from "../components/PresentationOverlay";
import { TopProducts } from "../components/TopProducts";
import { categorySalesOption, presentationChartOption, salesTrendOption } from "../data/charts";
import { agentStages, demoResult, kpiData } from "../data/demo";

const STAGE_DURATION_MS = 700; // 每个 Demo 阶段时长（仅视觉演示）

export function HomePage() {
  const [query, setQuery] = useState("");
  const [flowPhase, setFlowPhase] = useState<FlowPhase>("idle");
  const [stageIndex, setStageIndex] = useState(-1);
  const [presentation, setPresentation] = useState(false);
  const timerRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => clearTimer, []);

  const startAnalysis = useCallback(() => {
    if (flowPhase === "running") return;
    clearTimer();

    const question = query.trim() || "本月销售额是多少？";
    if (query.trim() !== question) setQuery(question);

    setFlowPhase("running");
    setStageIndex(0);

    const step = (index: number) => {
      setStageIndex(index);
      if (index >= 6) {
        timerRef.current = window.setTimeout(() => {
          setFlowPhase("done");
          timerRef.current = null;
        }, STAGE_DURATION_MS);
        return;
      }
      timerRef.current = window.setTimeout(() => step(index + 1), STAGE_DURATION_MS);
    };
    timerRef.current = window.setTimeout(() => step(0), STAGE_DURATION_MS);
  }, [query, flowPhase]);

  const cancelAnalysis = useCallback(() => {
    clearTimer();
    setFlowPhase("idle");
    setStageIndex(-1);
  }, []);

  const kpiIcons = [<IconWallet key="s" />, <IconCart key="o" />, <IconUsers key="u" />, <IconPrice key="p" />];

  return (
    <>
      <Hero query={query} onQueryChange={setQuery} onSubmit={startAnalysis} disabled={flowPhase === "running"} />

      <section className="kpi-grid fade-in">
        {kpiData.map((k, i) => (
          <KpiCard
            key={k.id}
            label={k.label}
            value={k.value}
            unit={k.unit}
            trend={k.trend}
            up={k.up}
            icon={kpiIcons[i]}
          />
        ))}
      </section>

      {(flowPhase !== "idle" || query) && (
        <AnalysisFlow
          question={query || "本月销售额是多少？"}
          phase={flowPhase}
          currentIndex={stageIndex}
          onCancel={cancelAnalysis}
        />
      )}

      <section className="analysis-grid fade-in">
        <ChartCard title="销售趋势" subtitle="近 12 个月 · Demo 数据" option={salesTrendOption()} />
        <ChartCard title="分类销售" subtitle="五大分类 · Demo 数据" option={categorySalesOption()} />
      </section>

      <section className="analysis-grid fade-in" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <TopProducts />
        <section className="card chart-card">
          <div className="chart-card__head">
            <h2 className="section-title">最近动态</h2>
            <span className="section-sub">P1 · 历史记录能力</span>
          </div>
          <div style={{ padding: "40px 0", textAlign: "center" }}>
            <span className="badge badge-warning">
              <span className="dot" />
              阶段 1 保留占位结构
            </span>
            <p className="section-sub" style={{ marginTop: 12 }}>
              最近查询记录将在此展示，点击可回填问题
            </p>
          </div>
        </section>
      </section>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button type="button" className="btn-ghost" onClick={() => setPresentation(true)}>
          进入汇报模式
        </button>
        <span className="section-sub">Demo 模式：静态演示数据，未连接后端</span>
      </div>

      <DbStatus />

      {presentation && (
        <PresentationOverlay
          question={query || "本月销售额是多少？"}
          stages={agentStages.map((name) => ({ name, status: "done" as const }))}
          resultValue={demoResult.value}
          resultUnit={demoResult.unit}
          chartOption={presentationChartOption()}
          chartAriaLabel="近 7 个月销售趋势"
          footer="数据来源：ecommerce.db · SQLite · 已连接  |  SQL / Trace 详情默认折叠  |  Demo 模式：暂未连接后端"
          onExit={() => setPresentation(false)}
        />
      )}
    </>
  );
}
