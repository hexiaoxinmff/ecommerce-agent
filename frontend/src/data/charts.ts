import type { EChartOption } from "../components/ChartCard";
import type { CategoryDistributionItemDto, SalesTrendPointDto } from "../api/insights";

/**
 * ECharts 配置构造函数（**数据由调用方传入，本文件不再持有任何数据**）。
 *
 * 第九阶段 Phase D 改造：原先这三个函数直接 `import { salesTrend, categorySales,
 * presentationChart } from "./demo"`（`./demo` 已于 Phase G 删除），即"图表看起来是真的，数据是编的"。
 * 现在它们只负责**视觉**（UI/UX v1.0 第 16 节：线宽 ≥ 2px、标签清晰、网格线淡、
 * 无 3D、无复杂动画），数据一律来自 `GET /api/insights/overview` 的真实返回值。
 *
 * 单位约定：接口返回的 `sales` 单位是**元**（与数据库一致）；图表按既有设计
 * 展示为**万元**（1 位小数）。转换只发生在这里，不改动接口原始值。
 */

const axisLine = { lineStyle: { color: "rgba(148,178,226,0.14)" } };
const splitLine = { lineStyle: { color: "rgba(148,178,226,0.10)" } };

/** 元 -> 万元（1 位小数）。仅用于图表展示。 */
function toWan(value: number): number {
  return Math.round((value / 10000) * 10) / 10;
}

/** 销售趋势（折线图） */
export function salesTrendOption(points: SalesTrendPointDto[]): EChartOption {
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
      data: points.map((p) => p.month),
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
        data: points.map((p) => toWan(p.sales)),
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
export function categorySalesOption(items: CategoryDistributionItemDto[]): EChartOption {
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
      data: items.map((c) => c.category),
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
        data: items.map((c, i) => ({
          value: toWan(c.sales),
          itemStyle: { color: palette[i % palette.length], borderRadius: [4, 4, 0, 0] },
        })),
        barWidth: 42,
        label: { show: true, position: "top", color: "#F4F7FF", fontSize: 13, formatter: "{c}" },
        animationDuration: 400,
      },
    ],
  };
}

/** 汇报模式侧边图表（折线，取最近 7 个月） */
export function presentationChartOption(points: SalesTrendPointDto[]): EChartOption {
  const recent = points.slice(-7);
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
      data: recent.map((p) => p.month),
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
        data: recent.map((p) => toWan(p.sales)),
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
