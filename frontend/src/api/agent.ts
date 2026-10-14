/**
 * Agent API 层：封装 POST /api/agent/analyze 的真实契约。
 * 类型与后端 backend/app/agent/models.py、app/trace/models.py 一一对应。
 *
 * P5：请求经由统一 http 层自动携带 `Authorization: Bearer <token>`，
 * 401 由统一层处理（清会话 + 广播），本模块导出保持既有契约。
 */

import { API_BASE_URL, apiRequest, HttpApiError } from "./http";

export { API_BASE_URL };

/** TraceEvent（后端 TraceEvent） */
export type TraceStatus = "success" | "error" | "skipped";

export interface AgentTraceEventDto {
  sequence: number;
  node: string;
  status: TraceStatus;
  duration_ms: number;
  message: string;
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
}

/** SQL 执行结果（后端 SQLExecutionResult） */
export interface AgentExecutionResultDto {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  execution_time_ms: number;
}

/** Agent 编排结果（后端 AgentResult） */
export interface AgentResultDto {
  question: string;
  success: boolean;
  generated_sql: string;
  repaired_sql: string;
  execution_result: AgentExecutionResultDto | null;
  execution_error: string;
  repair_reason: string;
  repair_error: string;
  execute_count: number;
  repair_count: number;
  final_error: string;
  trace: AgentTraceEventDto[];
  total_time_ms: number;
  http_status: number | null;
  error_type: string;
}

/** Agent API 响应（后端 AgentResponse） */
export interface AgentAnalysisResponseDto {
  success: boolean;
  result: AgentResultDto | null;
  error: string;
  /** 业务数据截止日（Data As-Of 契约，Phase 15 P0-1）；契约不可用时为空串 */
  data_as_of?: string;
}

/** 后端结构化错误（非 2xx 时的错误代理） */
export class AgentApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AgentApiError";
    this.status = status;
  }
}

/**
 * 调用真实 Agent 分析接口（自动携带 Bearer token；401 由统一层处理）。
 * @throws AgentApiError 后端非 2xx（携带后端 error / 状态码）
 * @throws TypeError/CustomError 网络不可达
 */
export async function analyzeQuestion(
  question: string,
  signal?: AbortSignal,
): Promise<AgentAnalysisResponseDto> {
  try {
    return await apiRequest<AgentAnalysisResponseDto>("/api/agent/analyze", {
      method: "POST",
      body: { question },
      signal,
    });
  } catch (err) {
    if (err instanceof HttpApiError) {
      throw new AgentApiError(err.status, err.message);
    }
    throw err;
  }
}