import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export type EChartOption = echarts.EChartsCoreOption;

type ChartCardProps = {
  title: string;
  subtitle?: string;
  option: EChartOption;
  height?: number;
  className?: string;
};

/**
 * 通用 ECharts 图表卡片容器。
 * 按 UI/UX v1.0 第 16 节规范：简洁、清晰、标签明确、无 3D、无过度动画。
 */
export function ChartCard({ title, subtitle, option, height = 280, className }: ChartCardProps) {
  const domRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = domRef.current;
    if (!el) return;

    const chart = echarts.init(el);
    chartRef.current = chart;

    const observer = new ResizeObserver(() => {
      chart.resize();
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return (
    <section className={`card chart-card${className ? ` ${className}` : ""}`}>
      <div className="chart-card__head">
        <h2 className="section-title">{title}</h2>
        {subtitle && <span className="section-sub">{subtitle}</span>}
      </div>
      <div
        ref={domRef}
        className="chart-card__body"
        style={{ height }}
        role="img"
        aria-label={title}
      />
    </section>
  );
}
