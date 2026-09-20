import type { EChartOption } from "../components/ChartCard";
import { categorySales, presentationChart, salesTrend } from "./demo";

/**
 * ECharts 静态配置（演示数据）。
 * 遵循 UI/UX v1.0 第 16 节：线宽 ≥ 2px、标签清晰、网格线淡、无 3D、无复杂动画。
 */

const axisLine = { lineStyle: { color: "rgba(148,178,226,0.14)" } };
const splitLine = { lineStyle: { color: "rgba(148,178,226,0.10)" } };

/** 销售趋势（折线图） */
export function salesTrendOption(): EChartOption {
  return {
    backgroundColor: "transparent",
    grid: { left: 16, right: 20, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#0B1220",
      borderColor: "rgba(148,178,226,0.30)",
      textStyle: { color: "#F4F7FF", fontSize: 14 },
      valueFormatter: (v: number | string) => `${v} 万元`,
    },
    xAxis: {
      type: "category",
      data: salesTrend.months,
      axisLine,
      axisTick: { show: false },
      axisLabel: { color: "#8CA0C0", fontSize: 13 },
    },
    yAxis: {
      type: "value",
      name: "万元",
      nameTextStyle: { color: "#8CA0C0", fontSize: 12 },
      axisLine: { show: false },
      axisLabel: { color: "#8CA0C0", fontSize: 13 },
      splitLine,
    },
    series: [
      {
        name: "销售额",
        type: "line",
        data: salesTrend.values,
        smooth: true,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { width: 3, color: "#3D8BFF" },
        itemStyle: { color: "#3D8BFF", borderColor: "#0B1220", borderWidth: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(61,139,255,0.28)" },
              { offset: 1, color: "rgba(61,139,255,0.02)" },
            ],
          },
        },
        label: { show: true, color: "#A8C9FF", fontSize: 13, formatter: "{c}" },
        animationDuration: 400,
      },
    ],
  };
}

/** 分类销售（柱状图，使用 UI/UX 图表色板） */
export function categorySalesOption(): EChartOption {
  const palette = ["#3D8BFF", "#8B7CF6", "#38BDF8", "#F5A623", "#2ED47A"];
  return {
    backgroundColor: "transparent",
    grid: { left: 16, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: "#0B1220",
      borderColor: "rgba(148,178,226,0.30)",
      textStyle: { color: "#F4F7FF", fontSize: 14 },
      valueFormatter: (v: number | string) => `${v} 万元`,
    },
    xAxis: {
      type: "category",
      data: categorySales.map((c) => c.name),
      axisLine,
      axisTick: { show: false },
      axisLabel: { color: "#8CA0C0", fontSize: 13, interval: 0 },
    },
    yAxis: {
      type: "value",
      name: "万元",
      nameTextStyle: { color: "#8CA0C0", fontSize: 12 },
      axisLine: { show: false },
      axisLabel: { color: "#8CA0C0", fontSize: 13 },
      splitLine,
    },
    series: [
      {
        name: "销售额",
        type: "bar",
        data: categorySales.map((c, i) => ({
          value: c.value,
          itemStyle: { color: palette[i % palette.length], borderRadius: [4, 4, 0, 0] },
        })),
        barWidth: 42,
        label: { show: true, position: "top", color: "#F4F7FF", fontSize: 13, formatter: "{c}" },
        animationDuration: 400,
      },
    ],
  };
}

/** 汇报模式侧边图表（折线，简版） */
export function presentationChartOption(): EChartOption {
  return {
    backgroundColor: "transparent",
    grid: { left: 16, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#0B1220",
      borderColor: "rgba(148,178,226,0.30)",
      textStyle: { color: "#F4F7FF", fontSize: 14 },
    },
    xAxis: {
      type: "category",
      data: presentationChart.months,
      axisLine,
      axisTick: { show: false },
      axisLabel: { color: "#8CA0C0", fontSize: 14 },
    },
    yAxis: {
      type: "value",
      name: "万元",
      nameTextStyle: { color: "#8CA0C0", fontSize: 13 },
      axisLine: { show: false },
      axisLabel: { color: "#8CA0C0", fontSize: 14 },
      splitLine,
    },
    series: [
      {
        name: "销售额",
        type: "line",
        data: presentationChart.values,
        smooth: true,
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { width: 3, color: "#8B7CF6" },
        itemStyle: { color: "#8B7CF6", borderColor: "#0B1220", borderWidth: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(139,124,246,0.30)" },
              { offset: 1, color: "rgba(139,124,246,0.03)" },
            ],
          },
        },
        label: { show: true, color: "#C9D4E8", fontSize: 14, formatter: "{c}" },
        animationDuration: 400,
      },
    ],
  };
}
