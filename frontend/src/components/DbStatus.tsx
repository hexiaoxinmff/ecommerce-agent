import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchDatabaseInfo,
  fetchHealth,
  SystemApiError,
  type DatabaseInfoDto,
  type HealthResponseDto,
} from "../api/system";

/**
 * 数据库状态（UI/UX v1.0 第 9.5 节）。
 *
 * 数据全部来自后端只读接口的真实返回值，页面不硬编码库名、类型或任何规模数字：
 * - GET /api/health          → 连接状态与数据库类型
 * - GET /api/system/database → 数据库名称与 6 项规模统计
 *
 * 不调用 Agent，不触发任何 LLM 调用，失败时不回退到任何演示数据。
 */

type LoadStatus = "loading" | "success" | "error";

/**
 * 统计项的展示顺序与中文标签。
 * 这里只有「字段名 → 界面文案」的映射，不含任何数值；数值一律取自接口返回值。
 */
const STAT_ITEMS: { key: keyof Omit<DatabaseInfoDto, "database">; label: string }[] = [
  { key: "tables", label: "业务表数量" },
  { key: "users", label: "平台注册用户" },
  { key: "categories", label: "商品分类" },
  { key: "products", label: "平台在售商品" },
  { key: "orders", label: "用户订单" },
  { key: "order_items", label: "订单商品明细" },
];

/** 千分位展示（仅格式化真实返回值，不做任何推算） */
function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/**
 * 错误信息友好化。
 *
 * 实测：GET /api/health 在数据库不可用时返回 HTTP 503，且响应体**不含** `detail`
 * 字段，因此不能把 err.message 直接当最终文案。这里按错误类型给固定文案，
 * 不外泄 traceback / URL / response body。
 */
function toErrorMessage(err: unknown): string {
  if (err instanceof SystemApiError) {
    if (err.status === 503) return "无法连接数据库，请确认后端数据库服务正常。";
    return "数据库状态获取失败，请稍后重试。";
  }
  if (err instanceof TypeError) {
    return "无法连接后端服务，请确认后端已启动。";
  }
  return "数据库状态获取失败，请稍后重试。";
}

export function DbStatus() {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [health, setHealth] = useState<HealthResponseDto | null>(null);
  const [info, setInfo] = useState<DatabaseInfoDto | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    void (async () => {
      try {
        // 两个只读接口并发请求，不串行
        const [healthData, infoData] = await Promise.all([
          fetchHealth(controller.signal),
          fetchDatabaseInfo(controller.signal),
        ]);
        setHealth(healthData);
        setInfo(infoData);
        setErrorMessage("");
        setStatus("success");
      } catch (err) {
        if (controller.signal.aborted) return;
        // 失败即清空上一次结果：不留缓存，也不回退到演示数据
        setHealth(null);
        setInfo(null);
        setStatus("error");
        setErrorMessage(toErrorMessage(err));
      }
    })();

    return () => controller.abort();
  }, [reloadToken]);

  /** 初始状态即 loading，挂载时无需重置；只有重试才需要显式回到 loading */
  const retry = useCallback(() => {
    setStatus("loading");
    setErrorMessage("");
    setReloadToken((token) => token + 1);
  }, []);

  /** 只有接口明确返回 status === "ok" 才算已连接 */
  const connected = status === "success" && health?.database.status === "ok";

  const connectionBadge =
    status === "loading" ? (
      <span className="badge badge-processing">
        <span className="dot" />
        连接中
      </span>
    ) : connected ? (
      <span className="badge badge-success">
        <span className="dot" />
        已连接
      </span>
    ) : (
      <span className="badge badge-error">
        <span className="dot" />
        未连接
      </span>
    );

  const subtitle =
    status === "loading"
      ? "正在读取真实数据库信息…"
      : status === "error"
        ? errorMessage
        : "当前开发数据库 · 合成数据";

  return (
    <section className="card db-card">
      <div className="db-card__head">
        <div>
          <div className="db-card__file">
            {info?.database ?? "—"}
            <span className="db-card__type">{health?.database.type ?? "—"}</span>
          </div>
          <span className="section-sub">{subtitle}</span>
        </div>
        <div>
          {connectionBadge}
          {status === "error" ? (
            <button type="button" className="btn-primary" onClick={retry}>
              重新加载
            </button>
          ) : null}
        </div>
      </div>

      <div className="db-card__stats">
        {STAT_ITEMS.map((item) => (
          <div className="db-card__stat" key={item.key}>
            <span className="db-card__stat-label">{item.label}</span>
            <span className="db-card__stat-value num">
              {status === "success" && info ? formatCount(info[item.key]) : "—"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
