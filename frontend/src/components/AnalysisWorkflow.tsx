import type { AgentTraceEventDto } from "../api/agent";

export type StageStatus = "todo" | "active" | "done" | "error";
export type WorkflowPhase = "idle" | "loading" | "done" | "error";

export type AnalysisWorkflowProps = {
  /** 阶段下标：当前高亮到第几步（-1 = 未开始） */
  currentIndex: number;
  /** idle / loading / done / error */
  phase: WorkflowPhase;
  /** 后端真实 Trace（done/error 时用于映射阶段状态与详情） */
  trace?: AgentTraceEventDto[];
  /** Agent 生成的真实 SQL（用于「SQL 生成」阶段详情） */
  generatedSql?: string;
};

const STAGE_NAMES = [
  "问题理解",
  "Schema 匹配",
  "Few-shot",
  "SQL 生成",
  "SQL 校验",
  "SQL 执行",
  "结果生成",
];

/** 后端节点 -> 七个 UI 阶段（repair 节点归属「SQL 执行」子状态，不新增第 8 阶段） */
const NODE_TO_STAGE: Record<string, number> = {
  schema_link: 1,
  fewshot_retrieve: 2,
  sql_generate: 3,
  sql_safety: 4,
  sql_execute: 5,
  sql_repair: 5,
  sql_execute_repaired: 5,
  result: 6,
};

type EventsByName = Record<string, AgentTraceEventDto | undefined>;

const SUMMARY_TEXT: Record<string, string> = {
  question: "输入问题",
  Schema: "匹配方式",
  tables: "匹配表",
  columns_count: "字段数",
  confidence: "置信度",
  match_count: "匹配案例",
  example_ids: "示例",
  sql_length: "SQL 长度",
  allowed: "只读校验",
  row_count: "返回行数",
  truncated: "已截断",
  repair_success: "自动修复",
  repaired_sql_length: "修复后长度",
  success: "是否成功",
};

function SummaryList(props: { summary: Record<string, unknown> }) {
  const entries = Object.entries(props.summary).filter(([key]) =>
    typeof key === "string" && SUMMARY_TEXT[key] !== undefined,
  );
  if (!entries.length) return null;
  return (
    <div className="wf-detail__row">
      <span className="wf-detail__key">输出摘要</span>
      <span className="wf-chips">
        {entries.slice(0, 4).map(([key, value]) => (
          <code key={key} className="wf-chip">
            {SUMMARY_TEXT[key]}: {String(value)}
          </code>
        ))}
      </span>
    </div>
  );
}

/** 阶段详情：优先展示后端真实 Trace 摘要 */
function StageDetail({
  stage,
  events,
  generatedSql,
}: {
  stage: number;
  events: EventsByName;
  generatedSql?: string;
}) {
  switch (stage) {
    case 1: {
      const ev = events["schema_link"];
      if (!ev) return <EmptyDetail />;
      return (
        <div className="wf-detail fade-in">
          <SummaryList summary={ev.output_summary} />
          {ev.message && <DetailMessage text={ev.message} />}
        </div>
      );
    }
    case 2: {
      const ev = events["fewshot_retrieve"];
      if (!ev) return <EmptyDetail />;
      return (
        <div className="wf-detail fade-in">
          <SummaryList summary={ev.output_summary} />
        </div>
      );
    }
    case 3: {
      const ev = events["sql_generate"];
      if (!generatedSql) return <EmptyDetail />;
      return (
        <div className="wf-detail fade-in">
          {ev && <SummaryList summary={ev.output_summary} />}
          <pre className="wf-sql">
            <code>{generatedSql}</code>
          </pre>
        </div>
      );
    }
    case 4: {
      const ev = events["sql_safety"];
      if (!ev) return <EmptyDetail />;
      return (
        <div className="wf-detail fade-in">
          <SummaryList summary={ev.output_summary} />
          {ev.message && <DetailMessage text={ev.message} />}
        </div>
      );
    }
    case 5: {
      const ev = events["sql_execute"] ?? events["sql_execute_repaired"];
      const repair = events["sql_repair"];
      if (!ev) return <EmptyDetail />;
      return (
        <div className="wf-detail fade-in">
          <SummaryList summary={ev.output_summary} />
          {repair && repair.status === "success" && (
            <div className="wf-detail__row">
              <span className="wf-detail__key">自动修复</span>
              <span className="wf-detail__val wf-repair">
                检测到执行异常并已自动修复 1 次（{String(repair.output_summary?.repair_success ?? "true")}）
              </span>
            </div>
          )}
          {ev.message && <DetailMessage text={ev.message} />}
        </div>
      );
    }
    case 6:
      return (
        <div className="wf-detail fade-in">
          <span className="wf-done-text">Agent 流程执行完毕，见右侧结果区</span>
        </div>
      );
    default:
      return null;
  }
}

