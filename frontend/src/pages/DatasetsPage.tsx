import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchHealth,
  fetchSchema,
  SystemApiError,
  type HealthResponseDto,
  type SchemaForeignKeyDto,
  type SchemaResponseDto,
} from "../api/system";
import { IconDatabase } from "../components/Icons";
import {
  DB_CONNECTION_BADGE,
  DB_CONNECTION_WORD,
  toDbConnectionTone,
} from "../utils/connection";
import "../styles/datasets.css";

/**
 * 数据集管理页（UI/UX v1.0 第 12 节 / PRD R-22）。
 *
 * 纯只读展示：数据库卡片 → 数据概览 → 按表分组的 Schema 表格。
 * 数据全部来自后端对真实 SQLite 的内省接口，页面不硬编码任何表名、
 * 字段名、类型或行数；不调用 Agent，也不触发任何 LLM 调用。
 */

type LoadStatus = "loading" | "success" | "error";

/** 千分位展示（仅格式化真实数值，不做任何推算） */
function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** 错误信息友好化：优先展示后端固定文案，不暴露内部细节 */
function toErrorInfo(err: unknown): { title: string; detail: string } {
  if (err instanceof SystemApiError) {
    if (err.status === 503) {
      return {
        title: "数据库暂时不可用",
        detail: `${err.message}（本页只读取数据库元数据，不依赖任何模型服务，可稍后重试。）`,
      };
    }
    return { title: "加载失败", detail: err.message };
  }
  if (err instanceof TypeError) {
    return {
      title: "无法连接后端服务",
      detail: "请确认后端服务已启动（默认 http://127.0.0.1:8000），再重试。",
    };
  }
  return {
    title: "加载失败",
    detail: err instanceof Error ? err.message : "发生未知错误，请重试。",
  };
}

