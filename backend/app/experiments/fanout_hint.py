"""E3 Fan-out 提示型干预（Task 20 实验模块，独立实验配置，不修改正式 Prompt/Generator）。

最小干预方案（同一次生成增加 prompt，而非 Repair / 第二 Agent / AST rewrite）：
- SQLGenerator 生成 SQL 后，用 analyze_fanout 检测；
- fan_out_suspected=false → hint = None（不向 prompt 添加任何内容）；
- fan_out_suspected=true → 生成 FANOUT_RECHECK_HINT 文本，作为额外的 user message
  追加在原始 messages 之后，复用原始 schema/few-shot 上下文重新生成一次 final SQL。

边界：
- 不修改检测器规则；
- 不修改 SQLGenerator / prompt.py / 任何正式文件；
- 不调用 repair 分支；
- 提示只在 detector alarm 时注入。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.fewshot.models import FewShotResult  # noqa: E402
from app.llm.provider import LLMProvider, get_llm_provider  # noqa: E402
from app.schemas.schema_link import SchemaLinkResult  # noqa: E402
from app.sqlcheck.fanout_detector import analyze_fanout  # noqa: E402
from app.sqlgen.prompt import SYSTEM_PROMPT, build_prompt  # noqa: E402
from app.sqlgen.validator import parse_llm_output, validate_output  # noqa: E402
from app.schema.metadata import SchemaCatalog  # noqa: E402

FANOUT_RECHECK_HINT = """【Fan-out 自检提示】
检测到当前 SQL 存在潜在 1:N Join 粒度风险（orders × order_items）。
请重新检查 SQL 中 orders 与 order_items 的 Join 粒度：

- 如果聚合函数作用于 orders 级字段（例如 orders.total_amount、订单数），请确认
  是否会因 order_items 的多行展开导致重复累加 / 重复计数；
- 不要修改查询需求的业务语义；
- 优先通过订单级预聚合（先按订单分组后聚合）、独立聚合后再按维度 JOIN、或使用
  EXISTS / 去重等方式避免重复累计；
- 注意：item-level 指标（例如 order_items.subtotal、order_items.quantity）不受本提示影响，
  请勿因本提示改写 item 级聚合。

请基于上述提示与题目原始需求，重新生成唯一一条只读 SQLite SQL。"""


def fanout_hint_for_sql(sql: str) -> str | None:
    """仅当 Detector alarm 时返回 hint 文本；否则返回 None（不注入任何内容）。"""
    diag = analyze_fanout(sql)
    if not diag.fan_out_suspected:
        return None
    return FANOUT_RECHECK_HINT


class FanoutHintGenerator:
    """带 Fan-out 自检提示的 SQL 生成器（包装正式 SQLGenerator 的生成步骤）。"""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider or get_llm_provider()

    def generate(
        self,
        question: str,
        link_result: SchemaLinkResult,
        fs_result: FewShotResult,
        initial_sql: str,
    ) -> dict[str, Any]:
        """基于已有 initial_sql 检测 fan-out；alarm 时带 hint 重新生成。

        Returns:
            {"initial_sql", "detector_alarm", "hint_injected", "hint", "final_sql"}
        """
        hint = fanout_hint_for_sql(initial_sql)
        injected = hint is not None
        if not injected:
            return {
                "initial_sql": initial_sql,
                "detector_alarm": False,
                "hint_injected": False,
                "hint": None,
                "final_sql": initial_sql,
            }

        prompt = build_prompt(question, link_result, fs_result)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "user", "content": hint},
        ]
        raw = self._provider.generate(messages, temperature=0.0)
        data = parse_llm_output(raw)
        catalog = SchemaCatalog.from_database()
        validated = validate_output(data, link_result.tables, catalog)
        return {
            "initial_sql": initial_sql,
            "detector_alarm": True,
            "hint_injected": True,
            "hint": hint,
            "final_sql": validated["sql"],
            "explanation": validated.get("explanation", ""),
        }