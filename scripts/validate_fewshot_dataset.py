"""Few-shot 数据集只读校验脚本（不进入默认 pytest）。

用法（在项目根目录）：
    python scripts/validate_fewshot_dataset.py

检查（全部基于当前真实 db/ecommerce.db）：
1. 数据集可加载、example_id 唯一、缺字段报错；
2. 表 / 字段存在于真实 Schema；
3. SQL 必须以 SELECT/WITH 开头（只读）；
4. SQL 可被 SQLite 解析；
5. SQL 在真实数据库上通过只读连接执行成功（禁止修改数据库）。

退出码：全部通过 0；任一失败 1。
"""

import sys
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db.sqlite import get_connection  # noqa: E402
from app.fewshot.dataset import FewShotDatasetError, get_dataset  # noqa: E402
from app.schema.metadata import SchemaCatalog  # noqa: E402

READONLY_PREFIXES = ("select", "with")


def _is_readonly_sql(sql: str) -> bool:
    return sql.strip().lower().startswith(READONLY_PREFIXES)


def main() -> int:
    print("=" * 70)
    print("Few-shot 数据集只读校验")
    print("=" * 70)

    try:
        dataset = get_dataset()
    except FewShotDatasetError as exc:
        print(f"[数据集] 加载失败：{exc}")
        return 1
    print(f"[数据集] 示例数量：{len(dataset)}，示例 id 唯一 ✓")

    catalog = SchemaCatalog.from_database()
    failures: list[str] = []

    for example in dataset:
        problems: list[str] = []

        for table in example.tables:
            if not catalog.has_table(table):
                problems.append(f"表不存在 {table}")
        for full in example.columns:
            table, column = full.split(".", 1)
            if not catalog.has_table(table) or not catalog.has_column(table, column):
                problems.append(f"字段不存在 {full}")
        if not _is_readonly_sql(example.sql):
            problems.append("SQL 必须以 SELECT/WITH 开头（只读）")

        if problems:
            failures.append(f"{example.id}: " + "; ".join(problems))
            print(f"[{example.id}] 校验失败：{'；'.join(problems)}")
        else:
            # 通过真实只读连接执行 SQL（只读层会拒绝任何写语句）
            try:
                with closing(get_connection()) as conn:
                    rows = conn.execute(example.sql).fetchall()
                print(f"[{example.id}] SQL 解析并执行成功（返回 {len(rows)} 行）✓")
            except Exception as exc:
                failures.append(f"{example.id}: SQL 执行失败 -> {exc}")
                print(f"[{example.id}] SQL 执行失败：{exc}")

    print("=" * 70)
    if failures:
        print(f"校验失败：{len(failures)} 个问题，请修复 data/fewshot/ecommerce_examples.json")
        return 1
    print("校验通过：所有示例的表/字段真实存在，SQL 均为只读且可执行 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())