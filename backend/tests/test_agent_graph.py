"""LangGraph Agent 编排单元测试（全部组件注入 fake，闭环执行复用真实 SQLite）。

覆盖：全流程成功、一次 Repair 成功、Repair 后仍失败、Repair Safety 拒绝、
sql_safety 阶段拒绝（不 Repair）、执行 Safety 错误（不 Repair）、
计数矩阵（execute_count ≤ 2 / repair_count ≤ 1）、State 证据保留、
不重复调用（SchemaLinker/FewShotRetriever 各 1 次）、数据库零变更。
"""

import hashlib

import pytest

from app.agent.graph import build_agent, default_components, run_agent
from app.agent.nodes import AgentComponents
from app.core import config
from app.fewshot.models import FewShotMatch, FewShotResult
from app.schemas.schema_link import SchemaLinkResult
from app.schemas.sql_generate import SQLGenerationResult
from app.sqlexec.errors import SQLExecutionDatabaseError, SQLExecutionSafetyError
from app.sqlexec.models import SQLExecutionResult
from app.sqlrepair.errors import SQLRepairSafetyError
from app.sqlrepair.models import SQLRepairResult

GOOD_SQL = "SELECT region, COUNT(*) AS c FROM users GROUP BY region"
BAD_SQL = "SELECT region, COUNT(*) AS c FROM user GROUP BY region"
REPAIRED_SQL = "SELECT region, COUNT(*) AS c FROM users GROUP BY region"


def _link_result(question: str = "问题") -> SchemaLinkResult:
    return SchemaLinkResult(
        question=question,
        tables=["users"],
        columns=["users.region", "users.username"],
        reasons=["按地区统计用户"],
        confidence=0.9,
    )


def _fs_result(question: str = "问题") -> FewShotResult:
    return FewShotResult(
        question=question,
        matches=[
            FewShotMatch(
                example_id="ex_001",
                score=0.8,
                question="示例",
                scenario="user_region_distribution",
                tables=["users"],
                columns=["users.region"],
                sql="SELECT region FROM users",
                explanation="按地区统计用户",
            )
        ],
    )


class _Recorder:
    """记录调用次数。"""

    def __init__(self):
        self.calls = 0


class FakeSchemaLinker(_Recorder):
    def __init__(self, result):
        super().__init__()
        self._result = result

    def link(self, question: str) -> SchemaLinkResult:
        self.calls += 1
        return self._result


class FakeRetriever(_Recorder):
    def __init__(self, result):
        super().__init__()
        self._result = result

    def retrieve(self, query) -> FewShotResult:
        self.calls += 1
        return self._result


class FakeGenerator(_Recorder):
    def __init__(self, result: SQLGenerationResult):
        super().__init__()
        self._result = result

    def generate_with_context(self, question, link_result, fs_result) -> SQLGenerationResult:
        self.calls += 1
        return self._result


class FakeRepairer(_Recorder):
    def __init__(self, repaired: str | None = None, error: Exception | None = None):
        super().__init__()
        self._repaired = repaired
        self._error = error

    def repair(self, request) -> SQLRepairResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return SQLRepairResult(
            original_sql=request.original_sql,
            repaired_sql=self._repaired,
            repair_reason="修复表名 user->users",
        )


def _gen_result(sql: str = GOOD_SQL) -> SQLGenerationResult:
    return SQLGenerationResult(
        question="问题",
        sql=sql,
        tables=["users"],
        columns=["users.region"],
        fewshot_examples=["ex_001"],
        explanation="按地区统计用户",
    )


def _ok_exec_result() -> SQLExecutionResult:
    return SQLExecutionResult(
        columns=["region", "user_count"],
        rows=[["广东", 246]],
        row_count=1,
        truncated=False,
        execution_time_ms=1.0,
    )


def _make_executor(good_sql: str = GOOD_SQL, bad_sql: str = BAD_SQL):
    """模拟 executor：bad_sql 触发数据库错误，其余成功。"""

    def exe(sql: str) -> SQLExecutionResult:
        if bad_sql and sql.strip() == bad_sql.strip():
            raise SQLExecutionDatabaseError("no such table: user")
        return _ok_exec_result()

    return exe


