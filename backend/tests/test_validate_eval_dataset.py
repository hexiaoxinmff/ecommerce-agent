"""scripts/validate_eval_dataset.py 的单元测试。

使用临时 SQLite 数据库 + 手工构造的 SchemaCatalog，不依赖真实业务库，
可完全离线、确定性运行。
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_eval_dataset import (  # noqa: E402
    EvalDatasetError,
    REQUIRED_ITEM_FIELDS,
    _normalize_question,
    load_dataset,
    normalize_result_hash,
    validate_dataset,
    validate_gold_sql,
    validate_item,
)
from app.schema.metadata import ColumnMeta, SchemaCatalog, TableMeta  # noqa: E402

# ---- 公共 fixture -------------------------------------------------------------


@pytest.fixture()
def catalog():
    """仅含 users（id/region）与 orders（id/status/total_amount）的手工目录。"""
    users = TableMeta(
        name="users",
        description="",
        columns=(
            ColumnMeta("id", "INTEGER", "", True, True),
            ColumnMeta("region", "TEXT", "", True, False),
        ),
    )
    orders = TableMeta(
        name="orders",
        description="",
        columns=(
            ColumnMeta("id", "INTEGER", "", True, True),
            ColumnMeta("status", "TEXT", "", True, False),
            ColumnMeta("total_amount", "REAL", "", True, False),
        ),
    )
    return SchemaCatalog({"users": users, "orders": orders})


@pytest.fixture()
def conn():
    """临时只读连接（继承自可写连接，保持简单）。"""
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, region TEXT NOT NULL);
        INSERT INTO users (id, region) VALUES (1, '广东'), (2, '北京'), (3, '广东');
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            total_amount REAL NOT NULL
        );
        INSERT INTO orders (id, status, total_amount)
        VALUES (1, 'completed', 100.0), (2, 'cancelled', 0.0);
        """
    )
    yield db
    db.close()


def make_item(**overrides) -> dict:
    base = {
        "id": "E-0001",
        "split": "eval",
        "difficulty": "easy",
        "scenario": "user_analysis",
        "operators": ["aggregate", "where"],
        "question": "哪个地区的用户最多？",
        "gold_sql": "SELECT region, COUNT(*) AS c FROM users GROUP BY region ORDER BY c DESC",
        "gold_result_hash": "0" * 64,
        "expected_behavior": "answer",
        "answer_slots": {"value_type": "category"},
        "multi_turn": None,
        "notes": "",
    }
    base.update(overrides)
    return base


def write_dataset(tmp_path: Path, single: dict, multi: dict) -> tuple[Path, Path]:
    single_path = tmp_path / "ecommerce_eval_v1.json"
    multi_path = tmp_path / "ecommerce_multiturn_v1.json"
    single_path.write_text(json.dumps(single, ensure_ascii=False), encoding="utf-8")
    multi_path.write_text(json.dumps(multi, ensure_ascii=False), encoding="utf-8")
    return single_path, multi_path


def meta_ok() -> dict:
    return {
        "dataset_name": "ECO-SQL-Bench",
        "version": "1.0",
        "database_version": "dev-2026-09-14",
        "seed": 20260914,
        "created_at": "2026-09-15",
        "schema_version": "1.0",
        "generator_version": "0",
        "review_status": "draft",
    }


# ---- normalize_result_hash ------------------------------------------------------


def test_hash_deterministic_and_row_order_independent():
    columns = ["region", "cnt"]
    rows_a = [(1, "广东"), (2, "北京")]
    rows_b = [(2, "北京"), (1, "广东")]
    assert normalize_result_hash(columns, rows_a) == normalize_result_hash(
        columns, rows_b
    )


def test_hash_floats_normalized():
    columns = ["v"]
    rows = [(0.1 + 0.2,),]
    other = [(0.3,),]
    assert normalize_result_hash(columns, rows) == normalize_result_hash(columns, other)


def test_hash_differs_on_content_change():
    columns = ["region"]
    assert normalize_result_hash(columns, [("广东",)]) != normalize_result_hash(
        columns, [("北京",)]
    )


# ---- validate_item --------------------------------------------------------------


