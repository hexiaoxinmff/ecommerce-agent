"""SQL Repair 数据结构与错误信息清洗。"""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.sqlexec.models import SQLExecutionResult


def sanitize_execution_error(message: str) -> str:
    """清洗 SQLite 错误信息：只保留错误主体，过滤明显敏感信息。

    - 过滤 Windows / POSIX 绝对路径；
    - 过滤疑似密钥的连续长字符串（如 sk-xxx、tp-xxx 或纯英文数字长串）；
    - 截断超长信息。
    """
    if not message:
        return ""
    text = message.replace("\n", " ").strip()
    text = re.sub(r"[A-Za-z]:\\[^\s:;,'\"]+", "<path>", text)
    text = re.sub(r"(?:/[\w.\-]+){2,}", "<path>", text)
    # 疑似密钥：sk-/tp-/其它 provider 前缀的连续 token
    text = re.sub(r"\b(?:sk|tp|ak|rk)-[A-Za-z0-9_\-]{8,}\b", "<secret>", text)
    text = re.sub(r"\b(?![A-Za-z]+\b)[A-Za-z0-9_\-]{24,}\b", "<secret>", text)
    return text[:500]


class SQLRepairRequest(BaseModel):
    """POST /api/sql/repair 请求体（Repair 能力单独测试）。"""

    question: str = Field(..., min_length=1, max_length=500)
    original_sql: str = Field(..., min_length=1, max_length=10000)
    error_message: str = Field(..., min_length=1, max_length=2000)
    # 可选：Schema Linking 提供的表/字段（用于 Schema 校验与 Few-shot 参考）
    tables: list[str] = []
    columns: list[str] = []

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question 不能为空")
        return value

    @field_validator("original_sql")
    @classmethod
    def reject_blank_sql(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_sql 不能为空")
        return value


class SQLRepairResult(BaseModel):
    """Repair 输出（保留修复前后证据）。"""

    original_sql: str
    repaired_sql: str
    repair_reason: str


class SQLRepairResponse(BaseModel):
    """POST /api/sql/repair 响应体。"""

    success: bool
    result: SQLRepairResult | None = None
    error: str = ""


class SQLExecuteWithRepairRequest(BaseModel):
    """POST /api/sql/execute-with-repair 请求体。"""

    question: str = Field(..., min_length=1, max_length=500)
    sql: str = Field(..., min_length=1, max_length=10000)
    tables: list[str] = []
    columns: list[str] = []

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question 不能为空")
        return value

    @field_validator("sql")
    @classmethod
    def reject_blank_sql(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sql 不能为空")
        return value


class SQLExecuteWithRepairResult(BaseModel):
    """闭环诊断结果（保留修复前后证据，供 Trace / Bad Case 分析）。"""

    question: str
    sql: str  # 原始 SQL
    execute_count: int
    repair_count: int
    original_error: str = ""
    repaired_sql: str = ""
    repair_reason: str = ""
    repair_error: str = ""
    result: SQLExecutionResult | None = None  # 最后一次成功执行的结果


class SQLExecuteWithRepairResponse(BaseModel):
    """POST /api/sql/execute-with-repair 响应体。"""

    success: bool
    result: SQLExecuteWithRepairResult | None = None
    error: str = ""