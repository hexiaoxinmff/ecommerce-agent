/**
 * Agent API 层：封装 POST /api/agent/analyze 的真实契约。
 * 类型与后端 backend/app/agent/models.py、app/trace/models.py 一一对应。
 */

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

/** 后端 Base URL：优先 VITE_API_BASE_URL，默认本地开发地址（集中管理） */
const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ??
  "http://127.0.0.1:8000";

function extractServerError(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.error === "string" && record.error) return record.error;
    const detail = record.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return fallback;
}

/**
 * 调用真实 Agent 分析接口。
 * @throws AgentApiError 后端非 2xx（携带后端 error / 状态码）
 * @throws TypeError/CustomError 网络不可达
 */
export async function analyzeQuestion(
  question: string,
  signal?: AbortSignal,
): Promise<AgentAnalysisResponseDto> {
  const res = await fetch(`${API_BASE_URL}/api/agent/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }

  if (!res.ok) {
    const message =
      extractServerError(body, `分析请求失败（HTTP ${res.status}）`);
    throw new AgentApiError(res.status, message);
  }

  return body as AgentAnalysisResponseDto;
}