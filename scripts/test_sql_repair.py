"""真实 Mimo SQL Repair 验证脚本（不进入默认 pytest）。

用法（在项目根目录）：
    python scripts/test_sql_repair.py

链路：真实 SQLite 第一次执行失败 -> 真实 Mimo 单次 Repair -> 二次 Safety/Schema
-> 第二次执行（最多一次）。输出修复前后证据与计数，不输出 API Key。

Demo A：错误表名 user -> users
Demo B：错误字段 user_name -> username
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core import config  # noqa: E402
from app.sqlrepair.repairer import SQLExecuteWithRepairOrchestrator  # noqa: E402

CASES = [
    {
        "question": "哪个地区的用户最多？",
        "sql": "SELECT region, COUNT(*) AS user_count FROM user GROUP BY region ORDER BY user_count DESC",
        "tables": ["users"],
        "columns": ["users.region", "users.username"],
    },
    {
        "question": "查询所有用户名",
        "sql": "SELECT user_name FROM users",
        "tables": ["users"],
        "columns": ["users.username", "users.region"],
    },
]


def main() -> int:
    print("=" * 70)
    print("Mimo 真实 SQL Repair 验证（有限单次修复，不执行无限循环）")
    print(f"LLM_PROVIDER : {config.LLM_PROVIDER}")
    print(f"MIMO_BASE_URL : {config.MIMO_BASE_URL or '(未设置)'}")
    print(f"MIMO_MODEL    : {config.MIMO_MODEL or '(未设置)'}")
    print(f"MIMO_API_KEY  : {'已设置(不显示内容)' if config.MIMO_API_KEY else '(未设置)'}")
    print("=" * 70)

    if not config.MIMO_API_KEY:
        print("Mimo API key is not configured")
        return 1

    orchestrator = SQLExecuteWithRepairOrchestrator()
    all_ok = True
    for case in CASES:
        print("-" * 70)
        print(f"Question: {case['question']}")
        print(f"Original SQL: {case['sql']}")
        outcome = orchestrator.run(
            question=case["question"],
            sql=case["sql"],
            tables=case["tables"],
            columns=case["columns"],
        )
        print(f"Original Error: {outcome.original_error or '(无)'}")
        print(f"Repaired SQL: {outcome.repaired_sql or '(未修复)'}")
        print(f"Repair Reason: {outcome.repair_reason or '(无)'}")
        print(f"Repair Error: {outcome.repair_error or '(无)'}")
        print(f"Execute Count: {outcome.execute_count}")
        print(f"Repair Count: {outcome.repair_count}")
        if outcome.result is not None:
            print(f"Final Execute Result: {len(outcome.result.rows)} 行 "
                  f"(columns={outcome.result.columns})")
        else:
            print("Final Execute Result: 失败（见上方错误）")
            all_ok = False

    print("=" * 70)
    print(f"SQL Repair（真实 Mimo）：{'成功' if all_ok else '存在失败'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())