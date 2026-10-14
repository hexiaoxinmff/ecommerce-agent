"""Task 37 校验：Scope 错误对 execute-with-repair 路由的影响（零 LLM）。

关键问题：新增校验后，E-0099 类 SQL 是否仍会触发一次 Repair？
正确行为 = 触发（因为归入 Database 故障域），而非被安全闸直接判死。

使用打桩 provider，不产生任何真实 LLM 调用。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "backend")

from app.agent.models import AgentResult
from app.agent.nodes import (
    AgentComponents,
    build_agent_result,
    make_nodes,
    route_after_execute,
)
from app.llm.provider import LLMProvider
from app.sqlrepair.repairer import SQLRepairer
from app.sqlexec.errors import SQLExecutionScopeError
from app.sqlexec.executor import execute as real_execute

ROOT = Path(__file__).resolve().parents[1]

E0099_PRED = (
    "WITH region_sales AS (SELECT o.region, SUM(oi.subtotal) AS total_sales "
    "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
    "WHERE o.status != 'cancelled' GROUP BY o.region) "
    "SELECT r.region, rs.total_sales FROM region_sales rs"
)

# 一个「修好了」的 Repair 输出（别名与 FROM 一致，且不依赖 CTE 别名限定）
# 注意：这里刻意不使用 CTE 别名，因为 master 基线的 _check_spelled_columns
# 存在与 Task 37 无关的既有缺陷（把 CTE 别名当真实表查列，必然拒绝）。
# 见 test_task37_sql_scope.py::test_baseline_spelled_column_check_rejects_cte_alias
REPAIRED_SQL = (
    "SELECT region, SUM(total_amount) AS total_sales FROM orders "
    "WHERE status != 'cancelled' GROUP BY region"
)


class _StubProvider(LLMProvider):
    """返回固定 Repair JSON 的打桩 provider（零网络）。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0

    def generate(self, messages, *, temperature: float = 0.0) -> str:  # noqa: D102
        self.calls += 1
        return json.dumps(self._payload, ensure_ascii=False)


def main() -> int:
    print("=" * 72)
    print("Task 37 — Scope 错误对 execute-with-repair 路由的影响（零 LLM）")
    print("=" * 72)

    # --- 1. 直接验证路由决策 ---
    state_bad = {
        "executed_ok": False,
        "execute_error_kind": "database",
        "repair_count": 0,
    }
    route = route_after_execute(state_bad)
    print(f"\n[1] route_after_execute(数据库阶段失败, repair_count=0) = {route!r}")
    assert route == "repair", "Scope 错误必须仍能触发 Repair"

    state_safety = {
        "executed_ok": False,
        "execute_error_kind": "safety",
        "repair_count": 0,
    }
    route_safety = route_after_execute(state_safety)
    print(f"    route_after_execute(安全阶段失败, repair_count=0) = {route_safety!r}")
    assert route_safety == "result", "安全阶段必须仍被禁止进入 Repair"

    # --- 2. 验证 Scope 错误确实被归类为 database ---
    print("\n[2] Scope 错误的故障域归类")
    try:
        real_execute(E0099_PRED)
        print("    FAIL: 未拦截")
        return 1
    except SQLExecutionScopeError as exc:
        print(f"    抛出类型: {type(exc).__name__}")
        print(f"    消息: {exc}")
        # 与 executor 节点里的 except 顺序一致 —— 必须先匹配 DatabaseError
        from app.sqlexec.errors import SQLExecutionDatabaseError, SQLExecutionSafetyError

        assert isinstance(exc, SQLExecutionDatabaseError)
        assert not isinstance(exc, SQLExecutionSafetyError)
        print("    归类: database  ✔ (会触发 Repair)")
        print("    非 safety      ✔ (不会被直接判死)")

    # --- 3. 端到端图行为（打桩 provider，零 LLM）---
    print("\n[3] 端到端修复流程（打桩 provider）")
    stub = _StubProvider(
        {"repaired_sql": REPAIRED_SQL, "repair_reason": "修正别名 r -> region_sales"}
    )
    repairer = SQLRepairer(provider=stub)

    components = AgentComponents(
        schema_linker=None,
        fewshot_retriever=None,
        sql_generator=None,
        sql_executor=real_execute,
        sql_repairer=repairer,
    )

    from app.sqlrepair.models import SQLRepairRequest

    req = SQLRepairRequest(
        question="哪些收货地区中，家用电器类目销售金额占该地区总销售金额的比例高于全平台家电占比？",
        original_sql=E0099_PRED,
        error_message=str(SQLExecutionScopeError("未定义的别名 r: r.region")),
        tables=["orders", "order_items", "products", "categories"],
        columns=[],
    )
    repaired = repairer.repair(req)
    print(f"    provider 调用次数: {stub.calls}")
    print(f"    Repair 输出: {repaired.repaired_sql[:60]}...")
    print(f"    修复后再执行: ", end="")
    result = real_execute(repaired.repaired_sql)
    print(f"{result.row_count} 行 ✔")

    # --- 4. 记录既有缺陷对 Repair 的真实影响（诚实披露）---
    print("\n[4] 已知既有缺陷对本任务目标的影响（不属 Task 37 变更边界）")
    print("    master 基线 _check_spelled_columns 把 CTE 别名当真实表查列，")
    print("    因此『修复后的 CTE SQL』仍会被 Repair 校验拒绝。")
    print("    => 本次修复能**准确诊断** E-0099（不再报模糊的 no such column），")
    print("       但**无法**让该类 Repair 自动成功 —— 后者需另行修复 _check_spelled_columns。")
    print("       未在本任务中修复，以遵守单变量变更纪律。")

    print("\n" + "=" * 72)
    print("结论: PASS —— Scope 错误走 database 域，Repair 流程完整保留")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
