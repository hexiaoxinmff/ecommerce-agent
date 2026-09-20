"""Agent Trace 单元测试（fake 组件；闭环执行复用真实 SQLite）。

覆盖（≥25 项）：
- 正常路径 Trace 顺序与 skipped 补全；
- Repair 成功 / 最终失败路径 Trace；
- Safety 拒绝（sql_execute/repair/repaired = skipped，计数 0/0）；
- Provider 错误（schema_link=error、Trace 保留、无密钥泄漏、后续 skipped）；
- duration_ms >= 0、sequence 严格递增、节点唯一性；
- Trace 与 execute_count / repair_count 一致性；
- input/output 摘要轻量（不包含 rows / 完整 SQL / 用户数据）；
- 数据库零变更；TraceEvent Pydantic 校验。
"""

import hashlib

import pytest

from app.agent.graph import run_agent
from app.agent.models import AgentResult
from app.agent.nodes import AgentComponents
from app.core import config
from app.fewshot.models import FewShotMatch, FewShotResult
from app.llm.provider import LLMNetworkError
from app.schemas.schema_link import SchemaLinkResult
from app.schemas.sql_generate import SQLGenerationResult
from app.sqlexec.errors import SQLExecutionDatabaseError, SQLExecutionSafetyError
from app.sqlexec.models import SQLExecutionResult
from app.sqlrepair.errors import SQLRepairSafetyError
from app.sqlrepair.models import SQLRepairResult
from app.trace.models import TraceEvent

GOOD_SQL = "SELECT region, COUNT(*) AS c FROM users GROUP BY region"
BAD_SQL = "SELECT region, COUNT(*) AS c FROM user GROUP BY region"
REPAIRED_SQL = "SELECT region, COUNT(*) AS c FROM users GROUP BY region"

NODE_SEQUENCE = [
    "schema_link",
    "fewshot_retrieve",
    "sql_generate",
    "sql_safety",
    "sql_execute",
    "sql_repair",
    "sql_execute_repaired",
    "result",
]


def _link(question="q") -> SchemaLinkResult:
    return SchemaLinkResult(
        question=question,
        tables=["users"],
        columns=["users.region", "users.username"],
        reasons=["按地区统计用户"],
        confidence=0.9,
    )


