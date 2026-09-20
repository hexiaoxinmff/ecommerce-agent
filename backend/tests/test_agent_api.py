"""POST /api/agent/analyze API 测试（注入 fake 组件图，不调用 Mimo）。

覆盖：正常 200（success=true、计数）、空 question 422、
修复成功 200（execute_count=2）、最终失败 422 语义（success=false 仍 200 结构）、
Provider 网络错误 503。
"""

import pytest
from fastapi.testclient import TestClient

from app.agent import graph as graph_module
from app.agent.nodes import AgentComponents
from app.llm.provider import LLMNetworkError
from app.schemas.schema_link import SchemaLinkResult
from app.schemas.sql_generate import SQLGenerationResult
from app.sqlexec.errors import SQLExecutionDatabaseError
from app.sqlexec.models import SQLExecutionResult
from app.sqlrepair.models import SQLRepairResult


class _Linker:
    def link(self, question: str):
        return SchemaLinkResult(
            question=question,
            tables=["users"],
            columns=["users.region"],
            reasons=["按地区统计用户"],
            confidence=0.9,
        )


class _Retriever:
    def retrieve(self, query):
        from app.fewshot.models import FewShotMatch, FewShotResult

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
                    explanation="按地区统计",
                )
            ],
        )


class _Generator:
    def __init__(self, sql: str):
        self._sql = sql

    def generate_with_context(self, question, link_result, fs_result):
        return SQLGenerationResult(
            question=question,
            sql=self._sql,
            tables=["users"],
            columns=["users.region"],
            fewshot_examples=["ex_001"],
            explanation="按地区统计用户",
        )


class _Repairer:
    def __init__(self, repaired: str | None = None, error: Exception | None = None):
        self._repaired = repaired
        self._error = error

    def repair(self, request):
        if self._error is not None:
            raise self._error
        return SQLRepairResult(
            original_sql=request.original_sql,
            repaired_sql=self._repaired,
            repair_reason="修复表名",
        )


def _executor(bad_sql: str | None = "SELECT region, COUNT(*) AS c FROM user GROUP BY region"):
    def exe(sql: str):
        if bad_sql and sql.strip() == bad_sql.strip():
            raise SQLExecutionDatabaseError("no such table: user")
        return SQLExecutionResult(
            columns=["region", "user_count"],
            rows=[["广东", 246]],
            row_count=1,
            truncated=False,
            execution_time_ms=1.0,
        )

    return exe


def _install(
    monkeypatch,
    *,
    sql: str,
    repaired: str | None = None,
    link_error=None,
    executor=None,
):
    linker = _Linker()
    if link_error is not None:

        def boom(question):
            raise link_error

        linker.link = boom
    gen = _Generator(sql)
    repairer = _Repairer(repaired=repaired)
    comps = AgentComponents(
        schema_linker=linker,
        fewshot_retriever=_Retriever(),
        sql_generator=gen,
        sql_executor=executor or _executor(),
        sql_repairer=repairer,
    )
    graph = graph_module.build_agent(comps)
    monkeypatch.setattr(graph_module, "build_agent", lambda c=None: graph)
    return comps


def test_agent_analyze_ok(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, sql="SELECT region, COUNT(*) AS c FROM users GROUP BY region")
    response = client.post("/api/agent/analyze", json={"question": "哪个地区的用户最多？"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["error"] == ""
    result = data["result"]
    assert result["question"] == "哪个地区的用户最多？"
    assert result["execute_count"] == 1
    assert result["repair_count"] == 0
    assert result["execution_result"]["row_count"] == 1
    assert result["generated_sql"]


def test_agent_analyze_repair_success(client: TestClient, monkeypatch) -> None:
    _install(
        monkeypatch,
        sql="SELECT region, COUNT(*) AS c FROM user GROUP BY region",
        repaired="SELECT region, COUNT(*) AS c FROM users GROUP BY region",
    )
    response = client.post("/api/agent/analyze", json={"question": "哪个地区的用户最多？"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["success"] is True
    assert result["execute_count"] == 2
    assert result["repair_count"] == 1
    assert "FROM users" in result["repaired_sql"]


def test_agent_analyze_final_failure_success_false(client: TestClient, monkeypatch) -> None:
    # 修复后仍失败 => success=false（结构化返回，含诊断）
    def always_fail(sql: str):
        raise SQLExecutionDatabaseError("still failing")

    _install(
        monkeypatch,
        sql="SELECT region, COUNT(*) AS c FROM user GROUP BY region",
        repaired="SELECT region, COUNT(*) AS c FROM users GROUP BY region",
        executor=always_fail,
    )
    response = client.post("/api/agent/analyze", json={"question": "q"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    result = data["result"]
    assert result["execute_count"] == 2
    assert result["repair_count"] == 1
    assert result["final_error"]


def test_agent_analyze_empty_question_422(client: TestClient, monkeypatch) -> None:
    _install(monkeypatch, sql="SELECT 1")
    assert client.post("/api/agent/analyze", json={"question": "  "}).status_code == 422


def test_agent_analyze_provider_error_503(client: TestClient, monkeypatch) -> None:
    _install(
        monkeypatch,
        sql="SELECT 1",
        link_error=LLMNetworkError("Mimo network error"),
    )
    response = client.post("/api/agent/analyze", json={"question": "q"})
    assert response.status_code == 503
    assert response.json()["error"] == "Mimo network error"