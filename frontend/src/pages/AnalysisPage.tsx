import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentAnalysisResponseDto,
  AgentApiError,
  AgentResultDto,
} from "../api/agent";
import { analyzeQuestion } from "../api/agent";
import { AgentTrace } from "../components/AgentTrace";
import { AnalysisWorkflow } from "../components/AnalysisWorkflow";
import { ChartCard } from "../components/ChartCard";
import type { EChartOption } from "../components/ChartCard";
import { IconSpark } from "../components/Icons";
import { PresentationOverlay } from "../components/PresentationOverlay";
import { ResultTable } from "../components/ResultTable";
import { SqlPanel } from "../components/SqlPanel";
import { analysisExamples, agentStages } from "../data/demo";
import { buildChartOption } from "../utils/chart";

type AnalysisStatus = "idle" | "loading" | "success" | "error";

const STAGE_DURATION_MS = 700; // loading 视觉滚动（不虚构节点完成）

export function AnalysisPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [stageIndex, setStageIndex] = useState(-1);
  const [result, setResult] = useState<AgentResultDto | null>(null);
  const [errorInfo, setErrorInfo] = useState<{ title: string; detail: string } | null>(null);
  const [presentation, setPresentation] = useState(false);

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
  const toErrorInfo = (err: unknown): { title: string; detail: string } => {
    if (err !== null && typeof err === "object" && "status" in err) {
      const apiErr = err as AgentApiError;
      if (apiErr.status === 503 || apiErr.status === 502) {
        return {
          title: "分析服务暂时不可用",
          detail: `${apiErr.message}（Mimo 服务异常，请稍后重试。）`,
        };
      }
      if (apiErr.status === 422) {
        return { title: "请求不合法", detail: apiErr.message };
      }
      return { title: "分析失败", detail: apiErr.message };
    }
    if (err instanceof TypeError) {
      return {
        title: "无法连接分析服务",
        detail: "请确认后端服务已启动，再重试。",
      };
    }
    return {
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
        if (data.result) setResult(data.result);
        if (data.result && data.result.success) {
          setStatus("success");
        } else if (data.result) {
          // Agent 级最终失败（HTTP 200 但 success=false）：保留诊断证据
          setStatus("error");
          setErrorInfo({
            title: "分析未完成",
            detail:
              data.result.final_error ||
              data.result.repair_error ||
              data.result.execution_error ||
              "Agent 执行失败，详见下方诊断信息。",
          });
        } else {
          setStatus("error");
          setErrorInfo({ title: "分析失败", detail: data.error || "后端未返回结果。" });
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
      setErrorInfo({ title: "请输入问题", detail: "请先输入要分析的问题，再开始分析。" });
      return;
    }
    void runAnalysis(q);
  }, [query, runAnalysis]);

  const retry = useCallback(() => {
    if (query.trim()) void runAnalysis(query.trim());
  }, [query, runAnalysis]);

  const chartOption = useMemo(
    () => buildChartOption(result?.execution_result ?? null),
    [result],
  );

  const success = status === "success";
  const errorWithDiagnosis = status === "error" && result !== null;
  const showEvidence = success || errorWithDiagnosis;
  const sqlToShow = result?.repaired_sql || result?.generated_sql || "";

  // 汇报模式数据（全部来自真实结果，不伪造）
  const presentationStages = agentStages.map((name) => ({
    name,
    status: result?.success ? ("done" as const) : ("error" as const),
  }));
  const presentationRows = result?.execution_result?.row_count ?? 0;
  const presentationChart = chartOption ?? emptyChartOption();

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
          <span className="badge badge-success">
            <span className="dot" />
            ecommerce.db · 已连接
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

      {/* ② 流程 + ③ 结果 */}
      <div className="analysis-grid">
        <AnalysisWorkflow
          currentIndex={stageIndex}
          phase={status === "loading" ? "loading" : status === "idle" ? "idle" : status === "error" ? "error" : "done"}
          trace={result?.trace ?? []}
          generatedSql={result?.generated_sql}
        />

        <section className="card result-card">
          <div className="result-card__head">
            <h2 className="section-title">分析结果</h2>
            {success ? (
              <span className="badge badge-success">
                <span className="dot" />
                真实执行成功
              </span>
            ) : errorWithDiagnosis ? (
              <span className="badge badge-error">
                <span className="dot" />
                最终失败
              </span>
            ) : status === "loading" ? (
              <span className="badge badge-processing">
                <span className="dot" />
                分析中
              </span>
            ) : (
              <span className="badge badge-warning">
                <span className="dot" />
                等待开始
              </span>
            )}
          </div>

          {status === "success" && result?.success && (
            <div className="result-body fade-in">
              {result.execution_result ? (
                <>
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
                  </div>
                </>
              ) : (
                <div className="result-note">Agent 成功但未返回可展示的数据集。</div>
              )}
            </div>
          )}

          {status === "error" && (
            <div className="result-error fade-in">
              <span className="badge badge-error">
                <span className="dot" />
                分析失败
              </span>
              <h3 className="result-error__title">{errorInfo?.title ?? "分析失败"}</h3>
              <p className="result-error__reason">{errorInfo?.detail ?? ""}</p>
              <button type="button" className="btn-primary" onClick={retry}>
                重新分析
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setStatus("idle");
                  setErrorInfo(null);
                  setResult(null);
                }}
              >
                返回首页提问区
              </button>
            </div>
          )}

          {status === "loading" && (
            <div className="result-empty">
              <span className="badge badge-processing">
                <span className="dot" />
                Agent 正在理解问题并生成 SQL
              </span>
              <p>真实 Agent 正在执行：Schema 匹配 → SQL 生成 → 校验 → 执行。</p>
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
      </div>

      {/* 图表区域（真实结果映射） */}
      {success && result?.execution_result ? (
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
      ) : status === "error" ? null : (
        <section className="card chart-card">
          <div className="chart-card__head">
            <h2 className="section-title">数据可视化</h2>
            <span className="section-sub">分析完成后展示</span>
          </div>
          <div style={{ padding: "48px 0", textAlign: "center" }}>
            <span className="badge badge-warning">
              <span className="dot" />
              等待分析完成
            </span>
            <p className="section-sub" style={{ marginTop: 12 }}>
              真实查询结果将按规则映射为图表
            </p>
          </div>
        </section>
      )}

      {/* ④ SQL + Trace（真实证据） */}
      {showEvidence && sqlToShow && (
        <div className="analysis-grid analysis-grid--bottom fade-in">
          <SqlPanel
            sql={sqlToShow}
            defaultOpen
            subtitle={
              result?.repair_count
                ? "真实 SQL · 已自动修复 1 次"
                : "真实 SQL · Agent 生成 · SQLite 只读执行"
            }
          />
          <AgentTrace trace={result?.trace ?? []} />
        </div>
      )}

      {presentation && showEvidence && result && (
        <PresentationOverlay
          question={question}
          stages={presentationStages}
          resultValue={`${presentationRows} 行`}
          resultUnit="SQLite 查询结果"
          chartOption={presentationChart}
          chartAriaLabel="真实查询结果可视化"
          footer={`数据来源：ecommerce.db · SQLite 已连接  |  问题：${question}  |  真实 Agent API · 执行 ${result.execute_count} 次 · 修复 ${result.repair_count} 次`}
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