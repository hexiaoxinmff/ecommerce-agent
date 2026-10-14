/**
 * 历史记录页（P5）：接入真实 GET /api/history 与 DELETE /api/history/{id}。
 *
 * 四态明确分离：loading / empty / error / data（不得混排）。
 * 列表默认最新在前（后端 created_at 倒序）；展示 question、成功/失败标签、
 * result_summary、row_count、耗时、时间；SQL 折叠展开。
 * 删除：逐条 loading/disabled 防重复；404（记录已不存在）视为已删除并从列表移除。
 *
 * ⚠️ 时间显示（第九阶段 Phase F 修复）：后端 `created_at` 是 **UTC 带显式
 * 偏移** 的字符串（`appdb.now_iso()`），原先本页直接
 * `replace("T"," ").slice(0,19)` 截断 ⇒ 等于把 UTC 墙上时钟当本地时间展示
 * （北京用户看到的时间会早 8 小时，且页面无任何时区标记）。
 * 现改用 `utils/datetime.ts::formatDateTime` 按用户本地时区渲染；
 * 首页「最近动态」的相对时间共用同一模块（铁律 36：单一推导源）。
 */

import { useCallback, useEffect, useState } from "react";

import { HttpApiError } from "../api/http";
import { deleteHistory, listHistory, type HistoryItemDto } from "../api/history";
import { IconHistory } from "../components/Icons";
import { formatDateTime } from "../utils/datetime";

const PAGE_SIZE = 50;

type LoadStatus = "loading" | "error" | "empty" | "data";

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  return `${ms.toFixed(1)} ms`;
}

function HistoryRow({
  item,
  onDelete,
  deleting,
}: {
  item: HistoryItemDto;
  onDelete: (id: number) => void;
  deleting: boolean;
}) {
  return (
    <li className="history__row card">
      <div className="history__row-head">
        <span className={`badge ${item.success ? "badge-success" : "badge-error"}`}>
          <span className="dot" />
          {item.success ? "成功" : "失败"}
        </span>
        <span className="history__question">{item.question}</span>
        <span className="history__time num">{formatDateTime(item.created_at)}</span>
        <button
          className="btn-ghost history__delete"
          type="button"
          disabled={deleting}
          onClick={() => onDelete(item.id)}
        >
          {deleting ? "删除中…" : "删除"}
        </button>
      </div>

      <div className="history__meta num">
        <span>{item.result_summary || "—"}</span>
        <span>行数：{item.row_count ?? "—"}</span>
        <span>耗时：{formatDuration(item.total_time_ms)}</span>
      </div>

      {!item.success && item.error_message && (
        <p className="history__error">失败原因：{item.error_message}</p>
      )}

      {item.sql && (
        <details className="history__sql">
          <summary>SQL</summary>
          <pre>{item.sql}</pre>
        </details>
      )}
    </li>
  );
}

export function HistoryPage() {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [items, setItems] = useState<HistoryItemDto[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    setActionError(null);
    try {
      const data = await listHistory(1, PAGE_SIZE);
      setItems(data.items);
      setTotal(data.total);
      setPage(1);
      setHasMore(data.items.length < data.total);
      setStatus(data.items.length === 0 ? "empty" : "data");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 「data → empty」的派生状态转移统一在此收口：删除使可见列表清空时
  // 自动切到 empty 态。纯声明式，避免在 setState updater 内做副作用。
  useEffect(() => {
    if (status === "data" && items.length === 0) {
      setStatus("empty");
    }
  }, [status, items]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = page + 1;
      const data = await listHistory(next, PAGE_SIZE);
      setItems((prev) => [...prev, ...data.items]);
      setPage(next);
      setHasMore(items.length + data.items.length < data.total);
    } catch {
      setActionError("加载更多失败，请重试");
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id);
    setActionError(null);
    try {
      await deleteHistory(id);
      removeItem(id);
    } catch (err) {
      if (err instanceof HttpApiError && err.status === 404) {
        // 记录已不存在（可能已被删除）：从列表移除
        removeItem(id);
      } else {
        setActionError("删除失败，请重试");
      }
    } finally {
      setDeletingId(null);
    }
  }

  /**
   * 删除后的本地状态同步。
   *
   * Phase 4 竞态修复：两个 setState 都使用纯 updater，且绝不在 setItems
   * 的 updater 内部调用 setTotal/setStatus —— React 18 StrictMode（开发
   * 模式）会对 updater 做双重调用以暴露非纯更新，写在里面的副作用会被
   * 排队两次，导致 total 被连减两次（页面瞬时显示「少 2 条」的错误计数，
   * 刷新后才恢复）。函数式 updater 本身保证并发删除多条时不互相覆盖。
   */
  function removeItem(id: number) {
    setItems((prev) => prev.filter((item) => item.id !== id));
    setTotal((t) => Math.max(0, t - 1));
  }

  if (status === "loading") {
    return (
      <section className="history fade-in">
        <h2 className="section-title">历史记录</h2>
        <div className="history__state">
          <span className="badge badge-processing">
            <span className="dot" />
            正在加载历史记录
          </span>
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="history fade-in">
        <h2 className="section-title">历史记录</h2>
        <div className="history__state">
          <span className="badge badge-error">
            <span className="dot" />
            历史记录加载失败
          </span>
          <button className="btn-ghost" type="button" onClick={() => void load()}>
            重试
          </button>
        </div>
      </section>
    );
  }

  if (status === "empty") {
    return (
      <section className="history fade-in">
        <h2 className="section-title">历史记录</h2>
        <div className="history__state">
          <div className="history__empty-icon">
            <IconHistory size={36} />
          </div>
          <p className="section-sub">暂无查询历史</p>
          <p className="section-sub">在「智能分析」提问后，记录会自动出现在这里</p>
        </div>
      </section>
    );
  }

  return (
    <section className="history fade-in">
      <div className="history__head">
        <h2 className="section-title">历史记录</h2>
        <span className="section-sub num">共 {total} 条</span>
      </div>

      {actionError && (
        <p className="history__action-error" role="alert">
          {actionError}
        </p>
      )}

      <ul className="history__list">
        {items.map((item) => (
          <HistoryRow
            key={item.id}
            item={item}
            deleting={deletingId === item.id}
            onDelete={(id) => void handleDelete(id)}
          />
        ))}
      </ul>

      {hasMore && (
        <div className="history__more">
          <button className="btn-ghost" type="button" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? "加载中…" : "加载更多"}
          </button>
        </div>
      )}
    </section>
  );
}
