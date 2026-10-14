import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentAnalysisResponseDto,
  AgentApiError,
  AgentExecutionResultDto,
  AgentResultDto,
} from "../api/agent";
import { analyzeQuestion } from "../api/agent";
import { classifyRequestFailure } from "../api/http";
import { AgentTrace } from "../components/AgentTrace";
import { AnalysisWorkflow } from "../components/AnalysisWorkflow";
import { ChartCard } from "../components/ChartCard";
import type { EChartOption } from "../components/ChartCard";
import { CollapsiblePanel } from "../components/CollapsiblePanel";
import { IconSpark } from "../components/Icons";
import { PresentationOverlay } from "../components/PresentationOverlay";
import { ResultTable } from "../components/ResultTable";
import { SqlPanel } from "../components/SqlPanel";
import { analysisExamples, agentStages } from "../data/uiCopy";
import { useHealthStatus } from "../hooks/useHealthStatus";
import {
  DB_CONNECTION_BADGE,
  DB_CONNECTION_WORD,
} from "../utils/connection";
import { buildChartOption } from "../utils/chart";

type AnalysisStatus = "idle" | "loading" | "success" | "error";

export type AnalysisPageProps = {
  /**
   * Phase 15（P0-3）：从首页提问框带过来的问题 —— 挂载后自动执行一次，
   * 消费完成回调 onInitialQuestionConsumed 清空，避免重复触发。
   */
  initialQuestion?: string | null;
  onInitialQuestionConsumed?: () => void;
};

/**
 * 错误四分类（第十二阶段 §九）：
 * - backend_unavailable：请求根本没到后端 → 「后端服务不可用 / 重新加载」
 * - service_unavailable：后端在但 LLM 上游 5xx → 「分析服务暂时不可用」
 * - invalid_request：422
 * - analysis_error：其余（含 Agent 级 success=false）
 */
type ErrorKind =
  | "analysis_error"
  | "service_unavailable"
  | "backend_unavailable"
  | "invalid_request";

type ErrorInfo = { kind: ErrorKind; title: string; detail: string };

const STAGE_DURATION_MS = 700; // loading 视觉滚动（不虚构节点完成）

type SingleValue = { column: string; value: unknown };

/** 单值结果判定：1 行 × 1 列且非空 → 适合 KPI 大数字展示（§五.2） */
function singleValueOf(exec: AgentExecutionResultDto | null): SingleValue | null {
  if (!exec || exec.columns.length !== 1 || exec.rows.length !== 1) return null;
  const value = exec.rows[0]?.[0];
  if (value === null || value === undefined) return null;
  return { column: exec.columns[0], value };
}

function formatKpiValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Intl.NumberFormat("en-US").format(value);
  }
  return String(value);
}

