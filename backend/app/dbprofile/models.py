"""Database Profile 数据结构（Phase 13 跨数据库适配层）。

三层 Profile（与最终架构图对应，字段以当前代码真实依赖为准）：
- SchemaProfile       ：表白名单 + 表/字段中文业务描述（结构层）；
- BusinessRulesProfile：三处 Prompt（生成 / 链接 / 修复）的业务口径文本
  与 Schema Linking 示例（语义层）；
- FewShotProfile      ：数据集路径 + 检索关键词（示例层）。

DatabaseProfile = 数据库连接 + 上述三层，交给 DatabaseAdapter 装配。
全部为 frozen dataclass：Profile 是配置，不是可变运行时状态。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型标注；避免运行时导入环
    from app.dbprofile.time_anchor import TimeAnchor


@dataclass(frozen=True)
class SchemaProfile:
    """结构层：表白名单（与展示顺序）+ 表/字段业务描述。

    table_names 为 None 表示不做白名单过滤（内省库内全部业务表）——
    仅用于迁移实验的「最低限度适配」场景；生产 Profile 一律显式给出名单。
    """

    table_names: tuple[str, ...] | None
    table_descriptions: dict[str, str]
    column_descriptions: dict[str, dict[str, str]]


@dataclass(frozen=True)
class BusinessRulesProfile:
    """语义层：业务口径文本（数据库结构与业务口径是两个不同层次）。

    - generation_rules：SQL 生成 Prompt 的完整口径（sqlgen/prompt.py）；
    - kpi_rules：KPI 口径定义（Phase 15 · P0-2，销售额唯一口径等），
      由生成 Prompt 作为附录渲染；generation_rules 本体保持冻结基线原文；
    - schema_link_rules / repair_rules：链接与修复 Prompt 的精简口径；
    - schema_link_example：Schema Linking 的输出示例。
    """

    generation_rules: str
    schema_link_rules: str
    repair_rules: str
    schema_link_example: str
    kpi_rules: str = ""


@dataclass(frozen=True)
class FewShotProfile:
    """示例层：Few-shot 数据集与检索词表。"""

    dataset_path: Path
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DatabaseProfile:
    """一个「公司数据库」的完整适配描述。"""

    profile_id: str
    db_type: str  # 当前仅支持 sqlite；不声称任意数据库通用
    db_path: Path
    domain_name: str  # System Prompt 领域词
    schema: SchemaProfile
    business_rules: BusinessRulesProfile
    fewshot: FewShotProfile
    # 数据时效锚点（Phase 15 · P0-1）：从哪张表的哪个日期列取 MIN/MAX；
    # None = 该库不提供时间锚点（Prompt 降级为无时间契约）
    time_anchor: "TimeAnchor | None" = None

    def with_overrides(self, **overrides) -> "DatabaseProfile":
        """派生 Profile（实验专用，如「A 的业务知识 + B 的数据库」）。"""
        base = {
            "profile_id": self.profile_id,
            "db_type": self.db_type,
            "db_path": self.db_path,
            "domain_name": self.domain_name,
            "schema": self.schema,
            "business_rules": self.business_rules,
            "fewshot": self.fewshot,
            "time_anchor": self.time_anchor,
        }
        unknown = set(overrides) - set(base)
        if unknown:
            raise KeyError(f"未知的 Profile 字段: {sorted(unknown)}")
        base.update(overrides)
        return DatabaseProfile(**base)