def test_validate_item_ok(catalog, conn):
    assert validate_item(make_item(), 0, catalog, conn) == []


def test_validate_item_missing_required_field(catalog, conn):
    item = make_item()
    del item["scenario"]
    problems = validate_item(item, 0, catalog, conn)
    assert any("缺少必填字段 scenario" in p for p in problems)


@pytest.mark.parametrize(
    "field,value",
    [
        ("difficulty", "very_easy"),
        ("scenario", "not_a_scenario"),
        ("expected_behavior", "guess"),
        ("split", "prod"),
    ],
)
def test_validate_item_invalid_enum(catalog, conn, field, value):
    item = make_item(**{field: value})
    problems = validate_item(item, 0, catalog, conn)
    assert any(f"{field} 非法" in p for p in problems)


def test_validate_item_operators_invalid_and_duplicate(catalog, conn):
    item = make_item()
    item["operators"] = ["group_by", "group_by", "not_a_tag"]
    problems = validate_item(item, 0, catalog, conn)
    assert any("非法标签" in p for p in problems)
    assert any("重复标签" in p for p in problems)


def test_validate_item_empty_operators(catalog, conn):
    item = make_item(operators=[])
    problems = validate_item(item, 0, catalog, conn)
    assert any("非空数组" in p for p in problems)


@pytest.mark.parametrize(
    "difficulty,op",
    [
        ("easy", "join"),
        ("easy", "group_by"),
        ("medium", "subquery"),
        ("medium", "ratio"),
        ("hard", "nested_subquery"),
    ],
)
def test_validate_item_forbidden_operator(catalog, conn, difficulty, op):
    """矩阵 §7.3 禁止项：该难度不得出现的 operator 必须被拦截。"""
    item = make_item(difficulty=difficulty, operators=["aggregate", op])
    problems = validate_item(item, 0, catalog, conn)
    assert any("禁止 operator" in p and op in p for p in problems)


@pytest.mark.parametrize(
    "difficulty,op",
    [
        ("easy", "top_n"),
        ("medium", "having"),
        ("hard", "subquery"),
        ("extra_hard", "nested_subquery"),
    ],
)
def test_validate_item_allowed_operator(catalog, conn, difficulty, op):
    """非禁止项不应触发禁止项错误。"""
    item = make_item(difficulty=difficulty, operators=["aggregate", op])
    problems = validate_item(item, 0, catalog, conn)
    assert not any("禁止 operator" in p for p in problems)


def test_validate_item_answer_slots_invalid(catalog, conn):
    item = make_item(answer_slots={"value_type": "weird", "tolerance": -1})
    problems = validate_item(item, 0, catalog, conn)
    assert any("value_type 非法" in p for p in problems)
    assert any("tolerance 必须为非负数" in p for p in problems)


def test_validate_item_multi_turn_must_be_null(catalog, conn):
    item = make_item()
    item["multi_turn"] = {"x": 1}
    problems = validate_item(item, 0, catalog, conn)
    assert any("multi_turn 必须为 null" in p for p in problems)


def test_validate_item_id_format(catalog, conn):
    item = make_item(id="abc")
    problems = validate_item(item, 0, catalog, conn)
    assert any("id 格式非法" in p for p in problems)


@pytest.mark.parametrize("field", ["expected_empty", "order_sensitive"])
def test_validate_item_answer_slots_bool_fields(catalog, conn, field):
    item = make_item(answer_slots={field: "yes"})
    problems = validate_item(item, 0, catalog, conn)
    assert any(f"answer_slots.{field} 必须为布尔值" in p for p in problems)


# ---- gold_sql 硬性检查 ----------------------------------------------------------


def test_validate_item_sql_write_rejected(catalog, conn):
    item = make_item(gold_sql="DELETE FROM users")
    problems = validate_item(item, 0, catalog, conn)
    assert any("安全/结构" in p for p in problems)


def test_validate_gold_sql_unknown_table(catalog, conn):
    problems = validate_gold_sql("SELECT * FROM nope", catalog, conn)
    assert any("不存在的表" in p for p in problems)


