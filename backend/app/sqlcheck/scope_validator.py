"""SQL Scope Validator —— 未定义 alias / column qualifier 静态校验。

背景（Task 37 / E-0099）：
LLM 生成的 SQL 可以通过 sqlglot 语法解析、也能通过现有 Safety 校验（单条只读
SELECT/WITH），却在执行阶段报 `no such column: r.region`。典型形态：

    WITH region_sales AS (...) SELECT r.region, ...
    FROM region_sales rs JOIN ...        -- 定义的是 rs，却引用了 r

SQLite 把 `r` 解析为**列名**而非限定符，于是等到真正执行才失败。更糟的是
Repair 拿到的是模糊的 "no such column"，无法可靠定位，往往改错地方
（冻结基线实测：Repair 输出 `rs.region` 又被 Schema 校验拒绝）。

本模块把这一类「明确可静态检查」的引用错误提前到执行之前发现。

设计约束（Task 37 §二）：
- 只读 AST，不修改 SQL、不 rewrite、不新增 LLM 调用；
- 不依赖 SchemaCatalog / 数据库 / 任何 Agent / LLM 模块；
- 纯确定性：同一输入永远得到同一输出；
- 不误报合法 SQL —— 见下方「可见性规则」。

可见性规则（关键，决定假阳性率）：
一个带限定符的列引用 `q.col` 在某个查询块内合法，当且仅当限定符 `q` 出现在
**该查询块自身或其任意外层祖先查询块**的 FROM/JOIN 数据源中（含 CTE 名）。
这条「祖先链可见性」是必需的，因为相关子查询会合法地引用外层别名：

    SELECT ... FROM orders o
    WHERE o.total > (SELECT AVG(p2.price) FROM products p2
                     WHERE p2.category_id = o.category_id)   -- o 来自外层，合法

> 朴素地只看「本查询块 sources ∩ external_columns」（sqlglot 的 Scope 默认语义）
会在 100 题 gold SQL 上产生 3 处误报（E-0060 / E-0087 / E-0095），因为相关
子查询里对外层别名的引用全部落在 external_columns 中。加上祖先链回溯后，
gold 假阳性 0/100，而 E-0099 仍被准确捕获。

TC-51：在「限定符可见」之上，再区分「限定符存在但其列不在该关系暴露的输出列」。
sqlglot 把 CTE / 派生表引用归一成带 Select 的关系节点，因此可按其 SELECT 输出列
集合判定 `rcs.category_id` 这类列引用是否不可见（code=SCOPE_HIDDEN_CTE_COLUMN）。
基础表 schema 未知，一律保守放行（列存在性交由数据库 / Repair 的字段检查）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


@dataclass(frozen=True)
class ScopeViolation:
    """一处未定义 / 不可见的限定符列引用。

    `code` 区分两类语义（Task 51，二者不得混淆）：
    - SCOPE_UNKNOWN_RELATION   ：限定符本身不存在（原本的「未定义别名」）；
    - SCOPE_HIDDEN_CTE_COLUMN  ：限定符存在（CTE / 子查询别名），但其引用
      的列不属于该关系暴露的输出列。
    """

    qualifier: str
    column: str
    expression: str
    visible_qualifiers: tuple[str, ...]
    code: str = "SCOPE_UNKNOWN_RELATION"

    def describe(self) -> str:
        if self.code == "SCOPE_HIDDEN_CTE_COLUMN":
            return (
                f"列 {self.column} 不属于关系 {self.qualifier} 暴露的输出列"
                f"（该关系输出列={sorted(self.visible_qualifiers)}）: {self.expression}"
            )
        return f"未定义的别名 {self.qualifier}: {self.expression}"


@dataclass
class ScopeCheckResult:
    """校验结果。`ok=True` 表示未发现未定义限定符。"""

    ok: bool
    violations: list[ScopeViolation] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        return [v.describe() for v in self.violations]


def _visible_qualifiers(scope) -> set[str]:
    """收集 scope 自身 + 全部外层祖先 scope 的数据源限定符。

    祖先链回溯是相关子查询合法性的来源，不可省略。
    """
    visible: set[str] = set()
    current = scope
    while current is not None:
        visible |= set(current.sources.keys())
        current = current.parent
    return visible


# ---------------------------------------------------------------- Task 51：输出列可见性

# 复制自不依赖 schema catalog 的保守实现：`SELECT *` / 未知结构记 unknown，
# 外层据此放行，宁可漏检也不误杀（与 Task 50 join_on_scope 同判据）。
def _output_cols(sel) -> tuple[set[str], bool]:
    """(SELECT 输出列名小写集合, 是否含无法判定的星号 / 结构)。"""
    cols: set[str] = set()
    unknown = False
    for e in sel.expressions:
        if isinstance(e, exp.Star) or any(True for _ in e.find_all(exp.Star)):
            unknown = True
            continue
        if isinstance(e, exp.Alias):
            cols.add(e.alias.lower())
        elif isinstance(e, exp.Column):
            cols.add(e.name.lower())
        else:
            cols.add(e.sql(dialect="sqlite").lower())
    return cols, unknown


def _exposed_cols(src) -> set[str] | None:
    """返回一个数据源（CTE / 派生表 / 基础表）对外暴露的输出列集合。

    返回 None = 保守放行（基础表 schema 未知，或 SELECT * / union / 未知结构）。
    返回 set = 该关系确定暴露的输出列；外层引用必须落在集合内。
    """
    if isinstance(src, exp.Table):
        return None  # 基础表：schema 交由数据库与既有 _check_spelled_columns 判断
    sel = None
    if isinstance(getattr(src, "expression", None), exp.Select):
        sel = src.expression
    elif isinstance(getattr(src, "this", None), exp.Select):
        sel = src.this
    if sel is None:
        return None
    cols, unknown = _output_cols(sel)
    return None if unknown else cols


def _alias_exposed(scope) -> dict[str, set[str] | None]:
    """scope 自身 + 全部外层祖先 scope 的「别名 -> 暴露列集合」映射。

    最近定义优先：外层同名 shadow 不覆盖内层已解析的别名。
    """
    merged: dict[str, set[str] | None] = {}
    current = scope
    while current is not None:
        for alias, src in current.sources.items():
            key = (alias or "").lower()
            if key and key not in merged:
                merged[key] = _exposed_cols(src)
        current = current.parent
    return merged


def check_sql_scope(sql: str) -> ScopeCheckResult:
    """静态检查 SQL 中是否存在未定义的表别名 / 列限定符。

    只检查**带限定符**的列引用（`q.col`）；无限定符的裸列名不在本模块职责内
    （其正确性依赖单表歧义消除，由数据库与既有 Schema 校验负责）。

    Args:
        sql: 待检查的 SQL 文本。

    Returns:
        ScopeCheckResult（ok / violations）。解析失败返回 ok=True 并留待
        Safety 层报错 —— 本模块**不**重复承担语法校验职责。

    Raises:
        不抛出异常。调用方通过返回值决策，避免与既有 Safety 语义混淆。
    """
    if not sql or not sql.strip():
        return ScopeCheckResult(ok=True)

    try:
        statement = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        # 无法解析属于 Safety 的职责范围，此处不越权判定。
        return ScopeCheckResult(ok=True)

    if statement is None:
        return ScopeCheckResult(ok=True)

    violations: list[ScopeViolation] = []
    seen: set[tuple[str, str, str]] = set()

    for scope in traverse_scope(statement):
        visible = _visible_qualifiers(scope)
        for column in scope.external_columns:
            qualifier = column.table
            if not qualifier:
                continue
            if qualifier in visible:
                continue
            expression = column.sql()
            key = (qualifier, column.name, expression)
            if key in seen:
                continue
            seen.add(key)
            violations.append(
                ScopeViolation(
                    qualifier=qualifier,
                    column=column.name,
                    expression=expression,
                    visible_qualifiers=tuple(sorted(visible)),
                    code="SCOPE_UNKNOWN_RELATION",
                )
            )

        # Task 51：CTE / 派生表 / 子查询的「输出列可见性」。
        # 限定符本身存在，但被引用的列不属于该关系暴露的输出列
        #（如 rcs.category_id 而 rcs 只暴露 {region, category_name, total_sales}）。
        exposed = _alias_exposed(scope)
        for column in scope.expression.find_all(exp.Column):
            # 只检查直接属于本 scope 的列引用（跳过嵌套子查询块，由其自身 scope 处理）
            if column.find_ancestor(exp.Select) is not scope.expression:
                continue
            qualifier = (column.table or "").lower()
            if not qualifier:
                continue
            cols = exposed.get(qualifier)
            if cols is None:  # 基础表 / unknown / 未定义限定符（后者走 external_columns）
                continue
            name = (column.name or "").lower()
            if name in cols:
                continue
            expression = column.sql()
            key = (qualifier, column.name, expression)
            if key in seen:
                continue
            seen.add(key)
            violations.append(
                ScopeViolation(
                    qualifier=qualifier,
                    column=column.name,
                    expression=expression,
                    visible_qualifiers=tuple(sorted(cols)),
                    code="SCOPE_HIDDEN_CTE_COLUMN",
                )
            )

    return ScopeCheckResult(ok=not violations, violations=violations)
