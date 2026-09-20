"""SQL Repair 单元测试（mock LLMProvider，闭环执行使用真实 SQLite 只读库）。

覆盖：
- Repairer：表错误/字段错误修复成功、Prompt 上下文、JSON 围栏解析；
- Validator：非法 JSON / reparsed_sql 空 / 写操作 / 多语句 / 表越界 / 列越界拒绝；
- Orchestrator 计数：无错误 1/0、修复成功 2/1、修复后仍失败 2/1、
  Safety 阶段拒绝 0/0、非法 Repair(Delete) 1/1 不执行二次；
- 数据库零变更；sanitize_execution_error 清洗。
"""

import hashlib
import json

import pytest

from app.core import config
from app.fewshot.models import FewShotResult
from app.sqlrepair.errors import (
    SQLRepairOutputInvalidError,
    SQLRepairSafetyError,
    SQLRepairSchemaError,
)
from app.sqlrepair.models import (
    SQLRepairRequest,
    sanitize_execution_error,
)
from app.sqlrepair.repairer import SQLExecuteWithRepairOrchestrator, SQLRepairer
from app.sqlrepair.validator import validate_repair_output
from app.schema.metadata import SchemaCatalog

USER_TABLES = ["users"]
USER_COLUMNS = ["users.region", "users.username"]


class _FakeProvider:
    name = "mimo"
    model = "mimo-v2.5-pro"

    def __init__(self, output: str = ""):
        self._output = output
        self.last_messages = None

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        self.last_messages = messages
        return self._output


class _FakeRetriever:
    def __init__(self, result: FewShotResult | None = None):
        self._result = result or FewShotResult(question="q", matches=[])

    def retrieve(self, query) -> FewShotResult:
        return self._result


def _repair_output(sql: str, reason: str = "修复表名") -> str:
    return json.dumps(
        {"repaired_sql": sql, "repair_reason": reason}, ensure_ascii=False
    )


def _repairer(output: str):
    return SQLRepairer(
        provider=_FakeProvider(output), fewshot_retriever=_FakeRetriever()
    )


# ---------- Repairer 修复成功 ----------


def test_repair_invalid_table_name() -> None:
    repaired = _repairer(
        _repair_output("SELECT region, COUNT(*) FROM users GROUP BY region", "修复表名 user->users")
    ).repair(
        SQLRepairRequest(
            question="哪个地区的用户最多？",
            original_sql="SELECT region, COUNT(*) FROM user GROUP BY region",
            error_message="no such table: user",
            tables=USER_TABLES,
            columns=USER_COLUMNS,
        )
    )
    assert repaired.original_sql == "SELECT region, COUNT(*) FROM user GROUP BY region"
    assert "FROM users" in repaired.repaired_sql
    assert repaired.repair_reason


def test_repair_invalid_column_name() -> None:
    repaired = _repairer(
        _repair_output("SELECT username FROM users", "修复字段 user_name->username")
    ).repair(
        SQLRepairRequest(
            question="查询用户名",
            original_sql="SELECT user_name FROM users",
            error_message="no such column: user_name",
            tables=["users"],
        )
    )
    assert repaired.repaired_sql == "SELECT username FROM users"


def test_repair_accepts_json_fence() -> None:
    output = f"```json\n{_repair_output('SELECT region, COUNT(*) AS c FROM users GROUP BY region')}\n```"
    repaired = _repairer(output).repair(
        SQLRepairRequest(
            question="问题", original_sql="SELECT x", error_message="e", tables=["users"]
        )
    )
    assert "FROM users" in repaired.repaired_sql


def test_repair_prompt_contains_full_context() -> None:
    provider = _FakeProvider(_repair_output("SELECT 1"))
    repairer = SQLRepairer(provider=provider, fewshot_retriever=_FakeRetriever())
    repairer.repair(
        SQLRepairRequest(
            question="哪个地区的用户最多？",
            original_sql="SELECT 1 FROM user",
            error_message="no such table: user",
            tables=USER_TABLES,
            columns=USER_COLUMNS,
        )
    )
    content = provider.last_messages[1]["content"]
    assert "哪个地区的用户最多？" in content
    assert "SELECT 1 FROM user" in content
    assert "no such table" in content
    assert "users.region" in content  # Schema Linking 字段
    assert "cancelled" in content  # 业务语义


# ---------- Validator 拒绝 ----------


def test_non_json_output_rejected() -> None:
    with pytest.raises(SQLRepairOutputInvalidError):
        validate_repair_output("这不是 JSON", "SELECT 1", USER_TABLES, SchemaCatalog.from_database())


def test_missing_fields_rejected() -> None:
    with pytest.raises(SQLRepairOutputInvalidError):
        validate_repair_output(
            '{"repaired_sql": ""}', "SELECT 1", USER_TABLES, SchemaCatalog.from_database()
        )


def test_repair_delete_rejected_as_safety() -> None:
    with pytest.raises(SQLRepairSafetyError, match="Safety"):
        validate_repair_output(
            _repair_output("DELETE FROM users"), "SELECT 1", USER_TABLES,
            SchemaCatalog.from_database(),
        )