def test_validate_gold_sql_missing_column(catalog, conn):
    problems = validate_gold_sql("SELECT missing_col FROM users", catalog, conn)
    assert any("执行失败" in p for p in problems)


def test_validate_gold_sql_runs_ok(catalog, conn):
    assert validate_gold_sql(
        "SELECT region, COUNT(*) AS c FROM users GROUP BY region", catalog, conn
    ) == []


# ---- 主集 + 多轮整体校验 ---------------------------------------------------------


def test_validate_dataset_duplicate_id_and_question(tmp_path, catalog, conn):
    single = {
        "metadata": meta_ok(),
        "items": [
            make_item(),
            make_item(id="E-0001", question="另一个问题"),  # id 重复
            make_item(id="E-0002", question=" 哪个地区的用户最多？ "),  # question 重复
        ],
    }
    multi = {"metadata": meta_ok(), "conversations": []}
    single_path, multi_path = write_dataset(tmp_path, single, multi)
    report = validate_dataset(single_path, multi_path, catalog=catalog, conn=conn)
    assert any("id 重复" in p for p in report["problems"])
    assert any("question 重复" in p for p in report["problems"])


def test_validate_dataset_metadata_missing(tmp_path, catalog, conn):
    single = {"metadata": {"dataset_name": "x"}, "items": []}
    multi = {"metadata": {}, "conversations": []}
    single_path, multi_path = write_dataset(tmp_path, single, multi)
    report = validate_dataset(single_path, multi_path, catalog=catalog, conn=conn)
    assert any("元数据缺少字段" in p for p in report["problems"])


def test_validate_dataset_metadata_seed_mismatch(tmp_path, catalog, conn):
    single = {"metadata": {**meta_ok(), "seed": 1}, "items": []}
    multi = {"metadata": meta_ok(), "conversations": []}
    single_path, multi_path = write_dataset(tmp_path, single, multi)
    report = validate_dataset(single_path, multi_path, catalog=catalog, conn=conn)
    assert any("seed = 1" in p and "不一致" in p for p in report["problems"])


def test_validate_dataset_verify_hashes(tmp_path, catalog, conn):
    good_sql = "SELECT region, COUNT(*) AS c FROM users GROUP BY region"
    cur = conn.execute(good_sql)
    good_hash = normalize_result_hash(
        [col[0] for col in cur.description], cur.fetchall()
    )
    single = {
        "metadata": meta_ok(),
        "items": [
            make_item(gold_sql=good_sql, gold_result_hash=good_hash),
            make_item(
                id="E-0002",
                gold_sql="SELECT region, COUNT(*) AS c FROM users GROUP BY region",
                gold_result_hash="f" * 64,
            ),
        ],
    }
    multi = {"metadata": meta_ok(), "conversations": []}
    single_path, multi_path = write_dataset(tmp_path, single, multi)
    report = validate_dataset(
        single_path, multi_path, catalog=catalog, conn=conn, verify_hashes=True
    )
    assert any("基线漂移" in p for p in report["problems"])
    assert report["hash_failures"] == 1


def test_validate_dataset_multiturn_chaining(tmp_path, catalog, conn):
    turns = [
        {
            "turn_id": 2,
            "previous_turn_id": 1,
            "question": "按类别看看",
            "gold_sql": "SELECT status, COUNT(*) FROM orders GROUP BY status",
            "gold_result_hash": "0" * 64,
            "expected_context": {"dependency": "dimension_change"},
        },
        {
            "turn_id": 2,
            "previous_turn_id": 1,
            "question": "按地区看看",
            "gold_sql": "SELECT region, COUNT(*) FROM users GROUP BY region",
            "gold_result_hash": "0" * 64,
            "expected_context": {"dependency": "dimension_change"},
        },
    ]
    single = {"metadata": meta_ok(), "items": []}
    multi = {
        "metadata": meta_ok(),
        "conversations": [
            {"conversation_id": "C-001", "turns": turns},  # turn 衔接错误
            {"conversation_id": "C-001", "turns": []},  # conversation_id 重复
        ],
    }
    single_path, multi_path = write_dataset(tmp_path, single, multi)
    report = validate_dataset(single_path, multi_path, catalog=catalog, conn=conn)
    assert any("首轮 turn_id 必须为 1" in p for p in report["problems"])
    assert any("turn_id 必须连续递增" in p for p in report["problems"])
    assert any("conversation_id 重复" in p for p in report["problems"])


