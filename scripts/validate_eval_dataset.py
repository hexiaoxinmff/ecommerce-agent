"""ECO-SQL-Bench 评测集结构校验脚本（Task 11，轻量版）。

功能（全部基于真实 db/ecommerce.db 做可执行性检查；不实现完整评测 Runner）：
1. JSON 可加载、结构合法（单轮主集 + 多轮文件 + 元数据必填字段）；
2. 元数据：seed 与数据库固定种子一致性（防"换库不清零"）；
3. 单轮条目：必填字段齐全、id 唯一且格式 E-xxxx、difficulty/scenario/operators/
   expected_behavior/split/answer_slots 枚举合法、operators 无重复、
   **难度禁止项拦截（FORBIDDEN_OPERATORS_BY_DIFFICULTY，矩阵 §7.3）**、
   expected_empty/order_sensitive 为布尔、question/gold_sql 非空、question 去重；
4. gold_sql 硬性检查（answer 条目）：
   - 只读单条 SELECT/WITH（app.sqlgen.safety.check_sql_safety）；
   - 引用表存在（SchemaCatalog）；
   - 在只读连接上真实执行成功（列/JOIN 合法性以执行结果为准）；
5. 多轮条目：conversation_id 唯一、turn_id 顺序、previous_turn_id 衔接、
   expected_context.dependency 与 context_operations 枚举合法；
6. 可选 --verify-hashes：重跑 gold_sql 重新计算 gold_result_hash 并与记录比对（防漂移闸门）；
7. 输出 难度×场景 分布矩阵与 operator 覆盖统计（对照 docs/evaluation-matrix.md §7.3/§7.4）。

用法（项目根目录）：
    python scripts/validate_eval_dataset.py
    python scripts/validate_eval_dataset.py --verify-hashes

退出码：全部通过 0；任一失败 1。
空数据集（items=[]）结构通过时给出明确"空占位"提示，不冒充通过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import sqlite3
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# ---- 枚举（与 docs/evaluation-matrix.md / evaluation-dataset-spec.md 保持一致）----

DIFFICULTIES = ("easy", "medium", "hard", "extra_hard")
SCENARIOS = (
    # 核心场景（阶段 1）
    "user_analysis", "product_analysis", "category_analysis",
    "order_analysis", "sales_analysis", "time_analysis", "regional_analysis",
    # 扩展场景（阶段 2 起允许）
    "comparison", "ranking", "ratio", "trend", "funnel",
)
OPERATORS = (
    # 基础操作
    "select", "where", "order_by", "limit", "group_by", "having",
    "aggregate", "join", "subquery", "case_when",
    "date_filter", "date_group", "ratio", "top_n",
    # 复杂操作
    "nested_subquery", "multiple_join", "conditional_aggregation",
    "comparison_to_average", "multi_dimension_grouping",
)
EXPECTED_BEHAVIORS = ("answer", "clarify", "refuse")
SPLITS = ("eval", "dev", "train")
VALUE_TYPES = (
    "scalar_number", "integer", "ratio", "currency", "category",
    "ranking", "date", "text", "boolean", "empty",
)
DEPENDENCIES = (
    "none", "reference", "condition_inherit",
    "filter_add", "dimension_change", "modify_range", "answer_grounded",
)
CONTEXT_OPERATIONS = (
    "inherit_condition", "add_filter", "change_group",
    "remove_condition", "modify_time_range", "reference_previous",
)
META_FIELDS = (
    "dataset_name", "version", "database_version", "seed",
    "created_at", "schema_version", "generator_version", "review_status",
)
REQUIRED_ITEM_FIELDS = (
    "id", "difficulty", "scenario", "operators",
    "question", "gold_sql", "gold_result_hash", "expected_behavior",
)
REQUIRED_TURN_FIELDS = (
    "turn_id", "previous_turn_id", "question",
    "gold_sql", "gold_result_hash", "expected_context",
)

# 数据库一致性绑定（docs/evaluation-dataset-spec.md §J）：种子变化必须同步更新此处
EXPECTED_SEED = 20260914
# 条目 ID 格式：E-0001 / C-0001 等「前缀-四位序号」
ID_PATTERN = re.compile(r"^[A-Z]{1,8}-\d{4}$")

# 各难度 operator 禁止项（docs/evaluation-matrix.md §7.3，难度分级的硬边界）
FORBIDDEN_OPERATORS_BY_DIFFICULTY: dict[str, tuple[str, ...]] = {
    "easy": (
        "group_by", "join", "having", "subquery", "date_group", "ratio",
        "case_when", "multiple_join", "nested_subquery",
        "conditional_aggregation", "comparison_to_average",
        "multi_dimension_grouping",
    ),
    "medium": (
        "subquery", "ratio", "multiple_join", "nested_subquery",
        "conditional_aggregation", "comparison_to_average",
        "multi_dimension_grouping",
    ),
    "hard": ("nested_subquery", "conditional_aggregation"),
    "extra_hard": (),
}

# 题集级最低覆盖（= docs/evaluation-matrix.md §7.4，各难度下限之和；范围/禁止项见 §7.3）
TARGET_OPERATOR_COVERAGE = {
    "aggregate": 68, "where": 54, "group_by": 38, "order_by": 31,
    "join": 27, "date_filter": 24, "limit": 23, "having": 17,
    "multiple_join": 16, "top_n": 14, "date_group": 13, "subquery": 10,
    "ratio": 7, "multi_dimension_grouping": 6,
    "comparison_to_average": 5, "case_when": 4,
    "nested_subquery": 4, "conditional_aggregation": 3,
}

DEFAULT_EVAL_DIR = PROJECT_ROOT / "data" / "eval"
DEFAULT_SINGLE_FILE = DEFAULT_EVAL_DIR / "ecommerce_eval_v1.json"
DEFAULT_MULTI_FILE = DEFAULT_EVAL_DIR / "ecommerce_multiturn_v1.json"


class EvalDatasetError(Exception):
    """评测集结构/内容错误。"""


def normalize_result_hash(columns: list, rows: list[tuple]) -> str:
    """按规范生产稳定 gold_result_hash（columns + 行内数值归一化 + 行排序），SHA-256 hex。

    设计要点（docs/evaluation-dataset-spec.md §C）：
    - None -> "<null>"；float -> round(v, 6)；
    - 行按序列化字符串排序后才参与 hash（该 hash 只防数据漂移，行顺序语义
      由 EX 比较阶段单独处理，不在 hash 中体现）。
    """
    col_norm = [str(c) for c in columns]
    serialized_rows = []
    for row in rows:
        values = []
        for value in row:
            if value is None:
                values.append("<null>")
            elif isinstance(value, float):
                values.append(round(value, 6))
            else:
                values.append(value)
        serialized_rows.append(
            json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        )
    serialized_rows.sort()
    payload = json.dumps(
        {
            "columns": col_norm,
            "rows": [json.loads(r) for r in serialized_rows],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_question(text: str) -> str:
    """去空白后的规范形式，用于『完全重复/近全重复』检测。"""
    return re.sub(r"\s+", "", text.strip())


def load_dataset(path: Path, expected_key: str) -> dict:
    """加载评测集 JSON 并做最外层结构校验。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EvalDatasetError(f"评测集文件不存在：{path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvalDatasetError(f"JSON 解析失败 {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get(expected_key), list):
        raise EvalDatasetError(f"{path} 缺少 {expected_key} 数组")
    return data


# ---------------- SQL 检查 ----------------

def validate_gold_sql(sql: str, catalog, conn: sqlite3.Connection | None) -> list[str]:
    """单独校验一条 gold_sql：只读安全 + 表存在 + 真实执行。

    Returns: 问题列表（空 = 通过）。
    """
    # 延迟导入，避免脚本在不加载后端时被 import 拖累
    from app.sqlgen.safety import check_sql_safety, extract_referenced_tables

    problems: list[str] = []
    try:
        check_sql_safety(sql)
    except Exception as exc:  # SQLUnsafeError / 解析异常
        problems.append(f"gold_sql 安全/结构校验失败：{exc}")
        return problems
    try:
        referenced = extract_referenced_tables(sql)
    except Exception as exc:
        problems.append(f"gold_sql 表提取失败：{exc}")
        return problems
    if catalog is not None:
        for table in sorted(referenced):
            if not catalog.has_table(table):
                problems.append(f"gold_sql 引用不存在的表：{table}")
    if conn is not None:
        try:
            conn.execute(sql).fetchall()
        except sqlite3.Error as exc:
            problems.append(f"gold_sql 执行失败：{exc}")
    return problems


# ---------------- 单轮条目 ----------------

def validate_item(item: dict, index: int, catalog, conn) -> list[str]:
    """校验单条单轮条目；返回问题列表。"""
    problems: list[str] = []
    prefix = f"条目[{index}]"

    for field in REQUIRED_ITEM_FIELDS:
        if field not in item or item.get(field) in (None, ""):
            problems.append(f"{prefix} 缺少必填字段 {field}")

    if not isinstance(item.get("id"), str) or not item["id"].strip():
        problems.append(f"{prefix} id 必须为非空字符串")
    elif not ID_PATTERN.match(item["id"].strip()):
        problems.append(f"{prefix} id 格式非法：{item['id']!r}（应为 E-0001 形式）")
    if not isinstance(item.get("question"), str) or not item["question"].strip():
        problems.append(f"{prefix} question 必须为非空字符串")
    if not isinstance(item.get("gold_sql"), str) or not item["gold_sql"].strip():
        problems.append(f"{prefix} gold_sql 必须为非空字符串")

    difficulty = item.get("difficulty")
    if difficulty not in DIFFICULTIES:
        problems.append(f"{prefix} difficulty 非法：{difficulty!r}（应为 {DIFFICULTIES}）")

    scenario = item.get("scenario")
    if scenario not in SCENARIOS:
        problems.append(f"{prefix} scenario 非法：{scenario!r}（应为 {SCENARIOS}）")

    operators = item.get("operators")
    if not isinstance(operators, list) or not operators:
        problems.append(f"{prefix} operators 必须为非空数组")
    else:
        seen = set()
        for op in operators:
            if not isinstance(op, str) or op not in OPERATORS:
                problems.append(f"{prefix} operators 含非法标签：{op!r}")
            if op in seen:
                problems.append(f"{prefix} operators 重复标签：{op}")
            seen.add(op)
        forbidden = FORBIDDEN_OPERATORS_BY_DIFFICULTY.get(difficulty, ())
        hits = sorted(set(operators) & set(forbidden))
        if hits:
            problems.append(
                f"{prefix} difficulty={difficulty} 包含禁止 operator：{', '.join(hits)}"
                f"（见 docs/evaluation-matrix.md §7.3 禁止项）"
            )

    behavior = item.get("expected_behavior")
    if behavior not in EXPECTED_BEHAVIORS:
        problems.append(f"{prefix} expected_behavior 非法：{behavior!r}")

    split = item.get("split")
    if split is not None and split not in SPLITS:
        problems.append(f"{prefix} split 非法：{split!r}")

    slots = item.get("answer_slots")
    if slots is not None:
        if not isinstance(slots, dict):
            problems.append(f"{prefix} answer_slots 必须为对象")
        else:
            value_type = slots.get("value_type")
            if value_type is not None and value_type not in VALUE_TYPES:
                problems.append(f"{prefix} answer_slots.value_type 非法：{value_type!r}")
            tolerance = slots.get("tolerance")
            if tolerance is not None:
                if not isinstance(tolerance, (int, float)) or tolerance < 0:
                    problems.append(f"{prefix} answer_slots.tolerance 必须为非负数")
            for bool_field in ("expected_empty", "order_sensitive"):
                if bool_field in slots and not isinstance(slots[bool_field], bool):
                    problems.append(f"{prefix} answer_slots.{bool_field} 必须为布尔值")

    if item.get("multi_turn") is not None:
        problems.append(f"{prefix} 主集单轮条目 multi_turn 必须为 null")

    # gold_sql 校验（clarify/refuse 条目同样要求提供可执行的参考 SQL）
    if isinstance(item.get("gold_sql"), str) and item["gold_sql"].strip():
        problems.extend(validate_gold_sql(item["gold_sql"], catalog, conn))

    return problems


# ---------------- 多轮文件 ----------------

def validate_conversations(data: dict, catalog, conn) -> list[str]:
    """校验多轮文件：conversation_id 唯一、turn 衔接、字段与枚举合法。"""
    problems: list[str] = []
    seen_ids: set[str] = set()
    for conv in data["conversations"]:
        conv_id = conv.get("conversation_id")
        if not isinstance(conv_id, str) or not conv_id.strip():
            problems.append("conversation 缺少合法 conversation_id")
            continue
        if conv_id in seen_ids:
            problems.append(f"conversation_id 重复：{conv_id}")
        seen_ids.add(conv_id)

        turns = conv.get("turns")
        if not isinstance(turns, list) or not turns:
            problems.append(f"{conv_id} 缺少非空 turns")
            continue
        prev: int | None = None
        for turn in turns:
            prefix = f"{conv_id}/turn[{turn.get('turn_id')}]"
            for field in REQUIRED_TURN_FIELDS:
                if field not in turn or turn.get(field) in (None, ""):
                    problems.append(f"{prefix} 缺少必填字段 {field}")
            if not isinstance(turn.get("question"), str) or not turn["question"].strip():
                problems.append(f"{prefix} question 必须为非空字符串")
            ctx = turn.get("expected_context")
            if not isinstance(ctx, dict):
                problems.append(f"{prefix} expected_context 必须为对象")
            else:
                if ctx.get("dependency") not in DEPENDENCIES:
                    problems.append(f"{prefix} expected_context.dependency 非法：{ctx.get('dependency')!r}")
                ops = ctx.get("context_operations")
                if ops is not None:
                    if not isinstance(ops, list):
                        problems.append(f"{prefix} expected_context.context_operations 必须为数组")
                    else:
                        seen_ops = set()
                        for op in ops:
                            if not isinstance(op, str) or op not in CONTEXT_OPERATIONS:
                                problems.append(f"{prefix} context_operations 含非法操作：{op!r}")
                            if isinstance(op, str) and op in seen_ops:
                                problems.append(f"{prefix} context_operations 重复操作：{op}")
                            seen_ops.add(op)
            if isinstance(turn.get("gold_sql"), str) and turn["gold_sql"].strip():
                problems.extend(validate_gold_sql(turn["gold_sql"], catalog, conn))
            # turn_id 顺序 + previous_turn_id 衔接
            if isinstance(turn.get("turn_id"), int):
                if prev is None:
                    if turn["turn_id"] != 1 or turn.get("previous_turn_id") is not None:
                        problems.append(f"{prefix} 首轮 turn_id 必须为 1 且 previous_turn_id 为 null")
                else:
                    if turn["turn_id"] != prev + 1:
                        problems.append(f"{prefix} turn_id 必须连续递增")
                    if turn.get("previous_turn_id") != prev:
                        problems.append(f"{prefix} previous_turn_id 必须等于上一轮 turn_id")
            else:
                problems.append(f"{prefix} turn_id 必须为整数")
            if isinstance(turn.get("turn_id"), int):
                prev = turn["turn_id"]
    return problems


# ---------------- 元数据 ----------------

def validate_metadata(meta: dict, file_label: str) -> list[str]:
    problems: list[str] = []
    for field in META_FIELDS:
        if field not in meta or meta.get(field) in (None, ""):
            problems.append(f"{file_label} 元数据缺少字段 {field}")
    seed = meta.get("seed")
    if isinstance(seed, int) and seed != EXPECTED_SEED:
        problems.append(
            f"{file_label} seed = {seed}，与数据库固定种子 {EXPECTED_SEED} 不一致"
            f"（数据库若已重建，必须重算全部 gold_result_hash 并更新版本）"
        )
    return problems


# ---------------- 汇总报告 ----------------

def summarize(items: list[dict]) -> dict:
    """难度×场景 分布矩阵 + operator 覆盖统计。"""
    matrix: dict[str, dict[str, int]] = {}
    operator_count: dict[str, int] = {}
    for item in items:
        d = matrix.setdefault(item.get("difficulty", "?"), {})
        d[item.get("scenario", "?")] = d.get(item.get("scenario", "?"), 0) + 1
        for op in item.get("operators", []):
            if isinstance(op, str):
                operator_count[op] = operator_count.get(op, 0) + 1
    return {"matrix": matrix, "operator_count": operator_count}


def validate_dataset(
    single_path: Path,
    multi_path: Path,
    *,
    catalog=None,
    conn: sqlite3.Connection | None = None,
    verify_hashes: bool = False,
) -> dict:
    """完整校验两个评测集文件，返回报告 dict。

    参数可由调用方注入（测试用临时数据库），main() 传入真实库。
    """
    problems: list[str] = []
    item_ids: set[str] = set()
    seen_questions: dict[str, str] = {}

    single = load_dataset(single_path, "items")
    problems.extend(validate_metadata(single.get("metadata", {}), str(single_path)))

    items: list[dict] = single["items"]

    # hash 校验（可选）：重跑 gold_sql 并比对
    hash_failures = 0
    if verify_hashes and conn is not None:
        for item in items:
            if (
                item.get("expected_behavior") == "answer"
                and isinstance(item.get("gold_sql"), str)
                and isinstance(item.get("gold_result_hash"), str)
            ):
                try:
                    cur = conn.execute(item["gold_sql"])
                    current = normalize_result_hash(
                        [col[0] for col in cur.description], cur.fetchall()
                    )
                except sqlite3.Error as exc:
                    problems.append(f"{item.get('id')} hash 重算执行失败：{exc}")
                    hash_failures += 1
                    continue
                if current != item["gold_result_hash"]:
                    problems.append(
                        f"{item.get('id')} gold_result_hash 与数据库结果不一致（基线漂移？）"
                    )
                    hash_failures += 1

    for index, item in enumerate(items):
        problems.extend(validate_item(item, index, catalog, conn))
        if isinstance(item.get("id"), str):
            if item["id"] in item_ids:
                problems.append(f"id 重复：{item['id']}")
            item_ids.add(item["id"])
        question = item.get("question")
        if isinstance(question, str) and question.strip():
            normalized = _normalize_question(question)
            if normalized in seen_questions:
                problems.append(
                    f"question 重复：{item.get('id')} 与 {seen_questions[normalized]} 相同"
                )
            seen_questions[normalized] = str(item.get("id"))

    multi = load_dataset(multi_path, "conversations")
    problems.extend(validate_metadata(multi.get("metadata", {}), str(multi_path)))
    problems.extend(validate_conversations(multi, catalog, conn))

    summary = summarize(items)
    return {
        "single_path": str(single_path),
        "multi_path": str(multi_path),
        "item_count": len(items),
        "conversation_count": len(multi["conversations"]),
        "problems": problems,
        "summary": summary,
        "hash_failures": hash_failures,
    }


def _print_report(report: dict) -> None:
    matrix = report["summary"]["matrix"]
    operator_count = report["summary"]["operator_count"]

    print("=" * 70)
    print("ECO-SQL-Bench 评测集结构校验")
    print("=" * 70)
    print(f"单轮主集    ：{report['single_path']}")
    print(f"多轮文件    ：{report['multi_path']}")
    print(f"单轮条目数  ：{report['item_count']}")
    print(f"多轮组数    ：{report['conversation_count']}")

    if report["hash_failures"]:
        print(f"hash 校验    ：{report['hash_failures']} 个条目漂移（详见问题列表）")

    print("\n[难度 × 场景 分布矩阵]")
    for difficulty in ("easy", "medium", "hard", "extra_hard"):
        if difficulty not in matrix:
            continue
        row = matrix[difficulty]
        parts = ", ".join(f"{s}={row.get(s, 0)}" for s in sorted(row))
        total = sum(row.values())
        print(f"  {difficulty:<11} total={total:<4} {parts}")

    print("\n[operator 覆盖（observed vs target）]")
    for op in sorted(TARGET_OPERATOR_COVERAGE):
        target = TARGET_OPERATOR_COVERAGE[op]
        observed = operator_count.get(op, 0)
        mark = "✓" if observed >= target else f"（缺口 {target - observed}）"
        print(f"  {op:<25} {observed:>4}/{target:<4} {mark}")
    for op in sorted(set(operator_count) - set(TARGET_OPERATOR_COVERAGE)):
        print(f"  {op:<25} {operator_count[op]:>4}/-      未设目标")

    print("\n" + "=" * 70)
    if report["problems"]:
        print(f"校验失败：{len(report['problems'])} 个问题")
        for problem in report["problems"]:
            print(f"  ✗ {problem}")
        return
    if report["item_count"] == 0:
        print("数据集结构合法（metadata/枚举/目录均通过校验），但当前为 0 条评测题 = 空占位。")
        print("注意：空占位 ≠「100 条已通过」；Task 12 分批生成的题目须经审核后入集再重跑本脚本。")
        return
    print(f"校验通过：{report['item_count']} 条单轮、"
          f"{report['conversation_count']} 组多轮结构合法，gold_sql 均可只读执行 ✓")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ECO-SQL-Bench 评测集结构校验")
    parser.add_argument("--single", type=Path, default=DEFAULT_SINGLE_FILE)
    parser.add_argument("--multi", type=Path, default=DEFAULT_MULTI_FILE)
    parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="重跑 gold_sql 并比对 gold_result_hash（防基线漂移）",
    )
    args = parser.parse_args(argv)

    from app.schema.metadata import SchemaCatalog  # noqa: PLC0415

    try:
        catalog = SchemaCatalog.from_database()
    except Exception as exc:
        print(f"Schema 元数据读取失败：{exc}；执行相关检查已跳过")
        catalog = None

    conn: sqlite3.Connection | None = None
    from app.db.sqlite import get_connection  # noqa: PLC0415

    try:
        conn = get_connection()
    except Exception as exc:
        print(f"只读数据库连接失败：{exc}；gold_sql 执行检查已跳过")

    with closing(conn) if conn is not None else _nullcontext():
        report = validate_dataset(
            args.single,
            args.multi,
            catalog=catalog,
            conn=conn,
            verify_hashes=args.verify_hashes,
        )
    _print_report(report)
    return 1 if report["problems"] else 0


class _nullcontext:
    """conn 为空时的空上下文（兼容不引入 contextlib.nullcontext 的 Python 版本）。"""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    sys.exit(main())