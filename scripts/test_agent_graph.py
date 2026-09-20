"""Agent Graph 真实 SQLite Trace 验证脚本（不调用 Mimo；fake LLM 组件）。

用法（在项目根目录）：
    python scripts/test_agent_graph.py

三种场景，全部使用真实 db/ecommerce.db 只读执行：
1. 正常查询       2. Execute Error -> Repair -> Execute Success   3. Safety Reject
打印 Sequence / Node / Status / Duration / Message 与最终计数。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.agent.graph import run_agent  # noqa: E402
from app.agent.nodes import AgentComponents  # noqa: E402
from app.fewshot.models import FewShotMatch, FewShotResult  # noqa: E402
from app.schemas.schema_link import SchemaLinkResult  # noqa: E402
from app.schemas.sql_generate import SQLGenerationResult  # noqa: E402
from app.sqlrepair.models import SQLRepairResult  # noqa: E402
from app.sqlexec.executor import execute as real_executor  # noqa: E402


class FakeLinker:
    def link(self, question):
        return SchemaLinkResult(
            question=question,
            tables=["users"],
            columns=["users.region", "users.username"],
            reasons=["按地区统计用户"],
            confidence=0.9,
        )


class FakeRetriever:
    def retrieve(self, query):
        return FewShotResult(
            question=query.question,
            matches=[
                FewShotMatch(
                    example_id="ex_001",
                    score=0.8,
                    question="示例",
                    scenario="u",
                    tables=["users"],
                    columns=["users.region"],
                    sql="SELECT 1",
                    explanation="e",
                )
            ],
        )


class FakeGenerator:
    def __init__(self, sql):
        self._sql = sql

    def generate_with_context(self, question, link_result, fs_result):
        return SQLGenerationResult(
            question=question,
            sql=self._sql,
            tables=["users"],
            columns=["users.region"],
            fewshot_examples=["ex_001"],
            explanation="e",
        )


class FakeRepairer:
    def __init__(self, repaired):
        self._repaired = repaired

    def repair(self, request):
        return SQLRepairResult(
            original_sql=request.original_sql,
            repaired_sql=self._repaired,
            repair_reason="修复表名 user->users（真实 SQLite 第二次执行）",
        )


def _components(gen_sql, repaired=None) -> AgentComponents:
    return AgentComponents(
        schema_linker=FakeLinker(),
        fewshot_retriever=FakeRetriever(),
        sql_generator=FakeGenerator(gen_sql),
        sql_executor=real_executor,
        sql_repairer=FakeRepairer(repaired or gen_sql),
    )


def _scenarios() -> list[tuple[str, AgentComponents]]:
    return [
        (
            "正常查询",
            _components("SELECT region, COUNT(*) AS c FROM users GROUP BY region"),
        ),
        (
            "Execute Error -> Repair -> Execute Success",
            _components(
                "SELECT region, COUNT(*) AS c FROM user GROUP BY region",
                repaired="SELECT region, COUNT(*) AS c FROM users GROUP BY region",
            ),
        ),
        (
            "Safety Reject",
            _components("DELETE FROM users"),
        ),
    ]


def _print_result(label: str, result) -> None:
    print("-" * 70)
    print(f"Scenario: {label}")
    print(f"Success: {result.success} | execute_count={result.execute_count} "
          f"| repair_count={result.repair_count} | total_time_ms={result.total_time_ms}")
    if result.generated_sql:
        print(f"Generated SQL: {result.generated_sql[:120]}")
    if result.repaired_sql:
        print(f"Repaired SQL: {result.repaired_sql[:120]}")
    if result.execution_result is not None:
        print(f"Execution rows: {result.execution_result.row_count} "
              f"(columns={result.execution_result.columns})")
    print("Trace:")
    for event in result.trace:
        print(f"  #{event.sequence} {event.node:<22} {event.status:<8} "
              f"{event.duration_ms:8.2f}ms  {event.message[:60]}"
              + (f"  out={json.dumps(event.output_summary, ensure_ascii=False)}" if event.output_summary else ""))


def main() -> int:
    print("=" * 70)
    print("Agent Graph 真实 SQLite Trace 验证（fake LLM，不调用 Mimo）")
    print("=" * 70)
    ok = True
    for label, components in _scenarios():
        try:
            result = run_agent("哪个地区的用户最多？", components)
            _print_result(label, result)
            if label == "Safety Reject" and result.execute_count != 0:
                ok = False
        except Exception as exc:
            print(f"Scenario {label} 执行异常：{type(exc).__name__}: {exc}")
            ok = False
    print("=" * 70)
    print(f"Agent Graph 真实 SQLite 验证：{'成功' if ok else '存在失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())