def test_validate_dataset_context_operations(tmp_path, catalog, conn):
    turns = [
        {
            "turn_id": 1,
            "previous_turn_id": None,
            "question": "近30天销售额最高的商品",
            "gold_sql": "SELECT region, COUNT(*) FROM users GROUP BY region",
            "gold_result_hash": "0" * 64,
            "expected_context": {"dependency": "none"},
        },
        {
            "turn_id": 2,
            "previous_turn_id": 1,
            "question": "只看华南地区",
            "gold_sql": "SELECT region, COUNT(*) FROM users GROUP BY region",
            "gold_result_hash": "0" * 64,
            "expected_context": {
                "dependency": "filter_add",
                "context_operations": ["add_filter", "not_an_op", "add_filter"],
            },
        },
    ]
    single = {"metadata": meta_ok(), "items": []}
    multi = {
        "metadata": meta_ok(),
        "conversations": [{"conversation_id": "C-001", "turns": turns}],
    }
    single_path, multi_path = write_dataset(tmp_path, single, multi)
    report = validate_dataset(single_path, multi_path, catalog=catalog, conn=conn)
    assert any("含非法操作" in p for p in report["problems"])
    assert any("重复操作" in p for p in report["problems"])


def test_load_dataset_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvalDatasetError):
        load_dataset(path, "items")


def test_normalize_question_ignores_whitespace():
    assert _normalize_question(" 哪个 地区 用户最多 ") == "哪个地区用户最多"


def test_required_item_fields_exported():
    assert REQUIRED_ITEM_FIELDS == (
        "id", "difficulty", "scenario", "operators",
        "question", "gold_sql", "gold_result_hash", "expected_behavior",
    )


# ---- Batch 2（Medium）draft 合同校验 -------------------------------------------
# 纯 JSON 校验，不依赖真实数据库：保证候选正式题满足难度档禁止项/枚举/场景配额约束，
# 与矩阵 §7.2 / §7.3 的一致性由生成期校验脚本负责，这里只做契约快照。


BATCH2_DRAFT = (
    PROJECT_ROOT
    / "data" / "eval" / "drafts" / "medium_batch2_candidates.json"
)


def _load_batch2_candidates() -> list[dict]:
    data = json.loads(BATCH2_DRAFT.read_text(encoding="utf-8"))
    assert isinstance(data.get("candidates"), list), "draft 缺少 candidates 数组"
    return data["candidates"]


def test_batch2_candidates_all_medium():
    """Batch 2 正式候选必须全部为 medium，且占位 hash 齐全（结构契约）。"""
    candidates = _load_batch2_candidates()
    assert candidates, "Batch 2 draft 不应为空"
    for item in candidates:
        assert item["difficulty"] == "medium", item["id"]
        assert item["expected_behavior"] == "answer", item["id"]
        assert item.get("multi_turn") is None, item["id"]
        # 置入占位 hash 后应能通过校验（结构上等价于候选稿的合法字段集合）
        item["gold_result_hash"] = "0" * 64


def test_batch2_candidates_no_medium_forbidden_operators():
    """Medium 禁止项（矩阵 §7.3）不得出现在任何正式候选的 operators 中。"""
    from scripts.validate_eval_dataset import (  # noqa: PLC0415
        FORBIDDEN_OPERATORS_BY_DIFFICULTY,
    )

    forbidden = set(FORBIDDEN_OPERATORS_BY_DIFFICULTY["medium"])
    for item in _load_batch2_candidates():
        ops = set(item["operators"])
        banned = ops & forbidden
        assert not banned, f"{item['id']} 含 Medium 禁止 operator：{sorted(banned)}"


