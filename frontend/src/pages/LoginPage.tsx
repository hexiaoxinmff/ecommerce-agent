/**
 * 登录页（P5）：登录 / 注册双模式，视觉沿用现有 tokens（深色卡片，克制）。
 *
 * - loading：提交期间按钮禁用；
 * - 错误提示：按状态码映射安全文案（不显示堆栈、不显示 token）；
 * - 登录成功：onSuccess 回调（由调用方决定回到原目标页面）。
 */

import { useState, type FormEvent } from "react";

import { HttpApiError, classifyRequestFailure } from "../api/http";
import { useAuth } from "../auth/AuthContext";

type LoginMode = "login" | "register";

function friendlyError(err: unknown, mode: LoginMode): string {
  if (err instanceof HttpApiError) {
    if (err.status === 401) return "用户名或密码不正确";
    if (err.status === 409) return "用户名或邮箱已被注册";
    if (err.status === 422) return "请检查输入格式";
  }
  // 网络失败已由 http 层统一包装为 HttpNetworkError，不能再判裸 TypeError
  // （第十阶段 P0-1：分类只允许有一个推导源）。
  switch (classifyRequestFailure(err)) {
    case "backend_unavailable":
      return "无法连接服务，请确认后端已启动";
    case "backend_error":
      return "服务暂时不可用，请稍后重试";
    default:
      break;
  }
  return mode === "login" ? "登录失败，请稍后重试" : "注册失败，请稍后重试";
}

export function LoginPage({ onSuccess }: { onSuccess?: () => void }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<LoginMode>("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), email.trim(), password);
      }
      onSuccess?.();
    } catch (err) {
      setError(friendlyError(err, mode));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="login fade-in">
      <form className="login__card card" onSubmit={handleSubmit}>
        <h2 className="login__title">{mode === "login" ? "登录" : "注册"}</h2>
        <p className="login__subtitle">
          {mode === "login" ? "登录后使用智能分析与历史记录" : "创建账号后自动登录"}
        </p>

        <label className="login__field">
          <span>用户名</span>
          <input
            className="login__input"
            type="text"
            value={username}
            autoComplete="username"
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>

        {mode === "register" && (
          <label className="login__field">
            <span>邮箱</span>
            <input
              className="login__input"
              type="email"
              value={email}
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
        )}

        <label className="login__field">
          <span>密码</span>
          <input
            className="login__input"
            type="password"
            value={password}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}

        <button className="btn-primary login__submit" type="submit" disabled={submitting}>
          {submitting ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
        </button>

        <button
          className="login__switch"
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "没有账号？去注册" : "已有账号？去登录"}
        </button>
      </form>
    </section>
  );
}
