import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartOption } from "./ChartCard";
import { IconSpark } from "./Icons";

export type StageLine = {
  name: string;
  status: "done" | "active" | "todo" | "error";
};

type PresentationOverlayProps = {
  question: string;
  stages: StageLine[];
  resultValue: string;
  resultUnit?: string;
  chartOption: EChartOption;
  chartAriaLabel?: string;
  footer?: string;
  onExit: () => void;
};

/**
 * 汇报模式（Presentation Mode）：UI/UX v1.0 第 19 节。
 * 远距离可读为第一要求：问题 36~40px、阶段 18px+、结果 72px+。
 * 支持从首页 / 智能分析页复用（问题 / 阶段 / 结果 / 图表通过 props 注入）。
 */
export function PresentationOverlay({
  question,
  stages,
  resultValue,
  resultUnit,
  chartOption,
  chartAriaLabel = "核心图表",
  footer,
  onExit,
}: PresentationOverlayProps) {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onExit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onExit]);

  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;
    const chart = echarts.init(el);
    chart.setOption(chartOption, { notMerge: true });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [chartOption]);

  return (
    <div className="presentation fade-in" role="dialog" aria-modal="true" aria-label="汇报模式">
      <div className="presentation__topbar">
        <div className="presentation__brand">
          <div className="sidebar__logo">
            <IconSpark size={18} />
          </div>
          电商智能数据分析 Agent
        </div>
        <button type="button" className="btn-ghost" onClick={onExit}>
          退出汇报模式（ESC）
        </button>
      </div>

      <h2 className="presentation__question">{question}</h2>

      <div className="presentation__body">
        <div className="presentation__flow">
          {stages.map((stage, i) => (
            <div
              key={stage.name}
              className={`presentation__stage${stage.status === "done" ? " presentation__stage--done" : ""}`}
            >
              <span className="mark">{stage.status === "done" ? "✓" : stage.status === "error" ? "✗" : i + 1}</span>
              <span>
                {i + 1}. {stage.name}
              </span>
            </div>
          ))}
        </div>

        <div className="presentation__result">
          <div className="presentation__result-label">最终结果</div>
          <div className="presentation__result-value num">{resultValue}</div>
          {resultUnit && <div className="presentation__result-unit">{resultUnit}</div>}
        </div>
      </div>

      <div className="presentation__bottom">
        <div ref={chartRef} className="presentation__chart" role="img" aria-label={chartAriaLabel} />
        {footer && <div className="presentation__footer">{footer}</div>}
      </div>
    </div>
  );
}