def test_batch2_candidates_operators_members():
    """正式候选的 operators 必须全部为合法枚举，且无重复标签。"""
    from scripts.validate_eval_dataset import OPERATORS  # noqa: PLC0415

    for item in _load_batch2_candidates():
        ops = item["operators"]
        assert len(ops) == len(set(ops)), f"{item['id']} operators 重复"
        assert all(op in OPERATORS for op in ops), item["id"]


def test_batch2_candidates_id_range_and_quota():
    """正式候选 ID 连续覆盖 E-0026~E-0055，且场景配额匹配矩阵 §7.2 Medium 行。"""
    candidates = _load_batch2_candidates()
    ids = sorted(item["id"] for item in candidates if item["id"].startswith("E-"))
    assert ids == [f"E-{i:04d}" for i in range(26, 56)], ids
    expected_quota = {
        "user_analysis": 3,
        "product_analysis": 5,
        "category_analysis": 4,
        "order_analysis": 3,
        "sales_analysis": 5,
        "time_analysis": 4,
        "regional_analysis": 3,
        "ranking": 3,
    }
    counts: dict[str, int] = {}
    for item in candidates:
        if item["id"].startswith("E-"):
            counts[item["scenario"]] = counts.get(item["scenario"], 0) + 1
    assert counts == expected_quota, counts


# ---- Batch 3（Hard）draft 合同校验 -------------------------------------------
# 纯 JSON 校验，不依赖真实数据库：verify Hard 禁止项/难度/ID 范围/场景配额，
# 与矩阵 §7.2 / §7.3 的一致性由生成期校验脚本负责，这里只做契约快照。


BATCH3_DRAFT = (
    PROJECT_ROOT
    / "data" / "eval" / "drafts" / "hard_batch3_candidates.json"
)


def _load_batch3_candidates() -> list[dict]:
    data = json.loads(BATCH3_DRAFT.read_text(encoding="utf-8"))
    assert isinstance(data.get("candidates"), list), "draft 缺少 candidates 数组"
    return data["candidates"]


def test_batch3_candidates_all_hard():
    """Batch 3 正式候选必须全部为 hard，且 expected_behavior=answer。"""
    candidates = _load_batch3_candidates()
    assert candidates, "Batch 3 draft 不应为空"
    for item in candidates:
        assert item["difficulty"] == "hard", item["id"]
        assert item["expected_behavior"] == "answer", item["id"]
        assert item.get("multi_turn") is None, item["id"]


def test_batch3_candidates_no_hard_forbidden_operators():
    """Hard 禁止项（矩阵 §7.3：nested_subquery / conditional_aggregation）不得出现。"""
    from scripts.validate_eval_dataset import (  # noqa: PLC0415
        FORBIDDEN_OPERATORS_BY_DIFFICULTY,
    )

    forbidden = set(FORBIDDEN_OPERATORS_BY_DIFFICULTY["hard"])
    for item in _load_batch3_candidates():
        banned = set(item["operators"]) & forbidden
        assert not banned, f"{item['id']} 含 Hard 禁止 operator：{sorted(banned)}"


def test_batch3_hard_requires_complex_capabilities():
    """Hard 题不得是 Medium 换皮：每题必须携带至少一个复杂能力标签
    （multiple_join / subquery / ratio / comparison_to_average /
     multi_dimension_grouping / case_when）、或同时具备 date_group+having
    （时间维度聚合过滤），或属于 Hard 特有场景 comparison（跨主体对比）。"""
    complex_ops = {
        "multiple_join", "subquery", "ratio",
        "comparison_to_average", "multi_dimension_grouping", "case_when",
    }
    for item in _load_batch3_candidates():
        ops = set(item["operators"])
        is_complex = bool(ops & complex_ops)
        is_time_having = {"date_group", "having"} <= ops
        is_comparison_scenario = item.get("scenario") == "comparison"
        assert is_complex or is_time_having or is_comparison_scenario, (
            f"{item['id']} 既无复杂能力标签、也非时间+HAVING 聚合/对比场景，疑似 Medium 换皮"
        )


