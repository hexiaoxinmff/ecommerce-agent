/**
 * 系统信息 API 层：封装只读的数据库元数据接口真实契约。
 *
 * 类型与后端 backend/app/schemas/health.py、app/schemas/system.py 一一对应。
 *
 * 说明：两个只读接口职责不同，各自封装，互不替代：
 * - GET /api/system/schema：供「数据集管理」页使用，逐表返回字段 / 类型 /
 *   主键 / 外键 / 行数；
 * - GET /api/system/database：供首页 DbStatus 使用，返回数据库名与 6 项规模统计。
 * 首页只需规模汇总，不必为此拉取整份 Schema。
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

/** 当前实际配置的 LLM Provider / Model（后端 LlmRuntimeInfo，只读展示） */
export interface LlmRuntimeDto {
  provider: string | null;
  model: string | null;
}

/** GET /api/health 响应（后端 HealthResponse） */
export interface HealthResponseDto {
  status: "ok" | "degraded";
  service: string;
  database: DatabaseHealthDto;
  /** 可选：后端无法安全判定（配置非法等）时为 null/缺失，前端须显示中性占位 */
  llm?: LlmRuntimeDto | null;
}

/** GET /api/system/database 响应（后端 DatabaseInfo）：数据库名 + 6 项规模统计 */
export interface DatabaseInfoDto {
  database: string;
  tables: number;
  users: number;
  categories: number;
  products: number;
  orders: number;
  order_items: number;
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

/** 数据库名称与各业务表真实行数（供首页 DbStatus 展示规模） */
export function fetchDatabaseInfo(signal?: AbortSignal): Promise<DatabaseInfoDto> {
  return getJson<DatabaseInfoDto>("/api/system/database", signal);
}

/** 各业务表真实字段结构、行数、外键与业务口径注释 */
export function fetchSchema(signal?: AbortSignal): Promise<SchemaResponseDto> {
  return getJson<SchemaResponseDto>("/api/system/schema", signal);
}
