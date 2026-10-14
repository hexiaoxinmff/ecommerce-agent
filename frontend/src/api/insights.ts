/**
 * 业务概览 API 层（第九阶段 Phase C/D）。
 *
 * 封装 `GET /api/insights/overview` 的真实契约，类型与后端
 * `backend/app/schemas/insights.py` 一一对应。
 *
 * 三条硬约定：
 * 1. **必须带 Bearer（`auth: true`，默认值）**：后端决策 D6 于 2026-09-28
 *    **反转** —— `GET /api/insights/overview` 现在挂 `Depends(get_current_user)`，
 *    未登录 / 伪造 token 一律 401。前端配套把首页纳入 `ProtectedRoute`
 *    （见 `App.tsx`），因此「未登录」这一路径由路由守卫兜住，不会走到这里。
 *    ⚠️ 后端加的是**访问门禁**而非数据隔离：聚合口径仍是全库的，
 *    响应体不含任何用户身份字段 —— 前端也不得据此渲染「我的数据」这类文案。
 * 2. **统一走 `http.ts::apiRequest`**，不在本模块自建 fetch（http.ts 顶部约定：
 *    「所有 API 模块经由本函数，页面不得散落 fetch」）。
 * 3. **接口不返回趋势百分比**：原先 `data/demo.ts` 里的 `+12.4% / -1.8%` 没有任何
 *    真实来源（该文件已于第九阶段 Phase G 删除），后端刻意不提供。
 *    前端**绝不**自行计算或硬编码补一个上去。
 */

import { apiRequest, HttpApiError, classifyRequestFailure } from "./http";

/** 单个 KPI：真实聚合值 + 单位 + 口径月份（无数据时 month 为 null） */
export interface KpiValueDto {
  label: string;
  value: number;
  unit: string;
  month: string | null;
}

/** 首页 4 张 KPI 卡 */
export interface OverviewKpisDto {
  month_sales: KpiValueDto;
  month_orders: KpiValueDto;
  users_total: KpiValueDto;
  avg_order_value: KpiValueDto;
}

/** 销售趋势的一个月份点（`sales` 单位：元） */
export interface SalesTrendPointDto {
  month: string;
  sales: number;
}

/** 类目分布项（叶子类目；`sales` 单位：元） */
export interface CategoryDistributionItemDto {
  category: string;
  sales: number;
  quantity: number;
}

/** Top 商品项（口径：销售额） */
export interface TopProductItemDto {
  rank: number;
  product: string;
  quantity: number;
  sales: number;
}

/** `GET /api/insights/overview` 响应 */
export interface OverviewDto {
  /** 数据截止日（= MAX(orders.order_date)）。**必须展示**，否则「本月」会被误读为完整自然月 */
  as_of: string | null;
  generated_at: string;
  kpis: OverviewKpisDto;
  sales_trend: SalesTrendPointDto[];
  category_distribution: CategoryDistributionItemDto[];
  top_products: TopProductItemDto[];
}

/** 首页业务概览（**需要登录**：决策 D6 反转后必须带 Bearer） */
export function fetchOverview(signal?: AbortSignal): Promise<OverviewDto> {
  return apiRequest<OverviewDto>("/api/insights/overview", {
    method: "GET",
    auth: true,
    signal,
  });
}

/**
 * 错误信息友好化。
 *
 * 后端非 2xx 时统一返回 `{"detail": "..."}`（已实测），`apiRequest` 会把它
 * 提取进 `HttpApiError.message`；这里按状态码给出**固定兜底文案**，
 * 不外泄 URL / traceback / 响应体原文。
 *
 * 401 单独分支：正常路径下首页已被 `ProtectedRoute` 守卫，走不到这里；
 * 但若会话在页面停留期间失效，`apiRequest` 会先清空本地会话并广播登出，
 * 这里只负责给出一句不误导的文案（不要说成「后端故障」）。
 */
export function toOverviewErrorMessage(err: unknown): string {
  if (err instanceof HttpApiError) {
    if (err.status === 401) {
      return "登录状态已失效，请重新登录后查看业务数据。";
    }
    if (err.status === 503) {
      return err.message || "后端数据库不可用，请确认 db/ecommerce.db 存在且可读。";
    }
    return `业务数据获取失败（HTTP ${err.status}）。`;
  }
  if (classifyRequestFailure(err) === "backend_unavailable") {
    return "无法连接后端服务，请确认后端已启动。";
  }
  return "业务数据获取失败，请稍后重试。";
}

/**
 * 修复提示（与 `toOverviewErrorMessage` 配套）。
 *
 * 单独拆出来的原因：错误卡片里曾把「请确认后端已启动、数据库可读」写死成静态文案，
 * 于是**鉴权失败也会被告知是后端故障** —— 属于任务书 §十二 禁止的失真文案。
 * 这里按错误类型分派：401 的下一步动作已经在 message 里（重新登录），故返回 null。
 */
export function toOverviewErrorHint(err: unknown): string | null {
  if (err instanceof HttpApiError) {
    if (err.status === 401) return null;
    if (err.status === 503) return "请确认后端已启动、数据库可读后重试。";
    return "请稍后重试。";
  }
  if (classifyRequestFailure(err) === "backend_unavailable") return "请确认后端已启动。";
  return "请稍后重试。";
}
