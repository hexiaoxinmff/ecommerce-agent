import type { ReactNode } from "react";
import { IconTrendDown, IconTrendUp } from "./Icons";

type KpiCardProps = {
  label: string;
  value: string;
  unit: string;
  /**
   * 趋势百分比（如 `+12.4%`）。
   *
   * **可选，且默认不传**：`GET /api/insights/overview` 刻意不返回趋势
   * （原先 `data/demo.ts` 里的 `+12.4% / -1.8%` 没有任何真实来源，既非环比也非同比；
   * 该文件已于第九阶段 Phase G 删除）。
   * 只有拿到真实可回溯的趋势值时才允许传这个 prop —— 绝不为了"填满卡片"编一个。
   */
  trend?: string;
  up?: boolean;
  /** 无趋势时展示的口径说明（如「数据截至 2026-09-12」） */
  note?: string;
  icon: ReactNode;
};

/** KPI 卡：UI/UX v1.0 第 17.1 节（数值 ≥ 44px，远距离可读） */
export function KpiCard({ label, value, unit, trend, up, note, icon }: KpiCardProps) {
  return (
    <div className="card kpi-card">
      <div className="kpi-card__head">
        <span className="kpi-card__icon">{icon}</span>
        <span>{label}</span>
      </div>
      <div className="kpi-card__value num">{value}</div>
      <div className="kpi-card__foot">
        {trend ? (
          <span className={`kpi-card__trend${up ? " kpi-card__trend--up" : " kpi-card__trend--down"}`}>
            {up ? <IconTrendUp size={14} /> : <IconTrendDown size={14} />} {trend}
          </span>
        ) : note ? (
          <span className="kpi-card__unit">{note}</span>
        ) : null}
        <span className="kpi-card__unit">单位：{unit}</span>
      </div>
    </div>
  );
}
