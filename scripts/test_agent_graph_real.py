"""Agent Graph 真实 Mimo + Trace 验证脚本（允许真实调用 Mimo）。

用法（在项目根目录）：
    python scripts/test_agent_graph_real.py

链路：真实 Mimo 做完 Schema Linking / Generation / Repair（如需要）+ 真实 SQLite 执行。
输出：Question / Success / Generated SQL / Execute Count / Repair Count / Trace / Total Time。
禁止输出 API Key。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.agent.graph import run_agent  # noqa: E402
from app.core import config  # noqa: E402

QUESTION = "近30天销售额最高的商品有哪些？"


def main() -> int:
    print("=" * 70)
    print("Agent Graph 真实 Mimo + Trace 验证")
    print(f"LLM_PROVIDER : {config.LLM_PROVIDER}")
    print(f"MIMO_BASE_URL : {config.MIMO_BASE_URL or '(未设置)'}")
    print(f"MIMO_MODEL    : {config.MIMO_MODEL or '(未设置)'}")
    print(f"MIMO_API_KEY  : {'已设置(不显示内容)' if config.MIMO_API_KEY else '(未设置)'}")
    print("=" * 70)

    if not config.MIMO_API_KEY:
        print("Mimo API key is not configured")
        return 1

    try:
        result = run_agent(QUESTION)
    except Exception as exc:
        print(f"Question: {QUESTION}")
        print(f"Real Mimo：执行失败\n原因：{type(exc).__name__}: {exc}")
        return 1

    print(f"Question: {QUESTION}")
    print(f"Success: {result.success}")
    print(f"Generated SQL(前200字): {result.generated_sql[:200]}")
    if result.repaired_sql:
        print(f"Repaired SQL(前200字): {result.repaired_sql[:200]}")
    print(f"Execute Count: {result.execute_count}")
    print(f"Repair Count: {result.repair_count}")
    print(f"Total Time: {result.total_time_ms:.0f} ms")
    if result.execution_result is not None:
        print(f"Execution rows: {result.execution_result.row_count} "
              f"(columns={result.execution_result.columns})")
    print("Trace:")
    for event in result.trace:
        print(f"  #{event.sequence} {event.node:<22} {event.status:<8} "
              f"{event.duration_ms:9.1f}ms  {event.message[:60]}")
    print("=" * 70)
    print(f"Real Mimo：{'成功' if result.success else '失败'}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())