import type { AgentExecutionResultDto } from "../api/agent";

const MAX_ROWS = 50;

type ResultTableProps = {
  result: AgentExecutionResultDto;
};

/** 真实查询结果表格：columns × rows（超出行仅截断展示前 50） */
export function ResultTable({ result }: ResultTableProps) {
  const rows = result.rows.slice(0, MAX_ROWS);
  const hidden = result.rows.length - rows.length;

  return (
    <div className="result-table">
      <div className="result-table__scroll">
        <table className="result-table__grid">
          <thead>
            <tr>
              {result.columns.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={`${i}-${j}`}>{cell === null ? "null" : String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.truncated && (
        <div className="result-table__note">
          结果过多，仅展示前 500 行（该查询实际返回 &gt;500 行，已按保护上限截断）
        </div>
      )}
      {hidden > 0 && !result.truncated && (
        <div className="result-table__note">
          共 {result.row_count} 行，此处展示前 {rows.length} 行
        </div>
      )}
    </div>
  );
}