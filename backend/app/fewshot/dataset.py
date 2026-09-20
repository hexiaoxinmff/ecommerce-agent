"""Few-shot 数据集加载与校验。

要求：
- 启动后首次使用时从 JSON 读取（默认 data/fewshot/ecommerce_examples.json，
  可用 FEWSHOT_DATASET_PATH 覆盖）；
- JSON 非法、example 缺字段、重复 example_id、表/字段不存在、SQL 为空、
  字段归属表不在 tables 中 -> 一律明确报错，禁止静默跳过坏数据；
- 表名/字段名以当前真实 SQLite Schema（SchemaCatalog）复核。
"""

import json
from functools import lru_cache
from pathlib import Path

from app.core import config
from app.fewshot.models import FewShotExample
from app.schema.metadata import SchemaCatalog


class FewShotDatasetError(Exception):
    """Few-shot 数据集异常基类。"""


class FewShotDatasetNotFoundError(FewShotDatasetError):
    """数据集文件不存在。"""


class FewShotDatasetInvalidError(FewShotDatasetError):
    """数据集内容非法（JSON/缺字段/重复 id/表字段不存在等）。"""


def _validate_example(
    raw: dict, catalog: SchemaCatalog, seen_ids: set[str]
) -> FewShotExample:
    try:
        example = FewShotExample(**raw)
    except Exception as exc:  # Pydantic ValidationError 等
        raise FewShotDatasetInvalidError(f"example 缺字段或类型错误: {raw.get('id', '?')}") from exc

    if example.id in seen_ids:
        raise FewShotDatasetInvalidError(f"重复的 example_id: {example.id}")
    seen_ids.add(example.id)

    if not example.sql.strip():
        raise FewShotDatasetInvalidError(f"{example.id} 的 sql 为空")

    for table in example.tables:
        if not catalog.has_table(table):
            raise FewShotDatasetInvalidError(
                f"{example.id} 引用不存在的表: {table}"
            )

    for full_name in example.columns:
        if not isinstance(full_name, str) or "." not in full_name:
            raise FewShotDatasetInvalidError(
                f"{example.id} 字段格式必须为「表名.字段名」: {full_name}"
            )
        table, column = full_name.split(".", 1)
        if not catalog.has_table(table):
            raise FewShotDatasetInvalidError(
                f"{example.id} 引用不存在的表: {full_name}"
            )
        if not catalog.has_column(table, column):
            raise FewShotDatasetInvalidError(
                f"{example.id} 引用不存在的字段: {full_name}"
            )
        if table not in example.tables:
            raise FewShotDatasetInvalidError(
                f"{example.id} 字段 {full_name} 所属表 {table} 不在 tables 中"
            )

    return example


def load_dataset(path: Path | None = None) -> list[FewShotExample]:
    """读取并校验数据集，返回按文件顺序排列的示例列表。"""
    dataset_path = Path(path) if path is not None else Path(config.FEWSHOT_DATASET_PATH)
    if not dataset_path.is_file():
        raise FewShotDatasetNotFoundError(f"Few-shot 数据集不存在: {dataset_path}")
    try:
        raw_data = json.loads(dataset_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FewShotDatasetInvalidError("Few-shot 数据集 JSON 解析失败") from exc

    if not isinstance(raw_data, list):
        raise FewShotDatasetInvalidError("Few-shot 数据集顶层必须是数组")

    catalog = SchemaCatalog.from_database()
    seen_ids: set[str] = set()
    examples: list[FewShotExample] = []
    for item in raw_data:
        if not isinstance(item, dict):
            raise FewShotDatasetInvalidError("数据集中的每一项必须是对象")
        examples.append(_validate_example(item, catalog, seen_ids))
    return examples


@lru_cache(maxsize=1)
def get_dataset() -> list[FewShotExample]:
    """首发缓存数据集（测试可通过 monkeypatch config 路径后调用 reload_dataset）。"""
    return load_dataset()


def reload_dataset() -> list[FewShotExample]:
    """强制重新读取数据集（清空缓存）。"""
    get_dataset.cache_clear()
    return get_dataset()