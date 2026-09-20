import { agentStages, demoResult } from "../data/demo";

export type FlowPhase = "idle" | "running" | "done" | "error";

type AnalysisFlowProps = {
  question: string;
  phase: FlowPhase;
  currentIndex: number; // 当前执行到的阶段下标（-1 表示尚未开始）
  onCancel: () => void;
};

/**
 * Demo 分析流程面板：7 阶段链路（UI/UX v1.0 第 10.2 节）。
 * 问题理解 → Schema 匹配 → Few-shot → SQL 生成 → SQL 校验 → SQL 执行 → 结果生成
 */
export function AnalysisFlow({ question, phase, currentIndex, onCancel }: AnalysisFlowProps) {
  const stageState = (i: number): "done" | "active" | "todo" | "error" => {
    if (phase === "done") return "done";
    if (phase === "error") return i < currentIndex ? "done" : i === currentIndex ? "error" : "todo";
    if (phase === "running") return i < currentIndex ? "done" : i === currentIndex ? "active" : "todo";
    return "todo";
  };

  return (
    <section className="card flow-card fade-in">
      <div className="flow-card__head">
        <h2 className="section-title">分析流程</h2>
        {phase === "running" ? (
          <span className="badge badge-processing">
            <span className="dot" />
            正在分析
          </span>
        ) : phase === "done" ? (
          <span className="badge badge-success">
            <span className="dot" />
            分析完成
          </span>
        ) : (
          <span className="badge badge-warning">
            <span className="dot" />
            Demo 模式
          </span>
        )}
      </div>

      {question && <div className="flow-card__question">问题：{question}</div>}

      <div className="flow-stages" aria-label="Agent 7 阶段分析流程">
        {agentStages.map((stage, i) => {
          const state = stageState(i);
          return (
            <div
              key={stage}
              className={`flow-stage flow-stage--${state}`}
              aria-current={state === "active" ? "step" : undefined}
            >
              <div className="flow-stage__dot">
                {state === "done" ? "✓" : state === "error" ? "✗" : i + 1}
              </div>
              <div className="flow-stage__name">{stage}</div>
            </div>
          );
        })}
      </div>

      {phase === "done" && (
        <div className="flow-result">
          <div>
            <div className="flow-result__label">查询结果</div>
            <div className="flow-result__value num">{demoResult.value}</div>
          </div>
          <div className="flow-result__unit">{demoResult.unit}</div>
          <div style={{ marginLeft: "auto", textAlign: "right" }}>
            <span className="badge badge-success">
              <span className="dot" />
              SQL 校验通过 · 执行成功
            </span>
          </div>
        </div>
      )}

      {phase === "running" && (
        <div className="flow-result__note" style={{ color: "var(--color-text-secondary)" }}>
          <span className="badge badge-processing">
            <span className="dot" />
            {agentStages[currentIndex] ?? "准备中"}…
          </span>
          <button type="button" className="btn-ghost" style={{ marginLeft: 12 }} onClick={onCancel}>
            取消
          </button>
        </div>
      )}

      {(phase === "done" || phase === "error") && (
        <div className="flow-result__note">Demo 模式：暂未连接后端，以上为静态演示数据。</div>
      )}
    </section>
  );
}