/** 耗时展示：<1s 显示 ms，否则显示 s（来源为真实 total_time_ms） */
function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function AnalysisPage({ initialQuestion, onInitialQuestionConsumed }: AnalysisPageProps) {
  const [query, setQuery] = useState(initialQuestion ?? "");
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [stageIndex, setStageIndex] = useState(-1);
  const [result, setResult] = useState<AgentResultDto | null>(null);
  const [dataAsOf, setDataAsOf] = useState("");
  const [errorInfo, setErrorInfo] = useState<ErrorInfo | null>(null);
  const [presentation, setPresentation] = useState(false);

  // 第九阶段 Phase E：连接状态不再硬编码「已连接」。
  // 库名与连接态都取自 GET /api/health 的真实返回值（与 Header / DbStatus 同源）。
  const { tone, health } = useHealthStatus();
  const dbName = health?.database?.name?.trim() || "数据库";

  const timerRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const cancelRequest = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      clearTimer();
      cancelRequest();
    };
  }, []);

  const startLoadingAnimation = useCallback(() => {
    setStageIndex(0);
    const step = (index: number) => {
      timerRef.current = window.setTimeout(() => {
        setStageIndex(index);
        if (index < 6) step(index + 1);
      }, STAGE_DURATION_MS);
    };
    timerRef.current = window.setTimeout(() => step(1), STAGE_DURATION_MS);
  }, []);

  /** 错误信息友好化：优先结构化错误，避免直接暴露开发者信息 */
  const toErrorInfo = (err: unknown): ErrorInfo => {
    if (err !== null && typeof err === "object" && "status" in err) {
      const apiErr = err as AgentApiError;
      if (apiErr.status === 503 || apiErr.status === 502) {
        return {
          kind: "service_unavailable",
          title: "分析服务暂时不可用",
          detail: `${apiErr.message}（LLM 服务异常，请稍后重试。）`,
        };
      }
      if (apiErr.status === 422) {
        return { kind: "invalid_request", title: "请求不合法", detail: apiErr.message };
      }
      return { kind: "analysis_error", title: "分析失败", detail: apiErr.message };
    }
    if (classifyRequestFailure(err) === "backend_unavailable") {
      return {
        kind: "backend_unavailable",
        title: "后端服务不可用",
        detail: "无法连接后端服务，请检查后端是否启动，再重新加载。",
      };
    }
    return {
      kind: "analysis_error",
      title: "分析失败",
      detail: err instanceof Error ? err.message : "发生未知错误，请重试。",
    };
  };

  const runAnalysis = useCallback(
    async (questionToRun: string) => {
      clearTimer();
      cancelRequest();
      setResult(null);
      setErrorInfo(null);
      setStatus("loading");
      startLoadingAnimation();

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const data: AgentAnalysisResponseDto = await analyzeQuestion(
          questionToRun,
          controller.signal,
        );
        // Phase 15（P0-1 最小版）：记录业务数据截止日，结果区展示「数据截至」
        setDataAsOf(data.data_as_of ?? "");
        if (data.result) setResult(data.result);
        if (data.result && data.result.success) {
          setStatus("success");
        } else if (data.result) {
          // Agent 级最终失败（HTTP 200 但 success=false）：保留诊断证据
          setStatus("error");
          setErrorInfo({
            kind: "analysis_error",
            title: "分析未完成",
            detail:
              data.result.final_error ||
              data.result.repair_error ||
              data.result.execution_error ||
              "Agent 执行失败，详见下方诊断信息。",
          });
        } else {
          setStatus("error");
          setErrorInfo({ kind: "analysis_error", title: "分析失败", detail: data.error || "后端未返回结果。" });
        }
      } catch (err) {
        if (controller.signal.aborted) return; // 已取消，忽略旧请求
        setResult(null);
        setStatus("error");
        setErrorInfo(toErrorInfo(err));
      } finally {
        clearTimer();
      }
    },
    [startLoadingAnimation],
  );

  const startAnalysis = useCallback(() => {
    const q = query.trim();
    if (!q) {
      clearTimer();
      cancelRequest();
      setResult(null);
      setStatus("error");
      setErrorInfo({
        kind: "invalid_request",
        title: "请输入问题",
        detail: "请先输入要分析的问题，再开始分析。",
      });
      return;
    }
    void runAnalysis(q);
  }, [query, runAnalysis]);

  // Phase 15（P0-3）：首页提问框带来的问题，挂载即真实执行（一次性消费）
  const consumedRef = useRef(false);
  useEffect(() => {
    if (initialQuestion && !consumedRef.current) {
      consumedRef.current = true;
      onInitialQuestionConsumed?.();
      void runAnalysis(initialQuestion);
    }
    // 仅挂载时消费一次；runAnalysis 闭包经 useCallback 稳定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retry = useCallback(() => {
    if (query.trim()) void runAnalysis(query.trim());
  }, [query, runAnalysis]);

  const resetToIdle = () => {
    setStatus("idle");
    setErrorInfo(null);
    setResult(null);
  };

  const chartOption = useMemo(
    () => buildChartOption(result?.execution_result ?? null),
    [result],
  );

  const success = status === "success";
  const errorWithDiagnosis = status === "error" && result !== null;
  const showEvidence = success || errorWithDiagnosis;
  const sqlToShow = result?.repaired_sql || result?.generated_sql || "";
  const traceEvents = result?.trace ?? [];
  const singleValue = singleValueOf(result?.execution_result ?? null);

  // 汇报模式数据（全部来自真实结果，不伪造）
  const presentationStages = agentStages.map((name) => ({
    name,
    status: result?.success ? ("done" as const) : ("error" as const),
  }));
  const presentationChart = chartOption ?? emptyChartOption();
  const presentationValue = singleValue
    ? formatKpiValue(singleValue.value)
    : `${result?.execution_result?.row_count ?? 0} 行`;

  const question = result?.question || query;

  return (
    <>
      {/* 页面标题行 */}
      <div className="analysis-page-head fade-in">
        <div>
          <h1 className="analysis-page-title">智能分析</h1>
          <span className="section-sub">用自然语言提问，Agent 自动完成 7 阶段分析</span>
        </div>
        <div className="analysis-page-head__right">
          <span className={`badge ${DB_CONNECTION_BADGE[tone]}`}>
            <span className="dot" />
            {dbName} · {DB_CONNECTION_WORD[tone]}
          </span>
          {status === "success" ? (
            <span className="badge badge-success">
              <span className="dot" />
              真实数据 · 分析完成
            </span>
          ) : status === "loading" ? (
            <span className="badge badge-processing">
              <span className="dot" />
              正在分析
            </span>
          ) : status === "error" ? (
            <span className="badge badge-error">
              <span className="dot" />
              分析失败
            </span>
          ) : (
            <span className="badge badge-warning">
              <span className="dot" />
              等待分析
            </span>
          )}
          <button
            type="button"
            className="btn-ghost"
            disabled={!showEvidence}
            onClick={() => setPresentation(true)}
            title={showEvidence ? "进入汇报模式" : "分析完成后可进入汇报模式"}
          >
            进入汇报模式
          </button>
        </div>
      </div>

      {/* ① 问题输入区 */}
      <section className="card analysis-input fade-in">
        <div className="analysis-input__label">
          <IconSpark size={16} />
          向数据提问
        </div>
        <div className="analysis-input__row">
          <div className="analysis-input__box">
            <IconSpark size={18} />
            <input
              type="text"
              placeholder="例如：哪个地区的用户最多？"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && status !== "loading") startAnalysis();
              }}
              aria-label="输入自然语言查询问题"
            />
          </div>
          <button
            type="button"
            className="btn-primary"
            onClick={startAnalysis}
            disabled={status === "loading"}
          >
            {status === "loading" ? "分析中…" : "开始分析"}
          </button>
        </div>
        <div className="analysis-input__foot">
          <div className="analysis-examples">
            {analysisExamples.map((q) => (
              <button
                key={q}
                type="button"
                className="hero__chip"
                onClick={() => setQuery(q)}
                disabled={status === "loading"}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ② 结果区（Result First：结果第一视觉中心，成功后用户无需滚动即见答案） */}
      {status !== "loading" && (
        <section className="card result-card fade-in" data-testid="result-card">
          <div className="result-card__head">
            <div>
              <h2 className="section-title">分析结果</h2>
              {(success || errorWithDiagnosis) && (
                <p className="result-card__question">{question}</p>
              )}
            </div>
            {success ? (
              <div className="result-card__status">
                <span className="badge badge-success">
                  <span className="dot" />
                  分析完成
                </span>
                {result && (
                  <span
                    className="result-card__duration num"
                    title="Agent 总耗时（真实）"
                  >
                    {formatDuration(result.total_time_ms)}
                  </span>
                )}
              </div>
            ) : status === "error" ? (
              <span className="badge badge-error">
                <span className="dot" />
                分析失败
              </span>
            ) : (
              <span className="badge badge-warning">
                <span className="dot" />
                等待开始
              </span>
            )}
          </div>

          {success && result?.success && result.execution_result && (
            <div className="result-body fade-in">
              {singleValue && (
                <div className="result-hero" data-testid="result-kpi">
                  <div className="result-hero__value num">
                    {formatKpiValue(singleValue.value)}
                  </div>
                  <div className="result-hero__label">{singleValue.column}</div>
                </div>
              )}
              <ResultTable result={result.execution_result} />
              <div className="result-meta">
                <div className="result-meta__item">
                  <span className="result-meta__key">返回行数</span>
                  <span className="result-meta__val num">
                    {result.execution_result.row_count}
                  </span>
                </div>
                <div className="result-meta__item">
                  <span className="result-meta__key">SQL 执行</span>
                  <span className="result-meta__val num">
                    {result.execute_count} 次
                  </span>
                </div>
                <div className="result-meta__item">
                  <span className="result-meta__key">自动修复</span>
                  <span className="result-meta__val num">
                    {result.repair_count} 次
                  </span>
                </div>
                <div className="result-meta__item">
                  <span className="result-meta__key">Agent 总耗时</span>
                  <span className="result-meta__val num">
                    {result.total_time_ms.toFixed(0)} ms
                  </span>
                </div>
              </div>
              {result.repair_count > 0 && (
                <div className="result-note result-note--repair">
                  Agent 检测到 SQL 执行异常并自动修复 {result.repair_count} 次
                  {result.repair_reason ? `：${result.repair_reason}` : ""}
                </div>
              )}
              <div className="result-note">
                {result.execution_result.truncated
                  ? "结果过多，仅展示前 500 行（已截断）"
                  : "以上为真实 SQLite 查询结果"}
                {dataAsOf && (
                  <>
                    {" · "}
                    数据截至 {dataAsOf}（相对时间如「本月/近30天」以该日期为业务锚点）
                    {" · "}
                    销售额口径：商品明细金额合计（排除已取消订单）
                  </>
                )}
              </div>
            </div>
          )}

          {success && result?.success && !result.execution_result && (
            <div className="result-note">Agent 成功但未返回可展示的数据集。</div>
          )}

          {status === "error" && (
            <div className="result-error fade-in" role="alert">
              <h3 className="result-error__title">{errorInfo?.title ?? "分析失败"}</h3>
              <p className="result-error__reason">{errorInfo?.detail ?? ""}</p>
              {errorWithDiagnosis && (
                <p className="result-error__evidence-note">
                  SQL 与 Trace 诊断证据已保留，可在下方「查看 SQL / 查看执行过程」展开。
                </p>
              )}
              <button type="button" className="btn-primary" onClick={retry}>
                {errorInfo?.kind === "backend_unavailable" ? "重新加载" : "重新分析"}
              </button>
              <button type="button" className="btn-ghost" onClick={resetToIdle}>
                返回提问区
              </button>
            </div>
          )}

          {status === "idle" && (
            <div className="result-empty">
              <span className="badge badge-warning">
                <span className="dot" />
                等待开始
              </span>
              <p>输入问题并点击「开始分析」，将调用真实 Agent API 完成本次分析。</p>
            </div>
          )}
        </section>
      )}

      {/* loading：结果位保持不变（分析中），进度流程卡紧随其后 */}
      {status === "loading" && (
        <>
          <section className="card result-card fade-in" data-testid="result-card">
            <div className="result-card__head">
              <div>
                <h2 className="section-title">分析结果</h2>
                {query && <p className="result-card__question">{query}</p>}
              </div>
              <span className="badge badge-processing">
                <span className="dot" />
                分析中
              </span>
            </div>
            <div className="result-empty">
              <span className="badge badge-processing">
                <span className="dot" />
                Agent 正在理解问题并生成 SQL
              </span>
              <p>真实 Agent 正在执行：Schema 匹配 → SQL 生成 → 校验 → 执行。</p>
            </div>
          </section>
          <AnalysisWorkflow currentIndex={stageIndex} phase="loading" />
        </>
      )}

      {/* ③ 图表区（图表属于结果，不属于 Trace —— 紧跟结果卡；单值结果 KPI 即是可视化） */}
      {success && result?.execution_result && !singleValue && (
        <div className="analysis-grid analysis-grid--charts fade-in">
          {chartOption ? (
            <ChartCard
              title="结果可视化"
              subtitle={`真实查询 · ${result.execution_result.row_count} 行`}
              option={chartOption}
            />
          ) : (
            <section className="card chart-card">
              <div className="chart-card__head">
                <h2 className="section-title">结果可视化</h2>
                <span className="section-sub">结果不适合图表，见结果表格</span>
              </div>
              <div style={{ padding: "48px 0", textAlign: "center" }}>
                <span className="badge badge-warning">
                  <span className="dot" />
                  未生成图表
                </span>
                <p className="section-sub" style={{ marginTop: 12 }}>
                  当前结果无法可靠识别为 2 维数值，仅展示表格。
                </p>
              </div>
            </section>
          )}
          <ChartCard
            title="执行诊断"
            subtitle="真实指标"
            option={metricChartOption(result)}
          />
        </div>
      )}

      {/* ④ 证据区（解释 / 审计层：SQL、执行流程、Trace 默认全部折叠） */}
      {showEvidence && (
        <div className="evidence-stack fade-in">
          <div className="evidence-stack__head">
            <h2 className="section-title">执行证据</h2>
            <span className="section-sub">解释与审计层 · 默认折叠，点击展开</span>
          </div>
          {sqlToShow && (
            <SqlPanel
              sql={sqlToShow}
              subtitle={
                result?.repair_count
                  ? "真实 SQL · 已自动修复 1 次"
                  : "真实 SQL · Agent 生成 · SQLite 只读执行"
              }
            />
          )}
          <CollapsiblePanel
            title="查看执行过程"
            subtitle="Agent 7 阶段 · 由真实 Trace 驱动"
          >
            <AnalysisWorkflow
              currentIndex={stageIndex}
              phase={success ? "done" : "error"}
              trace={traceEvents}
              generatedSql={result?.generated_sql}
            />
          </CollapsiblePanel>
          <CollapsiblePanel
            title="查看 Trace"
            subtitle={`后端真实执行轨迹 · ${traceEvents.length} 个节点`}
          >
            <AgentTrace trace={traceEvents} />
          </CollapsiblePanel>
        </div>
      )}

      {presentation && showEvidence && result && (
        <PresentationOverlay
          question={question}
          stages={presentationStages}
          resultValue={presentationValue}
          resultUnit={singleValue ? "真实查询结果" : "SQLite 查询结果"}
          chartOption={presentationChart}
          chartAriaLabel="真实查询结果可视化"
          footer={`数据来源：${dbName} · ${DB_CONNECTION_WORD[tone]}  |  问题：${question}  |  真实 Agent API · 执行 ${result.execute_count} 次 · 修复 ${result.repair_count} 次`}
          onExit={() => setPresentation(false)}
        />
      )}
    </>
  );
}

/** 执行诊断指标图（修复次数 / 执行次数 / 行数）真实数据 */
function metricChartOption(result: AgentResultDto): EChartOption {
  const rowCount = result.execution_result?.row_count ?? 0;
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 16, right: 24, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: "category",
      data: ["SQL 执行次数", "自动修复次数", "返回行数"],
      axisLabel: { color: "#8A96AA" },
    },
    yAxis: { type: "value", axisLabel: { color: "#8A96AA" } },
    series: [
      {
        name: "数值",
        type: "bar",
        data: [result.execute_count, result.repair_count, Math.min(rowCount, 500)],
        itemStyle: { color: "#8B7CF6" },
      },
    ],
    color: ["#8B7CF6"],
  };
}

/** 无可映射图表时的占位（空数据，不伪造） */
function emptyChartOption(): EChartOption {
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 16, right: 24, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: [], axisLabel: { color: "#8A96AA" } },
    yAxis: { type: "value", axisLabel: { color: "#8A96AA" } },
    series: [{ type: "bar", data: [] }],
  };
}
