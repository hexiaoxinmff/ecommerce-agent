/**
 * 首页「最近动态」（第九阶段 Phase F）：接入真实 `GET /api/history`。
 *
 * 契约（对应任务书 §九 / §十 / §十二）：
 * 1. **真实数据**：来自 `GET /api/history`，后端强制 `user_id` 隔离
 *    （`backend/app/api/routes/history.py:48-61`），响应体不含 user_id /
 *    session_id / 任何 hash。⇒ 本组件**不做任何前端过滤**（前端过滤
 *    只会制造「看起来隔离了」的假象），也**不渲染任何用户身份字段**。
 * 2. **四态显式**：`loading` / `empty` / `error` / `data`，各自渲染不同
 *    内容，不混排、不叠加。
 * 3. **失败禁止静默回退**：请求失败即清空列表并进入 error 态，
 *    **绝不回退到任何静态占位记录**（`data/demo.ts` 已于 Phase G 删除）。
 *    原先这里的占位块（「阶段 1 保留占位结构」）已删除 —— 它既不是
 *    真实数据，也不是加载态，属于任务书 §十二 禁止的「看起来真实」。
 * 4. **不编数字**：除「共 N 条」（后端 `total` 原值）外不显示任何聚合值；
 *    相对时间统一由 `utils/datetime.ts` 渲染，**不在本文件重写一份**
 *    （铁律 36：同一事实只能有一个推导源）。
 *
 * 交互：点击一条记录 → `onPickQuestion(question)` 把问题回填到首页提问框。
 * 这是原占位文案承诺过的行为（「点击可回填问题」），此处把它做实。
 * **刻意不自动发起查询** —— 点击只回填，是否执行由用户再按一次提交决定
 * （自动执行会直接产生一次真实 LLM 调用，不该由一次误点触发）。
 *
 * 取数写法与 `HomePage.tsx` 保持一致（inline async IIFE + `reloadToken`）：
 * 抽成独立 `useCallback` 会让 lint 的 `set-state-in-effect` 无法静态判定
 * 而误报；沿用既有模式可保持零新增告警。
 */

import { useCallback, useEffect, useState } from "react";

import { listHistory, type HistoryItemDto } from "../api/history";
import { formatRelativeTime } from "../utils/datetime";

/** 首页只展示最近若干条；完整列表（含分页/删除）在「历史记录」页 */
const RECENT_LIMIT = 5;

type LoadStatus = "loading" | "empty" | "error" | "data";

export function RecentActivity({
  onPickQuestion,
}: {
  /** 回填问题到首页提问框（必传：没有它按钮就是死的） */
  onPickQuestion: (question: string) => void;
}) {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [items, setItems] = useState<HistoryItemDto[]>([]);
  const [total, setTotal] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const data = await listHistory(1, RECENT_LIMIT, controller.signal);
        if (controller.signal.aborted) return;
        setItems(data.items);
        setTotal(data.total);
        setStatus(data.items.length === 0 ? "empty" : "data");
      } catch {
        if (controller.signal.aborted) return;
        // 失败即清空：不留陈旧列表，也不回退到任何静态数据
        setItems([]);
        setTotal(0);
        setStatus("error");
      }
    })();
    return () => controller.abort();
  }, [reloadToken]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadToken((token) => token + 1);
  }, []);

  const subtitle =
    status === "loading"
      ? "加载中…"
      : status === "error"
        ? "加载失败"
        : status === "empty"
          ? "暂无记录"
          : `共 ${total} 条 · 仅当前账号 · 来源 GET /api/history`;

  return (
    <section className="card chart-card recent-activity">
      <div className="chart-card__head">
        <h2 className="section-title">最近动态</h2>
        <span className="section-sub">{subtitle}</span>
      </div>

      {status === "loading" && (
        <div className="recent-activity__state">
          <span className="badge badge-processing">
            <span className="dot" />
            正在加载最近查询
          </span>
        </div>
      )}

      {status === "error" && (
        <div className="recent-activity__state">
          <span className="badge badge-error">
            <span className="dot" />
            最近动态加载失败
          </span>
          <p className="section-sub">这里不会回退到任何静态数据。</p>
          <button className="btn-ghost" type="button" onClick={retry}>
            重试
          </button>
        </div>
      )}

      {status === "empty" && (
        <div className="recent-activity__state">
          <p className="section-sub">暂无查询历史</p>
          <p className="section-sub">在「智能分析」提问后，记录会自动出现在这里</p>
        </div>
      )}

      {status === "data" && (
        <ul className="recent-activity__list">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="recent-activity__item"
                title="点击回填到提问框"
                onClick={() => onPickQuestion(item.question)}
              >
                <span className={`badge ${item.success ? "badge-success" : "badge-error"}`}>
                  <span className="dot" />
                  {item.success ? "成功" : "失败"}
                </span>
                <span className="recent-activity__question">{item.question}</span>
                <span className="recent-activity__time num">
                  {formatRelativeTime(item.created_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
