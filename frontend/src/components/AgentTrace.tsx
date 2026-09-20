import type { AgentTraceEventDto } from "../api/agent";

const STATUS_TEXT: Record<AgentTraceEventDto["status"], string> = {
  success: "成功",
  error: "失败",
  skipped: "未执行",
};

type AgentTraceProps = {
  /** 后端返回的真实 Trace 事件列表 */
  trace: AgentTraceEventDto[];
};

/** Agent Trace：按后端真实事件渲染（node / status / duration / message / 摘要） */
export function AgentTrace({ trace }: AgentTraceProps) {
  return (
    <section className="card trace-panel">
      <div className="trace-panel__head">
        <h2 className="section-title">Agent Trace</h2>
        <span className="section-sub">后端真实执行轨迹 · {trace.length} 个节点</span>
      </div>
      <ol className="trace-list">
        {trace.map((event) => {
          const hasDetail =
            event.message ||
            Object.keys(event.input_summary).length > 0 ||
            Object.keys(event.output_summary).length > 0;
          return (
            <li key={`${event.sequence}-${event.node}`} className="trace-item">
              <span className="trace-item__time num">
                {event.duration_ms.toFixed(0)}ms
              </span>
              <span className="trace-item__line" />
              <div className="trace-item__body">
                <div className="trace-item__row">
                  <code className="trace-item__node">{event.node}</code>
                  <span className={`trace-status trace-status--${event.status}`}>
                    {STATUS_TEXT[event.status]}
                  </span>
                </div>
                {event.message && (
                  <div className="trace-item__msg">{event.message}</div>
                )}
                {hasDetail && (
                  <details className="trace-item__detail">
                    <summary>输入/输出摘要</summary>
                    <pre>{JSON.stringify(
                      { input: event.input_summary, output: event.output_summary },
                      null,
                      2,
                    )}</pre>
                  </details>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}