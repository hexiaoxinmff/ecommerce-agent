/**
 * 连接状态推导（第九阶段 Phase E：Health / Runtime 状态统一）。
 *
 * 为什么需要这个模块：`Header`（原第 53-56 行）、`AnalysisPage`（原第 188 / 474 行）
 * 都**硬编码**了「已连接」。硬编码的绿徽标在数据库挂掉时依然是绿的 ——
 * 这正是任务书 §七 要消灭的失真状态：`FastAPI 200` 不等于 `DB 可用`，
 * `DB 可用` 也不等于 `LLM 可用`。
 *
 * 三条不可动摇的规则：
 * 1. **只有 `GET /api/health` 明确返回 `database.status === "ok"` 才算「已连接」**；
 * 2. 请求进行中 = `loading`；请求失败、字段缺失 = `unknown`。
 *    **`unknown` 绝不允许降级显示成「已连接」** —— 不知道就说不知道；
 * 3. **LLM 只说「已配置」，不说「可用」**。`/api/health` 的 `llm` 字段只读
 *    后端环境配置（`health.py` 自述「不产生任何网络请求」），它无法证明上游可达。
 *    用户 2026-09-28 决策：只读配置 + 措辞降级。
 */

import type { HealthResponseDto, LlmRuntimeDto } from "../api/system";

/** 数据库连接四态（loading / ok / error / unknown 互斥，不可合并） */
export type DbConnectionTone = "loading" | "ok" | "error" | "unknown";

/** `GET /api/health` 请求的粗粒度状态 */
export type HealthLoadStatus = "loading" | "success" | "error";

/** 状态词：**只有 `ok` 才允许出现「已连接」** */
export const DB_CONNECTION_WORD: Record<DbConnectionTone, string> = {
  loading: "连接中",
  ok: "已连接",
  error: "不可用",
  unknown: "状态未知",
};

/** 徽标样式类（复用 base.css 既有四态，不新增 CSS） */
export const DB_CONNECTION_BADGE: Record<DbConnectionTone, string> = {
  loading: "badge-processing",
  ok: "badge-success",
  error: "badge-error",
  unknown: "badge-warning",
};

/**
 * 由 `/api/health` 的加载状态与响应体推导数据库连接态。
 *
 * - 请求中 → `loading`（还不知道，但至少不是「已连接」）
 * - 请求失败 → `unknown`（拿不到证据，不等于「不可用」）
 * - 响应明确 `database.status === "error"` → `error`（有证据说它坏了）
 * - 其余（字段缺失等） → `unknown`
 */
export function toDbConnectionTone(
  status: HealthLoadStatus,
  health: HealthResponseDto | null,
): DbConnectionTone {
  if (status === "loading") return "loading";
  if (status === "error" || !health) return "unknown";
  if (health.database?.status === "ok") return "ok";
  if (health.database?.status === "error") return "error";
  return "unknown";
}

/**
 * LLM 徽标文案：**只反映后端环境配置**，不代表可用。
 *
 * 取不到任何配置时返回 `"—"`（中性占位），绝不回退到硬编码模型名。
 */
export function toLlmConfigLabel(llm: LlmRuntimeDto | null | undefined): string {
  const provider = llm?.provider?.trim() ?? "";
  const model = llm?.model?.trim() ?? "";
  if (!provider && !model) return "—";
  return `已配置 · ${[provider, model].filter(Boolean).join(" · ")}`;
}

/** LLM 徽标的悬停说明：把「已配置 ≠ 可用」这件事写在用户能看到的地方 */
export const LLM_CONFIG_TITLE =
  "只反映后端环境配置（provider / model），不代表上游可达或可用：" +
  "健康检查不发起任何 LLM 网络请求。";
