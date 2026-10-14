/**
 * 查询历史 API 层：封装 /api/history 的真实契约（P4 后端）。
 *
 * 类型与后端 backend/app/schemas/history.py 一一对应；
 * 响应不含 user_id / session_id / 任何 hash 字段。
 * Bearer 由统一请求层自动注入。
 */

import { apiRequest } from "./http";

/** 单条查询历史（后端 HistoryItem） */
export interface HistoryItemDto {
  id: number;
  question: string;
  sql: string;
  success: boolean;
  error_message: string;
  result_summary: string;
  row_count: number | null;
  total_time_ms: number | null;
  created_at: string;
}

/** GET /api/history 响应（created_at 倒序 + 分页） */
export interface HistoryListDto {
  items: HistoryItemDto[];
  page: number;
  page_size: number;
  total: number;
}

/** 当前用户的查询历史（后端强制 user_id 隔离） */
export function listHistory(
  page = 1,
  pageSize = 50,
  signal?: AbortSignal,
): Promise<HistoryListDto> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiRequest<HistoryListDto>(`/api/history?${query.toString()}`, {
    method: "GET",
    signal,
  });
}

/** 删除本人一条历史：成功 204；不属于本人或不存在 → HttpApiError 404 */
export function deleteHistory(historyId: number, signal?: AbortSignal): Promise<null> {
  return apiRequest<null>(`/api/history/${historyId}`, { method: "DELETE", signal });
}