def test_batch3_candidates_id_range_and_quota():
    """正式候选 ID 连续覆盖 E-0056~E-0085，且场景配额匹配矩阵 §7.2 Hard 行。"""
    candidates = _load_batch3_candidates()
    ids = sorted(item["id"] for item in candidates if item["id"].startswith("E-"))
    assert ids == [f"E-{i:04d}" for i in range(56, 86)], ids
    expected_quota = {
        "user_analysis": 2,
        "product_analysis": 3,
        "category_analysis": 3,
        "order_analysis": 2,
        "sales_analysis": 5,
        "time_analysis": 5,
        "regional_analysis": 3,
        "ranking": 2,
        "ratio": 3,
        "comparison": 2,
    }
    counts: dict[str, int] = {}
    for item in candidates:
        if item["id"].startswith("E-"):
            counts[item["scenario"]] = counts.get(item["scenario"], 0) + 1
    assert counts == expected_quota, counts


# ---- Batch 4（Extra Hard）draft 合同校验 ---------------------------------------
# 纯 JSON 校验，不依赖真实数据库：verify EH 禁止项（无）/ID 范围/场景配额/
# "非 Hard 换皮"复杂能力判定，与矩阵 §7.2 / §7.3 的一致性由生成期校验脚本负责。


BATCH4_DRAFT = (
    PROJECT_ROOT
    / "data" / "eval" / "drafts" / "extra_hard_batch4_candidates.json"
)


def _load_batch4_candidates() -> list[dict]:
    data = json.loads(BATCH4_DRAFT.read_text(encoding="utf-8"))
    assert isinstance(data.get("candidates"), list), "draft 缺少 candidates 数组"
    return data["candidates"]


def test_batch4_candidates_all_extra_hard():
    """Batch 4 正式候选必须全部为 extra_hard，且 expected_behavior=answer。"""
    candidates = _load_batch4_candidates()
    assert candidates, "Batch 4 draft 不应为空"
    for item in candidates:
        assert item["difficulty"] == "extra_hard", item["id"]
        assert item["expected_behavior"] == "answer", item["id"]
        assert item.get("multi_turn") is None, item["id"]


def test_batch4_candidates_id_range_and_quota():
    """正式候选 ID 连续覆盖 E-0086~E-0100，且场景配额匹配矩阵 §7.2 EH 行。"""
    candidates = _load_batch4_candidates()
    ids = sorted(item["id"] for item in candidates if item["id"].startswith("E-"))
    assert ids == [f"E-{i:04d}" for i in range(86, 101)], ids
    expected_quota = {
        "user_analysis": 1,
        "product_analysis": 2,
        "category_analysis": 1,
        "order_analysis": 1,
        "sales_analysis": 3,
        "time_analysis": 3,
        "regional_analysis": 1,
        "ranking": 1,
        "ratio": 1,
        "comparison": 1,
    }
    counts: dict[str, int] = {}
    for item in candidates:
        if item["id"].startswith("E-"):
            counts[item["scenario"]] = counts.get(item["scenario"], 0) + 1
    assert counts == expected_quota, counts


def test_batch4_extra_hard_requires_deep_capabilities():
    """EH 题不得是 Hard 换皮：每题必须至少携带一个 EH 级深能力标签
    （nested_subquery / multiple_join / conditional_aggregation /
     multi_dimension_grouping），或具备复杂时间逻辑结构
    （subquery+ratio+date_group 组合，如跨期同比/环比自联结比较）。"""
    deep_ops = {
        "nested_subquery", "multiple_join",
        "conditional_aggregation", "multi_dimension_grouping",
    }
    complex_ops = {
        "multiple_join", "subquery", "ratio",
        "comparison_to_average", "multi_dimension_grouping", "case_when",
    }
    time_series_ops = {"subquery", "ratio", "date_group"}
    for item in _load_batch4_candidates():
        ops = set(item["operators"])
        has_deep = bool(ops & deep_ops)
        has_time_series = time_series_ops <= ops
        assert has_deep or has_time_series, (
            f"{item['id']} 无 EH 级深能力标签（nested/multiple_join/条件聚合/多维）"
            f"，也非复杂时间逻辑（跨期比较），疑似 Hard 换皮"
        )
        assert ops & complex_ops, (
            f"{item['id']} 无任何复杂能力标签，结构过低"
        )