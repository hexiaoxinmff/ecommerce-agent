"""Few-shot 数据集加载与校验测试。

覆盖：正常加载、example_id 唯一、表/字段存在、SQL 非空、数量符合预期，
以及 JSON 非法 / 缺字段 / 重复 id / 不存在表 / 不存在字段 / 字段表不匹配 的全部报错。
"""

import json

import pytest

from app.fewshot.dataset import (
    FewShotDatasetInvalidError,
    FewShotDatasetNotFoundError,
    get_dataset,
    load_dataset,
)
from app.schema.metadata import SchemaCatalog

MINIMAL_EXAMPLE = {
    "id": "t_001",
    "question": "有多少活跃用户？",
    "scenario": "active_user_count",
    "tables": ["users"],
    "columns": ["users.status"],
    "sql": "SELECT COUNT(*) FROM users WHERE status = 'active'",
    "explanation": "统计活跃用户数",
    "tags": ["用户", "数量"],
}


def _write_dataset(tmp_path, examples) -> str:
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(examples, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ---------- 默认数据集 ----------


def test_default_dataset_loads_with_expected_scale() -> None:
    dataset = get_dataset()
    # FEWSHOT_V3（Task 14.3 干净版）：删除泄漏 ex_002 + 重写 V2 6 条 = 23 条
    assert 20 <= len(dataset) <= 30


def test_default_dataset_ids_unique() -> None:
    ids = [ex.id for ex in get_dataset()]
    assert len(ids) == len(set(ids))


def test_default_dataset_tables_exist_in_real_schema() -> None:
    catalog = SchemaCatalog.from_database()
    for ex in get_dataset():
        for table in ex.tables:
            assert catalog.has_table(table), f"{ex.id}: 表不存在 {table}"


def test_default_dataset_columns_exist_in_real_schema() -> None:
    catalog = SchemaCatalog.from_database()
    for ex in get_dataset():
        for full in ex.columns:
            table, column = full.split(".", 1)
            assert catalog.has_column(table, column), f"{ex.id}: 字段不存在 {full}"


def test_default_dataset_sql_not_empty() -> None:
    for ex in get_dataset():
        assert ex.sql.strip(), f"{ex.id}: sql 为空"


def test_default_dataset_scenarios_unique() -> None:
    scenarios = [ex.scenario for ex in get_dataset()]
    assert len(scenarios) == len(set(scenarios)), "每个 example 应使用不同 scenario"


# ---------- 非法数据报错 ----------


def test_missing_dataset_file_raises(tmp_path) -> None:
    with pytest.raises(FewShotDatasetNotFoundError):
        load_dataset(tmp_path / "missing.json")


def test_invalid_json_raises(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(FewShotDatasetInvalidError):
        load_dataset(path)


def test_top_level_not_list_raises(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(FewShotDatasetInvalidError):
        load_dataset(path)


def test_missing_field_raises(tmp_path) -> None:
    example = dict(MINIMAL_EXAMPLE)
    del example["sql"]
    with pytest.raises(FewShotDatasetInvalidError):
        load_dataset(_write_dataset(tmp_path, [example]))


def test_duplicate_id_raises(tmp_path) -> None:
    with pytest.raises(FewShotDatasetInvalidError, match="重复的 example_id"):
        load_dataset(_write_dataset(tmp_path, [MINIMAL_EXAMPLE, MINIMAL_EXAMPLE]))


def test_nonexistent_table_raises(tmp_path) -> None:
    example = dict(MINIMAL_EXAMPLE)
    example["tables"] = ["users", "payments"]
    with pytest.raises(FewShotDatasetInvalidError, match="payments"):
        load_dataset(_write_dataset(tmp_path, [example]))


def test_nonexistent_column_raises(tmp_path) -> None:
    example = dict(MINIMAL_EXAMPLE)
    example["columns"] = ["users.xxx"]
    with pytest.raises(FewShotDatasetInvalidError, match="users.xxx"):
        load_dataset(_write_dataset(tmp_path, [example]))


def test_column_table_not_in_tables_raises(tmp_path) -> None:
    example = dict(MINIMAL_EXAMPLE)
    example["columns"] = ["orders.status"]  # orders 不在 tables 中
    with pytest.raises(FewShotDatasetInvalidError, match="orders"):
        load_dataset(_write_dataset(tmp_path, [example]))


def test_empty_sql_raises(tmp_path) -> None:
    example = dict(MINIMAL_EXAMPLE)
    example["sql"] = "   "
    with pytest.raises(FewShotDatasetInvalidError, match="sql 为空"):
        load_dataset(_write_dataset(tmp_path, [example]))