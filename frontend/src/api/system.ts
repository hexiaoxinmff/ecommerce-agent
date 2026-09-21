/**
 * 系统信息 API 层：封装只读的数据库元数据接口真实契约。
 *
 * 类型与后端 backend/app/schemas/health.py、app/schemas/system.py 一一对应。
 *
 * 说明：数据库行数已由 GET /api/system/schema 逐表返回，因此这里**不再封装**
 * GET /api/system/database，避免同一页面重复查询同一份数据。
 *
 * 本模块只访问只读元数据接口，不接触任何 LLM / Agent 接口。
 */

import { API_BASE_URL } from "./agent";

/** 数据库健康状态（后端 DatabaseHealth） */
export interface DatabaseHealthDto {
  status: "ok" | "error";
  type: "sqlite";
  name: string;
}

/** GET /api/health 响应（后端 HealthResponse） */
export interface HealthResponseDto {
  status: "ok" | "degraded";
  service: string;
  database: DatabaseHealthDto;
}

/** 单个字段（后端 SchemaColumn） */
export interface SchemaColumnDto {
  name: string;
  type: string;
  description: string;
  not_null: boolean;
  primary_key: boolean;
}

/** 单条外键（后端 SchemaForeignKey） */
export interface SchemaForeignKeyDto {
  from_column: string;
  to_table: string;
  to_column: string;
}

/** 单张业务表（后端 SchemaTable） */
export interface SchemaTableDto {
  table: string;
  description: string;
  columns: SchemaColumnDto[];
  row_count: number;
  foreign_keys: SchemaForeignKeyDto[];
}

/** GET /api/system/schema 响应（后端 SchemaResponse） */
export interface SchemaResponseDto {
  database: string;
  tables: SchemaTableDto[];
}

/** 系统接口结构化错误（非 2xx） */
export class SystemApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "SystemApiError";
    this.status = status;
  }
}

/** 后端统一以 `detail`（HTTPException）或 `error` 返回固定文案 */
function extractServerError(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string" && record.detail) return record.detail;
    if (typeof record.error === "string" && record.error) return record.error;
  }
  return fallback;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { method: "GET", signal });

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }

  if (!res.ok) {
    throw new SystemApiError(
      res.status,
      extractServerError(body, `请求失败（HTTP ${res.status}）`),
    );
  }

  return body as T;
}

/** 服务与数据库连接状态（后端真实执行 SELECT 1 探活） */
export function fetchHealth(signal?: AbortSignal): Promise<HealthResponseDto> {
  return getJson<HealthResponseDto>("/api/health", signal);
}

/** 各业务表真实字段结构、行数、外键与业务口径注释 */
export function fetchSchema(signal?: AbortSignal): Promise<SchemaResponseDto> {
  return getJson<SchemaResponseDto>("/api/system/schema", signal);
}
