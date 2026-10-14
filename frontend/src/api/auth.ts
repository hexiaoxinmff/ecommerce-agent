/**
 * 认证 API 层：封装 /api/auth/* 的真实契约（P3 后端）。
 *
 * 类型与后端 backend/app/schemas/auth.py 一一对应。
 * 错误统一抛出 HttpApiError（status + 安全文案）；
 * 登录/注册走 auth:false（401 不触发全局登出事件）。
 */

import { apiRequest } from "./http";

/** 后端 UserPublic / UserOut（不含任何 hash 字段） */
export interface AuthUserDto {
  id: number;
  username: string;
  email: string;
  is_active?: boolean;
}

/** POST /api/auth/login 响应：access_token 为原始令牌，仅此一次返回 */
export interface LoginResponseDto {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: AuthUserDto;
}

export interface RegisterResponseDto {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
}

/** 注册（成功 201；username/email 冲突 → HttpApiError 409） */
export function register(
  body: { username: string; email: string; password: string },
  signal?: AbortSignal,
): Promise<RegisterResponseDto> {
  return apiRequest<RegisterResponseDto>("/api/auth/register", {
    method: "POST",
    body,
    signal,
    auth: false,
  });
}

/** 登录（错误密码/未知用户 → HttpApiError 401 "Invalid credentials"） */
export function login(
  body: { username: string; password: string },
  signal?: AbortSignal,
): Promise<LoginResponseDto> {
  return apiRequest<LoginResponseDto>("/api/auth/login", {
    method: "POST",
    body,
    signal,
    auth: false,
  });
}

/** 当前用户（Bearer；成功返回用户，失败 401） */
export function getCurrentUser(signal?: AbortSignal): Promise<AuthUserDto> {
  return apiRequest<AuthUserDto>("/api/auth/me", { method: "GET", signal });
}

/** 登出（204；token 失效也静默成功，不泄露内部信息） */
export async function logout(signal?: AbortSignal): Promise<void> {
  await apiRequest<null>("/api/auth/logout", { method: "POST", signal });
}
