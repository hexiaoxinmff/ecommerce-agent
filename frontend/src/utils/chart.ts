/**
 * 将真实 SQL 执行结果映射为 ECharts option（规则型，第一版）。
 *
 * 规则：取前 MAX_POINTS 行；第一列（非数值）作 X 轴，第一个数值列作 Y 轴；
 * - X 列名含 日期/月/time/date 且为字符串 -> 折线图，否则柱状图；
 * - 无法可靠识别数值列 -> 返回 null（只展示表格，不强行绘图）。
 * 禁止猜测业务含义。
 */

import type { EChartOption } from "../components/ChartCard";
import type { AgentExecutionResultDto } from "../api/agent";

const MAX_POINTS = 50;
const PRIMARY = "#3D8BFF";
const DATE_PATTERN = /日期|月份|月|年|date|time|ym/i;

function isNumberCell(value: unknown): boolean {
  return typeof value === "number" && Number.isFinite(value);
}

export function buildChartOption(
  result: AgentExecutionResultDto | null,
): EChartOption | null {
  if (!result || !result.columns.length || !result.rows.length) return null;

  const columns = result.columns;
  const rows = result.rows.slice(0, MAX_POINTS);

  // 找第一个数值列作为 Y；其余列中非数值列作为 X（默认第一个非数值列）
  let yIndex = -1;
  for (let c = 0; c < columns.length; c += 1) {
    if (rows.every((row) => isNumberCell(row[c]))) {
      yIndex = c;
      break;
    }
  }
  if (yIndex === -1) return null;

  let xIndex = -1;
  for (let c = 0; c < columns.length; c += 1) {
    if (c !== yIndex && rows.every((row) => row[c] !== null && row[c] !== undefined)) {
      xIndex = c;
      break;
    }
  }

  const xNames: string[] = [];
  const yValues: (number | null)[] = [];
  for (const row of rows) {
    const x = xIndex >= 0 ? String(row[xIndex]) : String(xNames.length + 1);
    xNames.push(x);
    yValues.push(isNumberCell(row[yIndex]) ? (row[yIndex] as number) : null);
  }

  const xLabel = xIndex >= 0 ? columns[xIndex] : "序号";
  const yLabel = columns[yIndex];
  const isLine = DATE_PATTERN.test(xLabel);

  return {
    tooltip: { trigger: "axis" },
    grid: { left: 16, right: 24, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: xNames, axisLabel: { color: "#8A96AA" } },
    yAxis: { type: "value", name: yLabel, axisLabel: { color: "#8A96AA" } },
    series: [
      {
        name: yLabel,
        type: isLine ? "line" : "bar",
        data: yValues,
        smooth: isLine,
        itemStyle: { color: PRIMARY },
        lineStyle: { color: PRIMARY, width: 2 },
        areaStyle: isLine
          ? { color: "rgba(61,139,255,0.12)" }
          : undefined,
      },
    ],
    color: [PRIMARY],
  };
}