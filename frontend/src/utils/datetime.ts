/**
 * 时间显示口径（第九阶段 Phase F）。
 *
 * 背景：后端 `appdb.now_iso()` 写入的是 **UTC 带显式偏移** 的字符串，
 * 形如 `2026-09-28T09:10:20+00:00`（见 `backend/app/db/appdb.py:83-85`）。
 *
 * ⚠️ 修复的真实缺陷：`HistoryPage` 原先用
 * `iso.replace("T", " ").slice(0, 19)` 直接截断显示，等于把 **UTC 墙上
 * 时钟当成用户本地时间** 呈现 —— 北京用户看到的「09:10」实际对应本地
 * 17:10，且页面上没有任何时区标记。数字是真的、语义是错的，属于任务书
 * §十二 意义上的失真展示。⇒ 这里统一按 **用户本地时区** 渲染。
 *
 * 单一推导源（铁律 36）：`HistoryPage`（绝对时间）与首页「最近动态」
 * （相对时间）渲染的是**同一批** `created_at`。若各自实现，两处必然
 * 互相矛盾（一个显示 UTC、一个显示本地差值），因此必须共用本模块。
 *
 * 只做显示用途：不做服务端时区推断，不读任何环境变量。
 */

/**
 * 绝对时间：转用户本地时区，输出 `YYYY-MM-DD HH:MM:SS`。
 * 无法解析时**原样返回入参** —— 绝不抛错，也绝不渲染 `Invalid Date`。
 */
export function formatDateTime(iso: string): string {
  const date = parseIso(iso);
  if (!date) return iso;
  return formatLocal(date);
}

/**
 * 相对时间：`刚刚 / N 分钟前 / N 小时前 / N 天前`；
 * 超过 7 天回退为 `MM-DD HH:MM`（相对时间再长就失去可读性）。
 *
 * 边界处理：
 * - 解析失败 → 原样返回；
 * - **未来时间** → 回退为绝对时间，避免出现「-3 分钟前」这种话
 *   （服务端时钟略快于客户端是常态，不能把它渲染成负数）。
 *
 * `now` 可注入，便于测试固定时间点。
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const date = parseIso(iso);
  if (!date) return iso;

  const diffMs = now.getTime() - date.getTime();
  if (diffMs < 0) return formatLocal(date).slice(5, 16);

  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;

  return formatLocal(date).slice(5, 16);
}

function parseIso(iso: string): Date | null {
  const ts = Date.parse(iso);
  return Number.isNaN(ts) ? null : new Date(ts);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function formatLocal(date: Date): string {
  const ymd = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const hms = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  return `${ymd} ${hms}`;
}