function EmptyDetail() {
  return (
    <div className="wf-detail fade-in">
      <span className="wf-detail__val">—</span>
    </div>
  );
}

function DetailMessage({ text }: { text: string }) {
  return (
    <div className="wf-detail__row">
      <span className="wf-detail__key">信息</span>
      <span className="wf-detail__val wf-msg">{text}</span>
    </div>
  );
}

/** 垂直 7 阶段 Agent 流程（状态来源：后端真实 Trace；loading 仅视觉滚动） */
export function AnalysisWorkflow({
  currentIndex,
  phase,
  trace = [],
  generatedSql,
}: AnalysisWorkflowProps) {
  const events: EventsByName = {};
  for (const event of trace) events[event.node] = event;

  const stateOf = (i: number): StageStatus => {
    if (phase === "loading") {
      // 不虚构已完成：仅当前阶段 active，其余保持待办
      return i === currentIndex ? "active" : "todo";
    }
    if (phase === "done") return "done";
    if (phase === "error") {
      // 定位第一个失败节点对应的阶段
      const failed = trace.find((e) => e.status === "error");
      const failedStage = failed ? (NODE_TO_STAGE[failed.node] ?? 6) : -1;
      if (failedStage < 0) return "todo";
      if (i < failedStage) return "done";
      if (i === failedStage) return "error";
      return "todo";
    }
    return "todo";
  };

  const runningTexts = [
    "正在理解问题…",
    "正在匹配 Schema…",
    "正在检索示例…",
    "正在生成 SQL…",
    "正在校验 SQL…",
    "正在执行查询…",
    "正在生成结果…",
  ];

  const headerBadge = (() => {
    if (phase === "loading")
      return (
        <span className="badge badge-processing">
          <span className="dot" />
          正在分析
        </span>
      );
    if (phase === "done")
      return (
        <span className="badge badge-success">
          <span className="dot" />
          分析完成
        </span>
      );
    if (phase === "error")
      return (
        <span className="badge badge-error">
          <span className="dot" />
          分析失败
        </span>
      );
    return (
      <span className="badge badge-warning">
        <span className="dot" />
        等待开始
      </span>
    );
  })();

  return (
    <section className="card wf-card">
      <div className="wf-card__head">
        <h2 className="section-title">Agent 执行流程</h2>
        {headerBadge}
      </div>

      <ol className="wf-stages">
        {STAGE_NAMES.map((name, i) => {
          const state = stateOf(i);
          const running = phase === "loading" && state === "active";
          const revealed =
            state === "done" || state === "active" || state === "error";
          return (
            <li key={name} className={`wf-stage wf-stage--${state}`}>
              <div className="wf-stage__head">
                <span className="wf-stage__dot">
                  {state === "done" ? "✓" : state === "error" ? "✗" : i + 1}
                </span>
                <span className="wf-stage__name">{name}</span>
                {running && <span className="wf-stage__hint">{runningTexts[i]}</span>}
                {state === "done" && <span className="wf-stage__hint">完成</span>}
                {state === "error" && <span className="wf-stage__hint">失败</span>}
              </div>
              {revealed && (
                <StageDetail
                  stage={i}
                  events={events}
                  generatedSql={generatedSql}
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}