def _fs(question="q") -> FewShotResult:
    return FewShotResult(
        question=question,
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


def _gen(sql=GOOD_SQL) -> SQLGenerationResult:
    return SQLGenerationResult(
        question="q",
        sql=sql,
        tables=["users"],
        columns=["users.region"],
        fewshot_examples=["ex_001"],
        explanation="e",
    )


def _ok_result() -> SQLExecutionResult:
    return SQLExecutionResult(
        columns=["region", "user_count"],
        rows=[["广东", 246]],
        row_count=1,
        truncated=False,
        execution_time_ms=1.0,
    )


class FakeSchemaLinker:
    def __init__(self, result=None, error=None):
        self._result = result or _link()
        self._error = error

    def link(self, question):
        if self._error:
            raise self._error
        return self._result


class FakeRetriever:
    def retrieve(self, query):
        return _fs(query.question)


class FakeGenerator:
    def __init__(self, sql=GOOD_SQL):
        self._sql = sql

    def generate_with_context(self, question, link_result, fs_result):
        return _gen(self._sql)


class FakeRepairer:
    def __init__(self, repaired=REPAIRED_SQL, error=None):
        self._repaired = repaired
        self._error = error

    def repair(self, request):
        if self._error is not None:
            raise self._error
        return SQLRepairResult(
            original_sql=request.original_sql,
            repaired_sql=self._repaired,
            repair_reason="修复表名 user->users",
        )


def _executor(bad_sql=BAD_SQL):
    def exe(sql):
        if bad_sql and sql.strip() == bad_sql.strip():
            raise SQLExecutionDatabaseError("no such table: user")
        return _ok_result()

    return exe


def _components(
    *,
    gen_sql=GOOD_SQL,
    executor=None,
    repairer=None,
    linker=None,
) -> AgentComponents:
    return AgentComponents(
        schema_linker=linker or FakeSchemaLinker(),
        fewshot_retriever=FakeRetriever(),
        sql_generator=FakeGenerator(gen_sql),
        sql_executor=executor or _executor(),
        sql_repairer=repairer or FakeRepairer(),
    )


def _nodes(result: AgentResult) -> dict[str, TraceEvent]:
    return {event.node: event for event in result.trace}


# ---------- 正常路径 ----------


def test_trace_normal_path_order() -> None:
    result = run_agent("q", _components())
    assert result.success is True
    # 顺序：前 5 个节点 + result
    expected = ["schema_link", "fewshot_retrieve", "sql_generate", "sql_safety", "sql_execute"]
    for index, node in enumerate(expected):
        event = result.trace[index]
        assert event.node == node
        assert event.status == "success"
    # 未执行节点补为 skipped
    assert result.trace[-3].node == "sql_repair" and result.trace[-3].status == "skipped"
    assert result.trace[-2].node == "sql_execute_repaired" and result.trace[-2].status == "skipped"
    assert result.trace[-1].node == "result" and result.trace[-1].status == "success"


def test_trace_full_node_coverage() -> None:
    result = run_agent("q", _components())
    assert [e.node for e in result.trace] == NODE_SEQUENCE


def test_trace_node_status_enum_valid() -> None:
    result = run_agent("q", _components())
    for event in result.trace:
        assert event.status in ("success", "error", "skipped")


def test_trace_sequence_strictly_increasing() -> None:
    result = run_agent("q", _components())
    sequences = [e.sequence for e in result.trace]
    assert sequences == sorted(sequences)
    assert sequences[0] == 1
    assert len(set(sequences)) == len(sequences)


def test_trace_duration_non_negative() -> None:
    result = run_agent("q", _components())
    for event in result.trace:
        assert event.duration_ms >= 0


def test_trace_node_uniqueness_normal() -> None:
    result = run_agent("q", _components())
    nodes = [e.node for e in result.trace]
    assert len(set(nodes)) == len(nodes)


def test_trace_matches_counts_normal() -> None:
    result = run_agent("q", _components())
    assert result.execute_count == 1
    assert result.repair_count == 0
    events = _nodes(result)
    assert events["sql_execute"].status == "success"
    assert events["sql_repair"].status == "skipped"


def test_trace_summaries_are_lightweight() -> None:
    result = run_agent("q", _components())
    events = _nodes(result)
    # 摘要不包含完整 rows / 完整 SQL 副本
    assert "rows" not in events["sql_execute"].output_summary
    assert "sql" not in events["sql_generate"].output_summary
    assert "email" not in str(events["sql_execute"].output_summary)
    assert events["sql_execute"].output_summary == {"row_count": 1, "truncated": False}


def test_trace_total_time_present() -> None:
    result = run_agent("q", _components())
    assert result.total_time_ms >= 0


# ---------- Repair 成功路径 ----------


def test_trace_repair_success_path() -> None:
    result = run_agent("q", _components(gen_sql=BAD_SQL))
    assert result.success is True
    assert result.execute_count == 2
    assert result.repair_count == 1
    events = _nodes(result)
    assert events["sql_execute"].status == "error"
    assert events["sql_execute"].message
    assert events["sql_repair"].status == "success"
    assert events["sql_execute_repaired"].status == "success"
    assert events["result"].status == "success"
    # 顺序严格正确
    order = [e.node for e in result.trace]
    assert order.index("sql_execute") < order.index("sql_repair") < order.index("sql_execute_repaired") < order.index("result")


def test_trace_repair_success_counts_consistent() -> None:
    result = run_agent("q", _components(gen_sql=BAD_SQL))
    events = _nodes(result)
    assert events["sql_execute"].status == "error"
    assert events["sql_execute_repaired"].status == "success"
    assert result.execute_count == 2
    assert result.repair_count == 1
    # Trace 中 repair/repaired 各恰好出现一次
    assert sum(1 for e in result.trace if e.node == "sql_repair") == 1
    assert sum(1 for e in result.trace if e.node == "sql_execute_repaired") == 1


def test_trace_repair_error_message_sanitized() -> None:
    result = run_agent("q", _components(gen_sql=BAD_SQL))
    assert "no such table: user" in _nodes(result)["sql_execute"].message


# ---------- Repair 最终失败 ----------


def test_trace_repair_still_fails() -> None:
    def always_fail(sql):
        raise SQLExecutionDatabaseError("still failing")

    result = run_agent("q", _components(gen_sql=BAD_SQL, executor=always_fail))
    assert result.success is False
    assert result.execute_count == 2
    assert result.repair_count == 1
    events = _nodes(result)
    assert events["sql_execute"].status == "error"
    assert events["sql_repair"].status == "success"
    assert events["sql_execute_repaired"].status == "error"
    assert result.repaired_sql  # 证据保留


# ---------- Safety 拒绝 ----------


def test_trace_safety_reject_marks_execute_skipped() -> None:
    result = run_agent("q", _components(gen_sql="DELETE FROM users"))
    assert result.success is False
    assert result.execute_count == 0
    assert result.repair_count == 0
    events = _nodes(result)
    assert events["sql_safety"].status == "error"
    assert events["sql_safety"].message
    assert events["sql_execute"].status == "skipped"
    assert events["sql_repair"].status == "skipped"
    assert events["sql_execute_repaired"].status == "skipped"


def test_trace_execute_safety_error_no_repair() -> None:
    def safety_error(sql):
        raise SQLExecutionSafetyError("SQL rejected: 多语句")

    result = run_agent("q", _components(executor=safety_error))
    assert result.success is False
    assert result.execute_count == 0
    assert result.repair_count == 0
    events = _nodes(result)
    assert events["sql_execute"].status == "error"
    assert events["sql_repair"].status == "skipped"


# ---------- Repair 拒绝 ----------


def test_trace_bad_repair_rejected_no_second_execute() -> None:
    result = run_agent(
        "q",
        _components(
            gen_sql=BAD_SQL,
            repairer=FakeRepairer(error=SQLRepairSafetyError("Repair Safety Rejected: 写操作")),
        ),
    )
    assert result.success is False
    assert result.execute_count == 1  # 只执行第一次
    assert result.repair_count == 1
    events = _nodes(result)
    assert events["sql_repair"].status == "error"
    assert events["sql_execute_repaired"].status == "skipped"
    assert "Safety" in result.final_error


# ---------- Provider 错误 ----------


def test_trace_provider_error_keeps_schema_error_event() -> None:
    result = run_agent(
        "q",
        _components(linker=FakeSchemaLinker(error=LLMNetworkError("Mimo network error"))),
    )
    assert result.success is False
    assert result.http_status == 503
    events = _nodes(result)
    assert events["schema_link"].status == "error"
    assert "Mimo network error" in events["schema_link"].message
    # 后续固定边节点被跳过
    assert events["fewshot_retrieve"].status == "skipped"
    assert events["sql_execute"].status == "skipped"
    assert events["sql_repair"].status == "skipped"
    assert events["sql_execute_repaired"].status == "skipped"
    # 不泄漏密钥/token
    assert "sk-" not in str(result.trace)


def test_trace_provider_error_counts_zero() -> None:
    result = run_agent(
        "q",
        _components(linker=FakeSchemaLinker(error=LLMNetworkError("Mimo network error"))),
    )
    assert result.execute_count == 0
    assert result.repair_count == 0
    assert result.trace  # Trace 不因异常丢失


# ---------- 一致性 & 零变更 ----------


@pytest.mark.parametrize(
    "scenario,gen_sql,executor,expected_exec,expected_repair",
    [
        ("normal", GOOD_SQL, _executor(), 1, 0),
        ("repair_success", BAD_SQL, _executor(), 2, 1),
        ("safety_reject", "DELETE FROM users", _executor(), 0, 0),
    ],
)
def test_trace_counts_consistent_with_events(scenario, gen_sql, executor, expected_exec, expected_repair) -> None:
    result = run_agent("q", _components(gen_sql=gen_sql, executor=executor))
    assert result.execute_count == expected_exec
    assert result.repair_count == expected_repair
    exec_events = [e for e in result.trace if e.node in ("sql_execute", "sql_execute_repaired")]
    # 成功执行事件数：normal/repair 成功为 1；safety 拒绝为 0
    expected_success_exec = 0 if expected_exec == 0 else 1
    assert sum(1 for e in exec_events if e.status == "success") == expected_success_exec
    # repair 节点非 skipped 事件数 == repair_count
    repair_events = [e for e in result.trace if e.node == "sql_repair" and e.status != "skipped"]
    assert len(repair_events) == expected_repair


def test_trace_database_unchanged_after_runs() -> None:
    hash_before = hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()
    run_agent("q", _components())  # 正常
    run_agent("q", _components(gen_sql=BAD_SQL))  # Repair
    run_agent("q", _components(gen_sql="DELETE FROM users"))  # Safety 拒绝
    run_agent(
        "q",
        _components(repairer=FakeRepairer(error=SQLRepairSafetyError("Reject"))),
    )
    assert hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest() == hash_before


def test_trace_events_are_valid_pydantic() -> None:
    result = run_agent("q", _components())
    for event in result.trace:
        assert isinstance(event, TraceEvent)


def test_agent_result_contains_trace_schema() -> None:
    result = run_agent("q", _components())
    assert isinstance(result.trace, list)
    assert result.trace[0].node == "schema_link"
    assert result.trace[0].input_summary == {"question": "q"}


def test_trace_skipped_has_explanatory_message() -> None:
    result = run_agent("q", _components(gen_sql="DELETE FROM users"))
    events = _nodes(result)
    assert events["sql_execute"].message  # "未执行（SQL Safety 未通过）"
    assert events["sql_execute_repaired"].message  # "未执行（未进入 Repair）"