def test_repair_multi_statement_rejected_as_safety() -> None:
    with pytest.raises(SQLRepairSafetyError):
        validate_repair_output(
            _repair_output("SELECT 1; DELETE FROM users"), "SELECT 1", USER_TABLES,
            SchemaCatalog.from_database(),
        )


def test_repair_table_out_of_scope_rejected() -> None:
    with pytest.raises(SQLRepairSchemaError, match="payments"):
        validate_repair_output(
            _repair_output("SELECT * FROM payments"), "SELECT 1", USER_TABLES,
            SchemaCatalog.from_database(),
        )


def test_repair_column_out_of_scope_rejected() -> None:
    with pytest.raises(SQLRepairSchemaError, match="user_name"):
        validate_repair_output(
            _repair_output("SELECT users.user_name FROM users"), "SELECT 1",
            USER_TABLES, SchemaCatalog.from_database(),
        )


# ---------- Orchestrator 计数 ----------


def _orchestrator(repair_output: str) -> SQLExecuteWithRepairOrchestrator:
    return SQLExecuteWithRepairOrchestrator(
        repairer=_repairer(repair_output)
    )


def test_orchestrator_no_error_execute_once() -> None:
    outcome = _orchestrator("").run("q", "SELECT region FROM users LIMIT 1", ["users"])
    assert outcome.execute_count == 1
    assert outcome.repair_count == 0
    assert outcome.result is not None
    assert outcome.result.row_count == 1


def test_orchestrator_repair_table_and_succeed() -> None:
    outcome = _orchestrator(
        _repair_output(
            "SELECT region, COUNT(*) AS user_count FROM users GROUP BY region",
            "修复表名 user->users",
        )
    ).run(
        "哪个地区的用户最多？",
        "SELECT region, COUNT(*) AS user_count FROM user GROUP BY region",
        USER_TABLES,
        USER_COLUMNS,
    )
    assert outcome.execute_count == 2
    assert outcome.repair_count == 1
    assert outcome.result is not None
    assert outcome.result.row_count > 0
    assert outcome.original_error  # 第一次错误被保留
    assert "FROM users" in outcome.repaired_sql


def test_orchestrator_repair_column_and_succeed() -> None:
    outcome = _orchestrator(
        _repair_output("SELECT username FROM users", "修复字段")
    ).run(
        "查询用户名",
        "SELECT user_name FROM users",
        ["users"],
        ["users.username"],
    )
    assert outcome.execute_count == 2
    assert outcome.repair_count == 1
    assert outcome.result is not None
    assert outcome.result.row_count > 0
    assert outcome.result.columns == ["username"]


def test_orchestrator_safety_reject_no_repair() -> None:
    outcome = _orchestrator("").run("q", "DELETE FROM users", ["users"])
    assert outcome.execute_count == 0  # Safety 阶段拒绝，未执行
    assert outcome.repair_count == 0  # 不触发 Repair
    assert outcome.result is None
    assert outcome.original_error


def test_orchestrator_bad_repair_delete_not_reexecuted() -> None:
    outcome = _orchestrator(_repair_output("DELETE FROM users")).run(
        "q", "SELECT region FROM user GROUP BY region", ["users"]
    )
    assert outcome.execute_count == 1  # 只执行了一次真实执行
    assert outcome.repair_count == 1  # Repair Safety Reject，不执行第二次
    assert outcome.result is None
    assert "Safety" in outcome.repair_error


def test_orchestrator_repair_still_fails_then_stops() -> None:
    # Repair 返回「通过校验但执行仍失败」的 SQL（无前缀列名不存在）
    outcome = _orchestrator(
        _repair_output("SELECT nonexistent_col FROM users", "尝试")
    ).run("q", "SELECT region FROM user GROUP BY region", ["users"])
    assert outcome.execute_count == 2  # 第一次 + 第二次各一次
    assert outcome.repair_count == 1
    assert outcome.result is None
    assert outcome.repair_error  # 第二次执行错误被保留
    assert outcome.original_error


# ---------- 数据库零变更 ----------


def test_database_unchanged_after_repair_cycle() -> None:
    hash_before = hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()
    _orchestrator(_repair_output(
        "SELECT region, COUNT(*) AS c FROM users GROUP BY region"
    )).run("q", "SELECT region FROM user GROUP BY region", ["users"])
    # 恶意 Repair 也应被拒且不改库
    _orchestrator(_repair_output("DROP TABLE users")).run(
        "q", "SELECT region FROM user GROUP BY region", ["users"]
    )
    assert hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest() == hash_before


# ---------- sanitize ----------


def test_sanitize_execution_error_filters_sensitive() -> None:
    raw = 'no such column: x at C:\\Users\\secret\\app.db near "sk-abcdef1234567890" /home/user/app/db.sqlite'
    cleaned = sanitize_execution_error(raw)
    assert "C:\\Users" not in cleaned
    assert "sk-abcdef1234567890" not in cleaned
    assert "/home/user" not in cleaned
    assert "no such column" in cleaned