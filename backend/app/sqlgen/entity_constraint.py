"""Task 38：条件性统计实体 / 驱动表约束。

## 目的

修复 E-0057 类缺陷：题目要求「按行为分档统计实体」，但生成的 SQL 用
`users LEFT JOIN orders` 把**零行为的实体**引入统计全集，导致 0 单用户
被 ELSE 分支错误计入最高档。

## 关键设计：为什么是「条件性」而非全局规则

`LEFT JOIN` 本身没有错。全库扫描发现 **E-0036 的 gold SQL 就用了 LEFT JOIN**：

- **E-0036**「哪些分类下**没有**挂载任何商品？」
  → `categories LEFT JOIN products ... HAVING COUNT(p.id) = 0`
  → **必须保留全集**，这正是题目要的答案。
- **E-0057**「按用户累计下单次数分档，各档多少用户？」
  → 统计对象是**有订单的用户**，0 单用户不属于任何一档。

两者**结构相同、语义相反**。因此约束绝不能是「禁止 LEFT JOIN」，
而必须判定「统计实体是否有行为」——即 `include_zero_activity_entities`。

本模块只在识别到「统计实体 / 聚合粒度存在全集 vs 行为集口径歧义」时
才产出约束；其余情况返回 None，Prompt 完全不变（保证单变量与可回退）。

## 触发条件（保守优先，宁可漏报不可误报）

同时满足：
1. 题目是**对实体计数的统计**（「多少(个|位|名)?」+ 实体量词）；
2. 统计对象是「实体的某个**行为/事件次数**」，而非实体自身属性；
3. 题目**未显式要求包含零行为实体**（如「所有用户/包括0单/即使没有…」）。

任一不满足 → 不触发 → 行为与冻结基线完全一致。

## 依赖约束

本模块**不**读取 Gold SQL / Gold Result / Benchmark 标签；只看 question 文本
与 Schema Linking 的 tables（可选）。纯确定性、无 LLM 调用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 实体词 -> (实体表, 该实体的「零行为」表述)
# 仅覆盖当前 Schema 支持的实体；未列出的实体不触发。
_ENTITY_TABLE = {
    "用户": "users",
    "会员": "users",
    "分类": "categories",
    "类目": "categories",
    "商品": "products",
}

# 「行为/事件」列的表 -> 说明该题统计的是实体的行为次数
_BEHAVIOR_SOURCES = {
    "订单": ("orders", "user_id"),
    "下单": ("orders", "user_id"),
    "购买": ("orders", "user_id"),
}

# 显式要求「包含零行为实体」的表述 —— 命中则**不**注入约束
_INCLUDE_ZERO_PATTERNS = (
    r"所有(用户|会员|分类|类目|商品)",
    r"全部(用户|会员|分类|类目|商品)",
    r"包括\s*0\s*(单|次|个)?",
    r"包含\s*0\s*(单|次|个)?",
    r"零(单|次|购买|下单)",
    r"即使没有",
    r"没有(下过|购买过|挂载)?(任何)?",
    r"未曾",
    r"从未",
)

# 统计实体数量的问法。
# 必须显式是「对实体本身计数」，因此要求「多少/几 + 实体量词」相邻出现。
# 反例（不得命中）：E-0082「…的比例是多少？」—— 问的是比例值，不是实体个数。
_COUNT_ENTITY_PATTERN = re.compile(
    r"(多少|几)\s*(个|位|名|档|类|种|件)?\s*"
    r"(用户|会员|分类|类目|商品|人)"
)

# 「按行为次数分档/分组」的问法
_BEHAVIOR_GRAIN_PATTERN = re.compile(
    r"(累计|总共|一共|合计)?"
    r"(下单|订单|购买|消费)"
    r"(次数|数|单数|笔数|量)?"
)


@dataclass(frozen=True)
class AnalysisEntityConstraint:
    """统计实体约束（注入 Prompt 的结构化信息）。"""

    analysis_entity: str
    driver_table: str
    aggregation_grain: str
    include_zero_activity_entities: bool
    entity_table: str
    reason: str

    def to_prompt_block(self) -> str:
        return (
            "【统计实体 / 驱动表约束】（本题已识别为「按行为分档统计实体」，请注意口径）\n"
            f"- 本题统计对象（analysis_entity）：{self.analysis_entity}\n"
            f"- 驱动表（driver_table）：{self.driver_table}"
            " —— 统计实体由该表提供，统计口径应以其为准；\n"
            f"- 聚合粒度（aggregation_grain）：{self.aggregation_grain}\n"
            f"- 是否包含零行为实体（include_zero_activity_entities）："
            f"{'true' if self.include_zero_activity_entities else 'false'}\n"
            "  本题问的是「有订单的用户」的订单数分档：**没有订单的用户不属于任何一档**，"
            "不得通过 LEFT JOIN 把零单用户引入统计全集；\n"
            "  否则零单用户会落入 ELSE 分支、被错误计入最高档。\n"
            "  正确做法：直接从行为表出发（FROM orders GROUP BY user_id），"
            "或在内层聚合后过滤掉零行为实体（HAVING COUNT(...) > 0）。\n"
            "- 注意：仅当题目明确要求「所有实体 / 包含 0 的行为实体」时，"
            "才允许用 LEFT JOIN 保留全集（例如「哪些分类下没有商品」）；"
            "本题不属于该情况。\n"
        )


def _explicitly_includes_zero(question: str) -> bool:
    for pattern in _INCLUDE_ZERO_PATTERNS:
        if re.search(pattern, question):
            return True
    return False


def detect_analysis_entity_constraint(question: str) -> AnalysisEntityConstraint | None:
    """判定题目是否需要「统计实体 / 驱动表」约束。

    Returns:
        AnalysisEntityConstraint（需注入）或 None（不需要，Prompt 保持原样）。
    """
    if not question or not question.strip():
        return None

    q = question.strip()

    # 1. 必须存在实体词
    entity_word = next((w for w in _ENTITY_TABLE if w in q), None)
    if entity_word is None:
        return None

    # 2. 必须是「统计实体数量」的问法（「多少/几 + 实体量词」相邻）
    if not _COUNT_ENTITY_PATTERN.search(q):
        return None

    # 3. 必须存在「行为次数」的统计语义
    behavior_key = next((k for k in _BEHAVIOR_SOURCES if k in q), None)
    if behavior_key is None:
        return None
    if not _BEHAVIOR_GRAIN_PATTERN.search(q):
        return None

    # 4. 若题目显式要求包含零行为实体 → 不注入
    if _explicitly_includes_zero(q):
        return None

    behavior_table, grain = _BEHAVIOR_SOURCES[behavior_key]
    entity_table = _ENTITY_TABLE[entity_word]

    return AnalysisEntityConstraint(
        analysis_entity=f"{entity_table}_with_{behavior_table}",
        driver_table=behavior_table,
        aggregation_grain=grain,
        include_zero_activity_entities=False,
        entity_table=entity_table,
        reason=(
            f"题目按「{behavior_key}」行为分档统计「{entity_word}」，"
            f"零{behavior_key}{entity_word}不属于任何档位"
        ),
    )
