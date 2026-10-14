"""Database Profile 适配层（Phase 13 跨数据库迁移验证）。

目标架构：

    Agent Core
        ↓
    Database Profile（schema / business_rules / fewshot 三层）
        ↓
    DatabaseAdapter（连接 + Schema 目录 + Few-shot + 组件装配）
        ↓
    Target Database

Agent Core（app/agent/*）不感知任何具体业务数据库；
本包负责把「某个公司的数据库 + 业务口径 + Few-shot」装配为
run_agent(components=...) 可直接注入的 AgentComponents。
"""

from app.dbprofile.adapter import DatabaseAdapter, components_for_profile
from app.dbprofile.models import (
    BusinessRulesProfile,
    DatabaseProfile,
    FewShotProfile,
    SchemaProfile,
)
from app.dbprofile.profiles import (
    DEFAULT_PROFILE_ID,
    PROFILE_IDS,
    resolve_profile,
)

__all__ = [
    "BusinessRulesProfile",
    "DatabaseAdapter",
    "DatabaseProfile",
    "FewShotProfile",
    "SchemaProfile",
    "components_for_profile",
    "resolve_profile",
    "PROFILE_IDS",
    "DEFAULT_PROFILE_ID",
]