def _components(
    *, gen_sql: str = GOOD_SQL, executor=None, repairer=None, link=None, retriever=None
) -> tuple[AgentComponents, dict[str, _Recorder]]:
    link = link or FakeSchemaLinker(_link_result())
    retriever = retriever or FakeRetriever(_fs_result())
    generator = FakeGenerator(_gen_result(gen_sql))
    executor = executor or _make_executor()
    repairer = repairer or FakeRepairer(repaired=REPAIRED_SQL)
    comps = AgentComponents(
        schema_linker=link,
        fewshot_retriever=retriever,
        sql_generator=generator,
        sql_executor=executor,
        sql_repairer=repairer,
    )
    return comps, {"link": link, "retriever": retriever, "generator": generator}


def test_agent_full_success_no_repair() -> None:
    comps, recorders = _components()
    result = run_agent("问题", comps)
    assert result.success is True
    assert result.execute_count == 1
    assert result.repair_count == 0
    assert result.generated_sql
    assert result.execution_result is not None
    assert result.execution_result.row_count == 1
    # Graph 中只调用一次 Schema Linking / Few-shot / Generation（无重复 Mimo）
    assert recorders["link"].calls == 1
    assert recorders["retriever"].calls == 1
    assert recorders["generator"].calls == 1


def test_agent_repair_success() -> None:
    comps, _ = _components(gen_sql=BAD_SQL)
    result = run_agent("问题", comps)
    assert result.success is True
    assert result.execute_count == 2
    assert result.repair_count == 1
    assert "FROM users" in result.repaired_sql
    assert result.repair_reason
    assert result.execution_result is not None


def test_agent_repair_still_fails_then_stops() -> None:
    # 第二次执行也失败 -> 最终失败，绝不第三次执行
    def always_fail(sql: str):
        raise SQLExecutionDatabaseError("still failing")

    comps, _ = _components(gen_sql=BAD_SQL, executor=always_fail)
    result = run_agent("问题", comps)
    assert result.success is False
    assert result.execute_count == 2
    assert result.repair_count == 1
    assert result.execution_result is None
    assert result.final_error
    # 证据保留
    assert result.repaired_sql
    assert result.execution_error


def test_agent_repair_safety_reject_stops() -> None:
    comps, _ = _components(
        gen_sql=BAD_SQL,
        repairer=FakeRepairer(error=SQLRepairSafetyError("Repair Safety Rejected: SQL 包含写操作")),
    )
    result = run_agent("问题", comps)
    assert result.success is False
    assert result.execute_count == 1  # repair 被拒后不再执行第二次
    assert result.repair_count == 1
    assert "Repair Safety" in result.final_error
    assert result.execution_result is None


def test_agent_sql_safety_reject_stops_without_repair() -> None:
    # 生成阶段产出危险 SQL：sql_safety 节点拒绝，execute_count=0、repair_count=0
    comps, _ = _components(gen_sql="DELETE FROM users")
    result = run_agent("问题", comps)
    assert result.success is False
    assert result.execute_count == 0
    assert result.repair_count == 0
    assert "Safety" in result.final_error


def test_agent_execute_safety_error_no_repair() -> None:
    def safety_error(sql: str):
        raise SQLExecutionSafetyError("SQL rejected: 只允许单条 SQL 语句")

    comps, _ = _components(executor=safety_error)
    result = run_agent("问题", comps)
    assert result.success is False
    assert result.execute_count == 0  # Safety 拒绝不计数
    assert result.repair_count == 0  # 禁止 Repair
    assert "Safety" in result.final_error


def test_agent_compiled_graph_invokable() -> None:
    graph = build_agent(_components()[0])
    state = graph.invoke({"question": "问题"})
    assert state["success"] is True
    assert state["execute_count"] == 1
    assert state.get("repair_count", 0) == 0  # 未触发 Repair 时该键不写入
    assert state["generated_sql"]


def test_agent_database_unchanged() -> None:
    hash_before = hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()
    # 真实 executor 全流程：成功路径
    import app.sqlexec.executor as real_exec

    comps_ok, _ = _components(gen_sql=GOOD_SQL)
    comps_ok.sql_executor = real_exec.execute
    run_agent("问题", comps_ok)
    # 恶意 repair 拒绝路径
    comps_bad, _ = _components(
        gen_sql=BAD_SQL,
        repairer=FakeRepairer(error=SQLRepairSafetyError("Reject")),
    )
    comps_bad.sql_executor = real_exec.execute
    run_agent("问题", comps_bad)
    assert hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest() == hash_before


def test_default_components_are_real_modules() -> None:
    comps = default_components()
    assert comps.schema_linker is not None
    assert comps.sql_generator is not None
    assert comps.sql_executor is not None
    assert comps.sql_repairer is not None