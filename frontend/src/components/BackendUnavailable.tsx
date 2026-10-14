/**
 * 后端不可用 / 后端异常 提示页（第十阶段 P0-1）。
 *
 * 存在的理由：在此之前，`AuthContext` 把 `/api/auth/me` 的**任何**失败都当成
 * "未登录"，于是后端整个挂掉时用户看到的是**登录页**。用户会以为是自己密码错了，
 * 反复输入正确密码，然后在 401 的迷雾里越陷越深。
 *
 * 三条硬规则：
 * 1. 后端不可用时**不跳登录页** —— 用户并没有登出，是服务不在；
 * 2. 必须给出**可执行**的下一步（"请检查后端是否启动"）+ 重试按钮；
 * 3. **禁止**回退到 Demo / Mock / 静态演示数据 —— 宁可显示"拿不到"，
 *    也不显示一个看起来很正常的假页面。
 */

import { useState } from "react";

export type BackendIssue = "backend_unavailable" | "backend_error";

const TITLE = "后端服务不可用";

const DESCRIPTION: Record<BackendIssue, string> = {
  backend_unavailable: "无法连接后端服务，请检查后端是否启动。",
  backend_error: "后端服务返回异常（HTTP 5xx），请检查后端日志。",
};

/** 把「怎么做」也写清楚，而不是只说一句"失败了" */
const HINT: Record<BackendIssue, string> = {
  backend_unavailable:
    "可在项目根目录执行 `python scripts/start_dev.py` 启动后端与前端，然后点击重试。",
  backend_error: "后端进程可能已崩溃，请查看其终端输出后点击重试。",
};

export function BackendUnavailable({
  reason,
  onRetry,
}: {
  reason: BackendIssue;
  onRetry: () => void | Promise<void>;
}) {
  const [retrying, setRetrying] = useState(false);

  async function handleRetry() {
    if (retrying) return;
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="placeholder fade-in" data-testid="backend-unavailable">
      <span className="badge badge-error">
        <span className="dot" />
        {TITLE}
      </span>
      <p className="section-sub" role="alert">
        {DESCRIPTION[reason]}
      </p>
      <p className="section-sub">{HINT[reason]}</p>
      <p className="section-sub">
        本页不会回退到本地假数据：拿不到后端数据，就如实显示为不可用。
      </p>
      <button type="button" className="btn-primary" onClick={() => void handleRetry()} disabled={retrying}>
        {retrying ? "重试中…" : "重试"}
      </button>
    </section>
  );
}
