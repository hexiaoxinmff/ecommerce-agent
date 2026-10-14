import { describe, expect, it } from "vitest";

import {
  categorySalesOption,
  presentationChartOption,
  salesTrendOption,
} from "./charts";
import type { CategoryDistributionItemDto, SalesTrendPointDto } from "../api/insights";

/**
 * 第十阶段 §十二：证明「Dashboard 上的真实图表」不是一句口号。
 *
 * 第九阶段 Phase D 把这三个函数从「自带 demo 数据」改成了「数据由调用方传入」，
 * 但当时只靠人工看浏览器。这里把它变成会响的断言：
 *
 *   1. 图表的 x 轴类目 == 接口返回的月份；
 *   2. 图表的 series 值 == 接口返回的销售额（元 → 万元，1 位小数）；
 *   3. 转换只发生在 charts.ts 一处（本文件用同样的算式对账）；
 *   4. 反向自查：空输入必须得到空图表 —— 否则「映射」可能是个恒返回常量的假货。
 *
 * ⚠️ 铁律 15：断言必须能失败。下面 `describe("反向自查")` 就是为此存在的。
 */

/** ECharts option 是宽松联合类型，取数据时统一收窄到我们真正写进去的形状。 */
type AxisLike = { data?: unknown[] };
type SeriesLike = { data?: Array<number | { value: number }> };

function axisData(option: unknown): unknown[] {
  const x = (option as { xAxis?: AxisLike }).xAxis;
  return x?.data ?? [];
}

function seriesData(option: unknown): Array<number | { value: number }> {
  const series = (option as { series?: SeriesLike[] }).series;
  return series?.[0]?.data ?? [];
}

/** 与 charts.ts 的 toWan() 同算式：元 -> 万元（1 位小数）。 */
function toWan(value: number): number {
  return Math.round((value / 10000) * 10) / 10;
}

const TREND: SalesTrendPointDto[] = [
  { month: "2025-10", sales: 1234567.89 },
  { month: "2025-11", sales: 0 },
  { month: "2025-12", sales: 98765.43 },
];

const CATEGORIES: CategoryDistributionItemDto[] = [
  { category: "服饰", sales: 500000, quantity: 120 },
  { category: "数码", sales: 250000.5, quantity: 60 },
];

describe("salesTrendOption：x 轴与 series 全部来自接口数据", () => {
  it("x 轴类目逐个等于接口返回的月份", () => {
    expect(axisData(salesTrendOption(TREND))).toEqual(["2025-10", "2025-11", "2025-12"]);
  });

  it("series 值等于接口销售额换算成万元（1 位小数）", () => {
    expect(seriesData(salesTrendOption(TREND))).toEqual([123.5, 0, 9.9]);
  });

  it("换算结果与独立算式逐值一致（元 → 万元只有一处转换）", () => {
    const expected = TREND.map((p) => toWan(p.sales));
    expect(seriesData(salesTrendOption(TREND))).toEqual(expected);
  });

  it("序列长度与数据点数一致（不多不少，没有硬编码的尾巴）", () => {
    expect(seriesData(salesTrendOption(TREND))).toHaveLength(TREND.length);
    expect(seriesData(salesTrendOption(TREND.slice(0, 1)))).toHaveLength(1);
  });
});

describe("categorySalesOption：类目与数值同样来自接口数据", () => {
  it("x 轴类目等于接口返回的品类名", () => {
    expect(axisData(categorySalesOption(CATEGORIES))).toEqual(["服饰", "数码"]);
  });

  it("series 值等于接口销售额换算成万元", () => {
    const values = seriesData(categorySalesOption(CATEGORIES)).map((d) =>
      typeof d === "number" ? d : d.value,
    );
    expect(values).toEqual([50, 25]);
  });
});

describe("presentationChartOption：汇报模式取最近 7 个月", () => {
  it("x 轴只保留最后 7 个点", () => {
    const twelve: SalesTrendPointDto[] = Array.from({ length: 12 }, (_, i) => ({
      month: `2026-${String(i + 1).padStart(2, "0")}`,
      sales: (i + 1) * 10000,
    }));
    const option = presentationChartOption(twelve);
    expect(axisData(option)).toEqual([
      "2026-06",
      "2026-07",
      "2026-08",
      "2026-09",
      "2026-10",
      "2026-11",
      "2026-12",
    ]);
    expect(seriesData(option)).toEqual([6, 7, 8, 9, 10, 11, 12]);
  });
});

describe("反向自查：映射不是恒返回常量的假货", () => {
  it("空输入必须得到空图表（否则上面的相等断言毫无意义）", () => {
    expect(axisData(salesTrendOption([]))).toEqual([]);
    expect(seriesData(salesTrendOption([]))).toEqual([]);
    expect(axisData(categorySalesOption([]))).toEqual([]);
    expect(seriesData(categorySalesOption([]))).toEqual([]);
  });

  it("数据变了，图表必须跟着变（同一函数两次调用结果不同）", () => {
    const a = salesTrendOption([{ month: "2026-01", sales: 10000 }]);
    const b = salesTrendOption([{ month: "2026-02", sales: 20000 }]);
    expect(axisData(a)).not.toEqual(axisData(b));
    expect(seriesData(a)).not.toEqual(seriesData(b));
  });

  it("接口给多少，图表就画多少 —— 不补点、不截断（除汇报模式的 7 点窗口）", () => {
    const many: SalesTrendPointDto[] = Array.from({ length: 12 }, (_, i) => ({
      month: `2026-${String(i + 1).padStart(2, "0")}`,
      sales: 1000,
    }));
    expect(seriesData(salesTrendOption(many))).toHaveLength(12);
    expect(seriesData(presentationChartOption(many))).toHaveLength(7);
  });
});
