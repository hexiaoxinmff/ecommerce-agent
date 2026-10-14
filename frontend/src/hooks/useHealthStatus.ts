/**
 * 后端 + 数据库连接状态 Hook（第九阶段 Phase E）。
 *
 * 把「取 `/api/health` → 推导连接态」这件事收成一处，供 `Header` 与
 * `AnalysisPage` 共用，推导规则集中在 `utils/connection.ts`。
 *
 * 刻意不做的事：
 * - 不轮询（避免把只读健康检查变成持续流量）；只在挂载时取一次，失败可手动 `retry`；
 * - 失败时**清空**上一次的 `health`，不留陈旧缓存（与 `DbStatus.tsx` 同一模式）；
 * - 不发起任何 LLM 调用（`/api/health` 本身也不发）。
 */

import { useCallback, useEffect, useState } from "react";

import { fetchHealth, SystemApiError, type HealthResponseDto } from "../api/system";
import {
  toDbConnectionTone,
  toLlmConfigLabel,
  type DbConnectionTone,
  type HealthLoadStatus,
} from "../utils/connection";

export interface HealthStatus {
  /** 粗粒度加载态 */
  status: HealthLoadStatus;
  /** 数据库连接四态 */
  tone: DbConnectionTone;
  /** 原始探活响应（未取到为 null） */
  health: HealthResponseDto | null;
  /** LLM 配置标签（只反映配置，不代表可用；取不到为「—」） */
  llmLabel: string;
  /** 失败文案（成功时为空串） */
  errorMessage: string;
  retry: () => void;
}

/**
 * 错误信息友好化。
 *
 * 实测：`GET /api/health` 在数据库不可用时返回 503 且响应体**不含** `detail`，
 * 因此不能把 `err.message` 直接当最终文案（`DbStatus.tsx` 已有同样结论）。
 */
function toHealthErrorMessage(err: unknown): string {
  if (err instanceof SystemApiError) {
    if (err.status === 503) return "无法连接数据库，请确认后端数据库服务正常。";
    return "服务状态获取失败，请稍后重试。";
  }
  if (err instanceof TypeError) return "无法连接后端服务，请确认后端已启动。";
  return "服务状态获取失败，请稍后重试。";
}

export function useHealthStatus(): HealthStatus {
  const [status, setStatus] = useState<HealthLoadStatus>("loading");
  const [health, setHealth] = useState<HealthResponseDto | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    void (async () => {
      try {
        const data = await fetchHealth(controller.signal);
        if (controller.signal.aborted) return;
        setHealth(data);
        setErrorMessage("");
        setStatus("success");
      } catch (err) {
        if (controller.signal.aborted) return;
        // 失败即清空：不留陈旧状态，也就不会误显示成「已连接」
        setHealth(null);
        setStatus("error");
        setErrorMessage(toHealthErrorMessage(err));
      }
    })();

    return () => controller.abort();
  }, [reloadToken]);

  const retry = useCallback(() => {
    setStatus("loading");
    setErrorMessage("");
    setReloadToken((token) => token + 1);
  }, []);

  return {
    status,
    tone: toDbConnectionTone(status, health),
    health,
    llmLabel: toLlmConfigLabel(health?.llm),
    errorMessage,
    retry,
  };
}
