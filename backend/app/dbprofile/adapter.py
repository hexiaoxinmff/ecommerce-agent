"""DatabaseAdapter：把 DatabaseProfile 装配为 Agent 可用的运行时组件。

职责（Adapter Layer，Agent Core 之外的全部数据库特化）：
- 只读连接（复用 app.db.sqlite 的 mode=ro + query_only 双重防护）；
- Schema 目录（真实内省 + Profile 描述，per-adapter 缓存）；
- Few-shot 数据集（按 Profile 路径加载；validate=False 用于迁移实验
  的「无适配裸切换」场景——允许注入引用其他库结构的示例）；
- 组件装配：components_for_profile 返回的 AgentComponents 与
  app/agent/graph.default_components() 结构完全一致，可直接传入
  run_agent(question, components=...)，Agent Core 零改动即可换库。

本模块不做任何「SQL 方言翻译」：当前两库均为 SQLite；
不支持也不声称支持任意数据库（PostgreSQL / MySQL 等属于后续工作）。
"""

import sqlite3
from contextlib import closing
from functools import partial
from typing import Callable

from app.agent.nodes import AgentComponents
from app.db.sqlite import DatabaseError, get_connection_for
from app.fewshot.dataset import load_dataset
from app.fewshot.models import FewShotExample
from app.fewshot.retriever import FewShotRetriever
from app.llm.provider import LLMProvider, get_llm_provider
from app.schema.linker import SchemaLinker
from app.schema.metadata import SchemaCatalog
from app.sqlgen.generator import SQLGenerator
from app.sqlrepair.repairer import SQLRepairer
from app.sqlexec.executor import execute
from app.sqlexec.models import SQLExecutionResult

from app.dbprofile.models import DatabaseProfile
from app.dbprofile.time_anchor import DataTimeContract, cached_time_contract, compose_appendix


class DatabaseAdapter:
    """一个 Database Profile 的运行时装配器。"""

    def __init__(self, profile: DatabaseProfile) -> None:
        self.profile = profile
        self._catalog: SchemaCatalog | None = None

    # ---------------- 连接 ----------------

    def get_connection(self) -> sqlite3.Connection:
        """获取指向 Profile 数据库的一条独立只读连接，调用方负责关闭。"""
        return get_connection_for(self.profile.db_path)

    def is_database_readable(self) -> bool:
        """轻量探活：Profile 数据库能否打开并执行 SELECT 1。"""
        try:
            conn = self.get_connection()
        except DatabaseError:
            return False
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    def database_info(self) -> dict[str, str | int]:
        """读取 Profile 库名、表数量与各业务表行数（全部来自真实查询）。"""
        table_names = self.get_cached_catalog().table_names
        with closing(self.get_connection()) as conn:
            (table_count,) = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()
            counts: dict[str, int] = {}
            for table in table_names:
                (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = count
        return {
            "database": self.profile.db_path.name,
            "tables": table_count,
            **counts,
        }

    # ---------------- Schema ----------------

    def build_catalog(self) -> SchemaCatalog:
        """从 Profile 数据库真实内省构建 Schema 目录（+ Profile 描述层）。"""
        return SchemaCatalog.from_database(
            connection_factory=self.get_connection,
            allowed_tables=self.profile.schema.table_names,  # None = 不过滤
            table_descriptions=self.profile.schema.table_descriptions,
            column_descriptions=self.profile.schema.column_descriptions,
        )

    def get_cached_catalog(self) -> SchemaCatalog:
        """返回本 adapter 的缓存目录（Profile 数据库只读，可安全缓存）。"""
        if self._catalog is None:
            self._catalog = self.build_catalog()
        return self._catalog

    def clear_cached_catalog(self) -> None:
        """清空缓存目录（测试或结构变化后调用）。"""
        self._catalog = None

    # ---------------- Few-shot ----------------

    def load_fewshot(self, *, validate: bool = True) -> list[FewShotExample]:
        """加载 Profile 的 Few-shot 数据集。

        validate=True：示例表/字段按本 Profile 的 Schema 目录复核（生产语义）；
        validate=False：跳过复核（迁移实验的「无适配裸切换」场景）。
        """
        catalog = self.get_cached_catalog() if validate else None
        return load_dataset(self.profile.fewshot.dataset_path, catalog=catalog)

    # ---------------- 数据时效契约（Phase 15 · P0-1） ----------------

    def time_contract(self) -> DataTimeContract | None:
        """本 Profile 库的数据时效契约（真实查询 MIN/MAX，进程内缓存）。

        Profile 未配置 time_anchor 或库不可读时返回 None（Prompt 降级为
        无时间契约，不阻断服务）。
        """
        if self.profile.time_anchor is None:
            return None
        try:
            return cached_time_contract(self.profile.db_path, self.profile.time_anchor)
        except (sqlite3.Error, ValueError, FileNotFoundError):
            return None

    def prompt_appendix(self) -> str:
        """生成/修复 Prompt 的运行时附录：KPI 口径定义 + 数据时效契约。

        与 business_rules 本体分离：冻结基线常量逐字节不变（Phase 13 契约），
        附录在渲染时追加。
        """
        return compose_appendix(
            self.profile.business_rules.kpi_rules, self.time_contract()
        )

    # ---------------- 执行器 ----------------

    def sql_executor(self) -> Callable[[str], SQLExecutionResult]:
        """返回绑定到 Profile 数据库的安全只读执行器。"""
        return partial(execute, connection_factory=self.get_connection)


def components_for_profile(
    profile: DatabaseProfile,
    provider: LLMProvider | None = None,
    *,
    validate_fewshot: bool = True,
) -> AgentComponents:
    """按 Profile 装配一套与 default_components() 同构的 Agent 组件。

    provider 可注入（测试用 fake Provider）；validate_fewshot=False
    对应迁移实验 B 组（A 的 Few-shot 知识 + B 的数据库，不做跨库复核）。
    """
    adapter = DatabaseAdapter(profile)
    prov = provider or get_llm_provider()
    linker = SchemaLinker(provider=prov, adapter=adapter)
    retriever = FewShotRetriever(
        dataset=adapter.load_fewshot(validate=validate_fewshot),
        keywords=profile.fewshot.keywords,
    )
    generator = SQLGenerator(
        provider=prov,
        schema_linker=linker,
        fewshot_retriever=retriever,
        adapter=adapter,
    )
    repairer = SQLRepairer(provider=prov, fewshot_retriever=retriever, adapter=adapter)
    return AgentComponents(
        schema_linker=linker,
        fewshot_retriever=retriever,
        sql_generator=generator,
        sql_executor=adapter.sql_executor(),
        sql_repairer=repairer,
    )
