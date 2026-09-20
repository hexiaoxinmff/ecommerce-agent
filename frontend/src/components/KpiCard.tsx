import type { ReactNode } from "react";
import { IconTrendDown, IconTrendUp } from "./Icons";

type KpiCardProps = {
  label: string;
  value: string;
  unit: string;
  trend: string;
  up: boolean;
  icon: ReactNode;
};

/** KPI 卡：UI/UX v1.0 第 17.1 节（数值 ≥ 44px，远距离可读） */
export function KpiCard({ label, value, unit, trend, up, icon }: KpiCardProps) {
  return (
    <div className="card kpi-card">
      <div className="kpi-card__head">
        <span className="kpi-card__icon">{icon}</span>
        <span>{label}</span>
      </div>
      <div className="kpi-card__value num">{value}</div>
      <div className="kpi-card__foot">
        <span className={`kpi-card__trend${up ? " kpi-card__trend--up" : " kpi-card__trend--down"}`}>
          {up ? <IconTrendUp size={14} /> : <IconTrendDown size={14} />} {trend}
        </span>
        <span className="kpi-card__unit">单位：{unit}</span>
      </div>
    </div>
  );
}
