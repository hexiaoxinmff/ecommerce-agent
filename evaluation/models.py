"""评测模型：单题结果 + 运行摘要 + 报告 CLI 输出结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvalCaseResult:
    """单题评测结果。"""

    eval_id: str
    question: str
    difficulty: str
    scenario: str
    operators: list[str]

    gold_sql: str
    pred_sql: str = ""
    initial_sql: str = ""
    final_sql: str = ""

    exec_success: bool = False
    exact_match: bool = False
    execution_accuracy: bool = False

    repair_triggered: bool = False
    repair_count: int = 0
    repair_success: bool = False

    failure_stage: str | None = None  # schema_link/fewshot/sql_generate/sql_safety/sql_execute/repair/result/provider/timeout
    error_type: str | None = None

    latency_ms: float = 0.0
    valid_model_run: bool = True  # provider 是否成功返回模型输出（非网络/超时错误）

    trace_summary: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalRunMeta:
    run_id: str
    timestamp: str
    dataset_version: str
    database_version: str
    schema_version: str
    seed: int
    model: str
    provider: str
    base_url: str
    prompt_version: str
    fewshot_version: str = ""
    experiment: str = ""
    randomness: str = "provider API controlled randomness unavailable"
    per_item_timeout_s: float = 60.0
    total_items: int = 0
    mode: str = "full"
    # Task 14.3：运行可复现性元数据（sha256 / 路径 / 数据库行数）
    prompt_sha256: str = ""
    fewshot_sha256: str = ""
    fewshot_path: str = ""
    dataset_sha256: str = ""
    db_table_counts: str = ""


@dataclass
class EvalRunSummary:
    meta: EvalRunMeta

    total: int = 0
    valid_model_runs: int = 0
    provider_failures: int = 0
    timeouts: int = 0

    exec_rate: float = 0.0
    ex: float = 0.0
    conditional_ex: float = 0.0
    pass_at_1: float = 0.0  # repair_count==0 且正确
    final_ex: float = 0.0  # 含 repair 后的正确率（= ex，语义区分）

    repair_trigger_rate: float = 0.0
    repair_success_rate: float = 0.0

    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0

    by_difficulty: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_scenario: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_operator: dict[str, dict[str, Any]] = field(default_factory=dict)
    failure_stages: dict[str, int] = field(default_factory=dict)
    error_types: dict[str, int] = field(default_factory=dict)