export function DatasetsPage() {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [health, setHealth] = useState<HealthResponseDto | null>(null);
  const [schema, setSchema] = useState<SchemaResponseDto | null>(null);
  const [errorInfo, setErrorInfo] = useState<{ title: string; detail: string } | null>(null);
  const [activeTable, setActiveTable] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const [healthData, schemaData] = await Promise.all([
        fetchHealth(controller.signal),
        fetchSchema(controller.signal),
      ]);
      setHealth(healthData);
      setSchema(schemaData);
      setActiveTable((prev) =>
        schemaData.tables.some((item) => item.table === prev)
          ? prev
          : (schemaData.tables[0]?.table ?? ""),
      );
      setStatus("success");
    } catch (err) {
      if (controller.signal.aborted) return;
      setHealth(null);
      setSchema(null);
      setStatus("error");
      setErrorInfo(toErrorInfo(err));
    }
  }, []);

  /** 初始状态即 loading，挂载时无需重置；只有重试才需要显式回到 loading */
  const retry = useCallback(() => {
    setStatus("loading");
    setErrorInfo(null);
    void load();
  }, [load]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const activeSchema = useMemo(
    () => schema?.tables.find((item) => item.table === activeTable) ?? null,
    [schema, activeTable],
  );

  /** 外键按 from_column 建索引，供表格逐字段展示 */
  const foreignKeyByColumn = useMemo(() => {
    const map = new Map<string, SchemaForeignKeyDto>();
    for (const fk of activeSchema?.foreign_keys ?? []) {
      map.set(fk.from_column, fk);
    }
    return map;
  }, [activeSchema]);

  // 第九阶段 Phase E：连接态推导统一走 utils/connection.ts。
  // 本页沿用自己那次 /api/health 请求（与 schema 并发），不额外再取一次；
  // 关键是**词表与徽标与其他三处同源**，避免同一个事实在不同页面说成不同的话。
  const tone = toDbConnectionTone(status, health);
  const databaseName = schema?.database ?? health?.database.name ?? "—";

  const connectionBadge = (
    <span className={`badge ${DB_CONNECTION_BADGE[tone]}`}>
      <span className="dot" />
      {DB_CONNECTION_WORD[tone]}
    </span>
  );

  return (
    <>
      {/* 页面标题行 */}
      <div className="ds-page-head fade-in">
        <div>
          <h1 className="ds-page-title">数据集管理</h1>
          <span className="section-sub">
            当前 SQLite 数据集的连接状态、数据规模与 Schema 结构（只读展示）
          </span>
        </div>
      </div>

      {/* ① 数据库卡片（UI/UX 12.1） */}
      <section className="card ds-db fade-in">
        <div className="ds-db__head">
          <div>
            <div className="ds-db__file">
              <IconDatabase size={18} />
              {databaseName}
              <span className="ds-db__type">{health?.database.type ?? "SQLite"}</span>
            </div>
            <span className="section-sub ds-db__sub">
              当前开发数据库 · 合成数据 · 后端只读连接（mode=ro + PRAGMA query_only）
            </span>
          </div>
          {connectionBadge}
        </div>
      </section>

      {/* ② 数据概览（UI/UX 12.2） */}
      {status === "success" && schema ? (
        <div className="ds-stats fade-in">
          <div className="card ds-stat">
            <span className="ds-stat__label">业务表数量</span>
            <span className="ds-stat__value num">{formatCount(schema.tables.length)}</span>
            <span className="ds-stat__unit">张</span>
          </div>
          {schema.tables.map((item) => (
            <div className="card ds-stat" key={item.table}>
              <span className="ds-stat__label" title={`${item.table} · ${item.description}`}>
                {item.description || item.table}
              </span>
              <span className="ds-stat__value num">{formatCount(item.row_count)}</span>
              <span className="ds-stat__unit">{item.table} · 行</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* ③ Schema 表格（UI/UX 12.3，按表分组） */}
      <section className="card fade-in">
        <div className="ds-schema-head">
          <h2 className="section-title">Schema 结构</h2>
          <span className="section-sub">
            {status === "success" && schema
              ? `${formatCount(schema.tables.length)} 张表 · 字段、类型、主键、外键与业务口径`
              : "字段、类型、主键、外键与业务口径"}
          </span>
        </div>

        {status === "loading" ? (
          <div className="ds-state">
            <span className="badge badge-processing">
              <span className="dot" />
              正在读取真实数据库结构
            </span>
            <p>后端正在内省 sqlite_master 与 PRAGMA table_info / foreign_key_list。</p>
          </div>
        ) : status === "error" ? (
          <div className="ds-state">
            <span className="badge badge-error">
              <span className="dot" />
              加载失败
            </span>
            <p className="ds-state__title">{errorInfo?.title ?? "加载失败"}</p>
            <p>{errorInfo?.detail ?? ""}</p>
            <div className="ds-state__actions">
              <button type="button" className="btn-primary" onClick={retry}>
                重新加载
              </button>
            </div>
          </div>
        ) : !schema || schema.tables.length === 0 ? (
          <div className="ds-state">
            <span className="badge badge-warning">
              <span className="dot" />
              未发现业务表
            </span>
            <p>当前数据库中没有可展示的业务表。</p>
          </div>
        ) : (
          <>
            <div className="ds-tabs" role="tablist" aria-label="按表分组">
              {schema.tables.map((item) => (
                <button
                  key={item.table}
                  type="button"
                  role="tab"
                  id={`ds-tab-${item.table}`}
                  aria-selected={item.table === activeTable}
                  aria-controls={`ds-panel-${item.table}`}
                  className={`ds-tab${item.table === activeTable ? " ds-tab--active" : ""}`}
                  onClick={() => setActiveTable(item.table)}
                  title={item.description}
                >
                  {item.table}
                </button>
              ))}
            </div>

            <div
              className="ds-schema-body"
              role="tabpanel"
              id={`ds-panel-${activeTable}`}
              aria-labelledby={`ds-tab-${activeTable}`}
            >
              {activeSchema ? (
                <>
                  <div className="ds-table-head">
                    <span className="ds-table-name">{activeSchema.table}</span>
                    <span className="ds-table-desc">
                      {activeSchema.description} · {formatCount(activeSchema.columns.length)} 个字段 ·{" "}
                      {formatCount(activeSchema.row_count)} 行
                    </span>
                  </div>

                  <div className="result-table">
                    <div className="result-table__scroll">
                      <table className="result-table__grid">
                        <thead>
                          <tr>
                            <th>字段</th>
                            <th>类型</th>
                            <th>主键</th>
                            <th>外键</th>
                            <th>业务说明</th>
                          </tr>
                        </thead>
                        <tbody>
                          {activeSchema.columns.map((column) => {
                            const fk = foreignKeyByColumn.get(column.name);
                            return (
                              <tr key={column.name}>
                                <td className="ds-field">{column.name}</td>
                                <td className="ds-type">{column.type || "—"}</td>
                                <td>
                                  {column.primary_key ? (
                                    <span className="ds-pk">✓</span>
                                  ) : (
                                    <span className="ds-none">—</span>
                                  )}
                                </td>
                                <td>
                                  {fk ? (
                                    <span className="ds-fk">
                                      → {fk.to_table}.{fk.to_column}
                                    </span>
                                  ) : (
                                    <span className="ds-none">—</span>
                                  )}
                                </td>
                                <td>{column.description || <span className="ds-none">—</span>}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="result-table__note">
                      {activeSchema.table} · {formatCount(activeSchema.columns.length)} 个字段 ·{" "}
                      {formatCount(activeSchema.row_count)} 行 · 外键{" "}
                      {formatCount(activeSchema.foreign_keys.length)} 条
                    </div>
                  </div>
                </>
              ) : null}
            </div>
          </>
        )}

        <div className="ds-note">
          本页为只读展示页，数据来自后端对真实 SQLite 数据库的内省结果，不提供编辑。
        </div>
      </section>
    </>
  );
}
