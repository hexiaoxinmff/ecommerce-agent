"""Data As-Of / 时间锚定契约（Phase 15 · P0-1）。

问题（Phase 14 实证，RBQ-P20 时间题 3/3 静默错误）：
- 业务库是**静态快照**（A 库数据止于 2026-09-12），而 Agent 的 Prompt 规则与
  Few-shot 示例教模型用 ``date('now')`` / ``strftime('now')`` 理解相对时间 ——
  这些函数取**机器系统时钟**。真实时钟越过数据截止日后，"本月/最近 N 天/上月"
  全部静默出错（本月返回空、上月只剩部分月、近 30 天窗口缩水）。

设计（不是把 '2026-09-12' 硬编码散落进 Prompt）：

    Database/Profile（time_anchor 表+列，随 Profile 配置）
        ↓ compute_time_contract()（真实只读查询 MIN/MAX）
    DataTimeContract（data_min_date / data_as_of，进程内缓存）
        ↓ to_prompt_block()（渲染为生成/修复 Prompt 的动态附录）
    SQL Generation / Repair（时间理解锚定业务数据，而非系统时钟）

换数据库时只需更新 Profile 的 time_anchor 指向（表+列），契约文本由
真实查询动态生成 —— 不存在散落的日期常量。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.core import config


@dataclass(frozen=True)
class TimeAnchor:
    """数据时间锚点来源（Profile 配置）：从哪张表的哪个日期列取 MIN/MAX。"""

    table: str
    column: str


@dataclass(frozen=True)
class DataTimeContract:
    """一次真实查询得到的数据时效契约（库为只读快照，可安全缓存）。"""

    data_min_date: str  # 业务数据最早日期，如 2024-01-01
    data_as_of: str  # 业务数据截止日（"业务上的今天"），如 2026-09-12
    source_table: str
    source_column: str

    def to_prompt_block(self) -> str:
        as_of = self.data_as_of
        year = as_of[:4]
        this_month = as_of[:7]
        prev_month = _prev_month(this_month)
        return (
            "【数据时效契约】（最高优先级，覆盖任何其他时间写法）\n"
            f"- 本库为业务数据快照：数据日期范围 {self.data_min_date} ~ {as_of}；"
            f"{as_of} 之后没有任何数据；\n"
            "- 所有相对时间一律以业务数据截止日 " + as_of + " 作为「今天」计算；"
            "禁止使用 date('now')、strftime(.., 'now')、CURRENT_DATE 等**系统时钟**函数"
            "（系统日期与业务数据时间无关）；即使 Few-shot 示例中出现 date('now') 写法，"
            "也必须按本契约替换为数据锚点日期；\n"
            f"- 据此换算：本月 = {this_month}（截至 {as_of} 的部分月，属正常口径，不要换月）；"
            f"上月 = {prev_month}；今年 = {year}；"
            f"最近 N 天 = 从锚点 {as_of} 往回推 N-1 天到 {as_of}（含两端）；"
            "最近 N 周/月同理从锚点往回推；\n"
            "- 时间窗口必须真实落在日期过滤条件上；禁止因「now 之后无数据」返回空结果。\n"
        )


def _prev_month(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def compute_time_contract(db_path: Path, anchor: TimeAnchor) -> DataTimeContract:
    """对目标库执行一次只读 MIN/MAX 查询，得到数据时效契约。

    Raises:
        sqlite3.Error / FileNotFoundError：库不可读（调用方决定降级策略）。
    """
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        row = conn.execute(
            f"SELECT MIN({anchor.column}), MAX({anchor.column}) FROM {anchor.table}"
        ).fetchone()
    finally:
        conn.close()
    min_date, as_of = ("" if v is None else str(v) for v in row)
    if not as_of:
        raise ValueError(f"时间锚点表为空：{anchor.table}.{anchor.column}（{db_path}）")
    return DataTimeContract(
        data_min_date=min_date,
        data_as_of=as_of,
        source_table=anchor.table,
        source_column=anchor.column,
    )


# ---------------------------------------------------------------------------
# 进程级缓存（业务库为只读快照；同一库的契约在一次进程生命周期内不变）
# ---------------------------------------------------------------------------

_CONTRACT_CACHE: dict[tuple[str, str, str], DataTimeContract] = {}


def cached_time_contract(db_path: Path, anchor: TimeAnchor) -> DataTimeContract:
    key = (str(Path(db_path).resolve()), anchor.table, anchor.column)
    if key not in _CONTRACT_CACHE:
        _CONTRACT_CACHE[key] = compute_time_contract(db_path, anchor)
    return _CONTRACT_CACHE[key]


def clear_time_contract_cache() -> None:
    """测试或数据快照更换后清空缓存。"""
    _CONTRACT_CACHE.clear()


def default_time_contract() -> DataTimeContract | None:
    """默认业务库（config.DB_PATH）的数据时效契约；不可用时返回 None（降级）。"""
    from app.dbprofile.profiles import resolve_profile

    profile = resolve_profile()
    if profile.time_anchor is None:
        return None
    try:
        return cached_time_contract(profile.db_path, profile.time_anchor)
    except (sqlite3.Error, ValueError, FileNotFoundError):
        return None


def compose_appendix(kpi_rules: str, contract: DataTimeContract | None) -> str:
    """把 KPI 口径与时间契约拼成 Prompt 附录（两部分都可缺省）。"""
    blocks = [
        b for b in (kpi_rules.strip(), contract.to_prompt_block() if contract else "") if b
    ]
    return "\n\n".join(blocks)


def default_kpi_rules() -> str:
    """默认 Profile 的 KPI 口径定义文本（Schema Linking / 生成 / 修复共享）。"""
    from app.dbprofile.profiles import resolve_profile

    return resolve_profile().business_rules.kpi_rules


def default_prompt_appendix() -> str:
    """默认组件（无 adapter 注入路径）使用的 Prompt 附录。

    KPI 口径来自默认 Profile；时间契约来自默认库的真实查询。
    库不可用时降级为仅 KPI 口径（时间契约缺省不阻断服务）。
    """
    from app.dbprofile.profiles import resolve_profile

    profile = resolve_profile()
    if Path(config.DB_PATH).resolve() != Path(profile.db_path).resolve():
        # 默认组件固定连 config.DB_PATH；仅当默认 Profile 指向同一库时才
        # 复用其锚点，避免对错误路径发查询。
        return compose_appendix(profile.business_rules.kpi_rules, None)
    return compose_appendix(profile.business_rules.kpi_rules, default_time_contract())


def format_as_of(contract: DataTimeContract | None) -> str:
    """对外展示用数据截止日（无契约时为空串，调用方自行降级）。"""
    return contract.data_as_of if contract else ""
