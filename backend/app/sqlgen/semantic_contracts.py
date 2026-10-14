"""Task 44：SQLGEN 语义契约（条件性 / 确定性识别，无 LLM、无 DB 依赖）。

## 目的

Task 43 小样本实测确证了 5 个失败机制。其中 3 个属于「SQL 生成层的语义方向
/ 口径 / 确定性」问题，本模块为它们提供**可测试、可回归**的约束段：

| flag | 机制 | 靶题 | 触发条件 |
|---|---|---|---|
| E9  | 全局口径不得继承外层时间过滤 | E-0065 | 题面同时出现「时间过滤」与「平台级全局词」 |
| E10 | ratio 分子/分母方向必须显式确定 | E-0075 | 题面含比值/倍数/占比/增速语义 |
| E11 | Top-N / 排名必须有确定性破平键 | E-0098 | 题面是「Top-N 集合」或「最X的是哪些」 |

## 为什么是「条件性」而不是全局规则

与 Task 38 的 E8 同构：全局注入会污染与本题无关的 99 道题。本模块的每个
detector 都返回 `None`（不注入）或一个不可变契约对象（注入），因此：

- 未设置对应 flag ⇒ 恒返回 None ⇒ Prompt 与冻结基线**逐字节相同**；
- 设置 flag 但题目不命中 ⇒ 同样不注入 ⇒ 单变量可控、可回退。

## 判据的保守性（决定副作用面）

- **E9**：刻意用「合取」——必须**同时**命中时间过滤与平台级全局词
  （`全平台 / 全站 / 整个平台 / 平台整体`）。故意**不**收「全部 / 所有」，
  因为这类词常被同一句的时间窗限定（反例 E-0083「该季度全部商品销售金额」），
  把它当全局口径会让规则教模型丢掉合法的时间过滤。
- **E10**：只在题面出现比值语义时注入，且要求模型**先写出分子/分母再生成 SQL**；
  能从句式直接抽取方向时（「A 是 B 的几倍」）额外给出题面级方向提示。
- **E11**：只认「Top-N 集合」（显式 N）或「最X的是哪些」，**排除标量 Top-1**
  （如「售价最高的商品价格是多少？」），因为该场景破平键不影响返回值。
  Task 46 依据 Task 45 的真实回归把注入文本**收窄**为「只允许在 ORDER BY 追加破平键」，
  并显式禁止四类误用：写入 SELECT、写入 GROUP BY、改写 WHERE/HAVING 过滤（尤其日期）、
  改变原有聚合粒度。

## 依赖约束

本模块**不**读取 Gold SQL / Gold Result / Benchmark 标签，只看 question 文本。
纯确定性：同一输入永远得到同一输出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------- 共享词表

# 题面中的时间过滤表达（与 E-0065/E-0075/E-0083 等题面一致）
_TIME_FILTER_PATTERN = re.compile(
    r"20\d{2}\s*年|20\d{2}-\d{2}|上半年|下半年|第[一二三四1234]季度|本年度|今年|去年|全年|月度|季度"
)

# 「平台级」全局口径词 —— 刻意窄化：不含「全部 / 所有」（见模块 docstring）
_PLATFORM_SCOPE_PATTERN = re.compile(r"全平台|全站|整个平台|平台整体")

# ---------------------------------------------------------------- E9 全局口径


@dataclass(frozen=True)
class GlobalScopeContract:
    """E9：题面同时存在时间过滤与平台级全局口径时的口径约束。"""

    global_terms: tuple[str, ...]
    time_terms: tuple[str, ...]

    def to_prompt_block(self) -> str:
        return (
            "【全局口径 / 参照基准约束】（本题同时出现时间过滤与「全平台」类全局口径，请注意）\n"
            f"- 本题的时间过滤表达：{'、'.join(self.time_terms)}\n"
            f"- 本题的全局口径表达：{'、'.join(self.global_terms)}\n"
            "- 「全平台 / 全站 / 平台整体」描述的是一个**不受本题时间窗限制**的整体口径；\n"
            "  当它作为**参照基准**出现时（如「高于全平台平均实付金额」中的平均值），\n"
            "  该参照基准的聚合**不得继承**外层的年份 / 季度 / 半年过滤条件，"
            "否则阈值会被抬高、命中数会偏少；\n"
            "- 正确写法：把参照基准写成独立的标量子查询，子查询内只保留题面为该基准"
            "显式声明的过滤条件（如「非取消订单」），不要复制外层的日期条件；\n"
            "- 反例（不要这样做）：外层 `WHERE order_date >= '2026-01-01'` 时，"
            "内层 `SELECT AVG(total_amount) FROM orders WHERE order_date >= '2026-01-01'`；\n"
            "- 例外：若题面把全局口径**与同一时间窗绑定**（如「该季度全部商品销售金额」"
            "「2025 年全平台销售额」），则该基准**必须**保留该时间窗，不得去掉过滤。\n"
            "- 只有本题被识别为「全局口径」时才适用本段；其他题目不要无理由去掉时间过滤。\n"
        )


def detect_global_scope(question: str) -> GlobalScopeContract | None:
    """识别「时间过滤 ∧ 平台级全局口径」的题目。

    Returns:
        GlobalScopeContract（需注入 E9 段）或 None（不注入）。

    Notes:
        必须**同时**命中时间过滤与平台级全局词。只命中其一时不注入 ——
        单独出现全局词时（如 E-0082 无时间过滤）注入是无效噪声；
        单独出现时间过滤时注入会诱导模型丢掉合法过滤。
    """
    if not question or not question.strip():
        return None
    q = question.strip()

    time_terms = tuple(sorted({m.group(0).strip() for m in _TIME_FILTER_PATTERN.finditer(q)}))
    if not time_terms:
        return None
    if not _PLATFORM_SCOPE_PATTERN.search(q):
        return None

    global_terms = tuple(sorted({m.group(0) for m in _PLATFORM_SCOPE_PATTERN.finditer(q)}))
    return GlobalScopeContract(global_terms=global_terms, time_terms=time_terms)


# ---------------------------------------------------------------- E10 比值方向

# 「A 是 B 的几倍」/「A 相当于 B 的多少倍」/「A 占 B 的比例」三类方向句式
_RATIO_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "multiple",
        re.compile(r"(?P<num>[^，。；？、]{2,40}?)是(?P<den>[^，。；？、]{2,40}?)的(?:几倍|多少倍)"),
        "「A 是 B 的几倍」⇒ numerator = A，denominator = B",
    ),
    (
        "equivalent",
        re.compile(
            r"(?P<num>[^，。；？、]{2,40}?)相当于(?P<den>[^，。；？、]{2,40}?)的(?:几倍|多少倍)"
        ),
        "「A 相当于 B 的多少倍」⇒ numerator = A，denominator = B",
    ),
    (
        "share",
        re.compile(
            r"(?P<num>[^，。；？、]{2,40}?)占(?P<den>[^，。；？、]{2,40}?)的?(?:比例|占比|百分比|百分之)"
        ),
        "「A 占 B 的比例」⇒ numerator = A，denominator = B",
    ),
)

# 题面含比值语义（决定是否注入 E10）
_RATIO_HINT_PATTERN = re.compile(r"几倍|多少倍|倍数|比例|占比|百分比|ratio|增速|增长幅度|同比|环比")

# 增速类（方向由定义固定，不需要从句式抽取实体）
_GROWTH_HINT_PATTERN = re.compile(r"增速|增长幅度|同比|环比")

# 抽取结果「不干净」的判据：指示代词 / 连接词开头或内含，说明从句式拿不到真正的
# 分子分母（如 E-0076「它们各占订单总量的百分之几」会抽出「它们各」）。
# 这类情况**不**给出题面级方向提示，只保留通用方向契约 —— 宁可少说，不可说错。
#
# 注意：「该」**不**列为脏前缀 —— 「该地区 / 该季度总销售金额」是合法且精确的
# 分母表述（E-0083 / E-0099），把它判脏会白白丢掉可用的方向信息。
_DIRTY_SPAN_PREFIXES = ("它们", "其", "并", "这", "那", "以上", "上述", "其中", "各", "两者")
_DIRTY_SPAN_CONTAINS = ("及其", "并给出", "请给出", "分别是")


def _is_clean_span(text: str) -> bool:
    if len(text) < 2:
        return False
    if text.startswith(_DIRTY_SPAN_PREFIXES):
        return False
    return not any(token in text for token in _DIRTY_SPAN_CONTAINS)


@dataclass(frozen=True)
class RatioDirectionContract:
    """E10：比值方向契约（numerator = 被除数，denominator = 除数）。

    `numerator` / `denominator` 为 None 表示「从句式无法稳定抽取方向」——
    此时只注入通用方向契约，不给出可能出错的题面级提示。
    """

    form: str
    numerator: str | None
    denominator: str | None
    evidence: str

    @property
    def direction_extracted(self) -> bool:
        return self.numerator is not None and self.denominator is not None

    def to_prompt_block(self) -> str:
        if self.form == "growth":
            concrete = (
                "- 本题为增速类比值：numerator = （本期值 − 上期值），denominator = 上期值；\n"
                f"  依据：{self.evidence}\n"
            )
        elif self.direction_extracted:
            concrete = (
                f"- 本题题面识别到的方向：numerator（被除数）= 「{self.numerator}」，"
                f"denominator（除数）= 「{self.denominator}」\n"
                f"  依据：{self.evidence}\n"
            )
        else:
            concrete = (
                "- 本题未能从句式稳定抽取方向，必须由你按题面语义确定，"
                "并在 explanation 中写明 numerator / denominator 各是什么；\n"
                f"  依据：{self.evidence}\n"
            )
        return (
            "【比值方向契约】（本题要求计算比值 / 倍数 / 占比 / 增速，请先确定方向再写 SQL）\n"
            "- 生成 ratio 前必须先显式写出两件事：numerator（被除数 / 分子）= ？ "
            "denominator（除数 / 分母）= ？\n"
            f"{concrete}"
            "- 方向由**题面语义**决定，不得由两个数字在 SQL 中出现的先后顺序决定：\n"
            "  「A 是 B 的几倍」⇒ A / B；「A 相当于 B 的多少倍」⇒ A / B；"
            "「A 占 B 的比例」⇒ A / B；\n"
            "  「A 比 B 增长 / 同比 / 环比」⇒ (A − B) / B（分母是**基期**，不是本期）；\n"
            "- 写完 SQL 后自检一次方向：若题面说「下半年是上半年的几倍」，"
            "而结果 < 1，必须复查分子分母是否颠倒；\n"
            "- 分母必须做除零保护（NULLIF(x, 0)）。\n"
        )


def detect_ratio_direction(question: str) -> RatioDirectionContract | None:
    """识别比值 / 倍数 / 占比 / 增速题并抽取方向。

    Returns:
        RatioDirectionContract（需注入 E10 段）或 None（不注入）。
    """
    if not question or not question.strip():
        return None
    q = question.strip()
    if not _RATIO_HINT_PATTERN.search(q):
        return None

    for form, pattern, rule in _RATIO_PATTERNS:
        m = pattern.search(q)
        if not m:
            continue
        num = m.group("num").strip()
        den = m.group("den").strip()
        if _is_clean_span(num) and _is_clean_span(den) and num != den:
            return RatioDirectionContract(
                form=form,
                numerator=num,
                denominator=den,
                evidence=f"题面片段「{m.group(0)}」；{rule}",
            )
        return RatioDirectionContract(
            form=form,
            numerator=None,
            denominator=None,
            evidence=(
                f"题面含「{m.group(0)}」句式，但抽取出的分子/分母含指示代词或连接词，"
                "无法据此确定方向"
            ),
        )

    if _GROWTH_HINT_PATTERN.search(q):
        return RatioDirectionContract(
            form="growth",
            numerator="(本期值 − 上期值)",
            denominator="上期值",
            evidence="题面含增速 / 增长幅度 / 同比 / 环比语义，分母固定为基期值",
        )
    return None


# ---------------------------------------------------------------- E11 排名破平

# Top-N 集合（显式 N）
_RANK_TOPN_PATTERN = re.compile(
    r"最[高低多少快慢大小][^，。；？]{0,12}?(?:的)?\s*(?P<n>\d+)\s*[款个名项笔位月种]"
    r"|前\s*(?P<n2>\d+)"
    r"|(?:Top|TOP)\s*(?P<n3>\d+)"
)
# 「最X的是哪些 / 哪几个」——集合型排名（无显式 N）
_RANK_SUPERLATIVE_SET_PATTERN = re.compile(
    r"最[高低多少快慢大小][^，。；？]{0,12}?(?:的)?(?:是)?(?:哪些|哪几个|哪几笔)"
)
# 显式名次 / 排名语义
_RANK_EXPLICIT_PATTERN = re.compile(r"排名|第\s*[一二三四五六七八九十\d]+\s*名")

# 排除：标量 Top-1（只问指标值，不返回实体，破平键不影响返回值）
_RANK_SCALAR_ONLY_PATTERN = re.compile(
    r"最[高低多少快慢大小][^，。；？]{0,12}?(?:是)?(?:多少|几)"
)

_PRIMARY_KEYS = (
    "orders.id",
    "order_items.id",
    "products.id",
    "categories.id",
    "users.id",
)


@dataclass(frozen=True)
class RankingTiebreakContract:
    """E11：Top-N / 排名确定性破平契约。"""

    ranking_phrase: str
    limit_n: int | None

    def to_prompt_block(self) -> str:
        n_text = (
            f"- 本题的 Top-N 规模：N = {self.limit_n}\n"
            if self.limit_n is not None
            else "- 本题为集合型排名（未显式给出 N）\n"
        )
        return (
            "【Top-N 确定性排序契约】（本题是 Top-N / 排名题，请注意并列风险）\n"
            f"- 识别到的排名表述：「{self.ranking_phrase}」\n"
            f"{n_text}"
            "- ⚠️ **E11 是 append-only ORDER BY contract，不是 SQL rewriting contract。**\n"
            "- **唯一允许的改动**：在**最终排名结果的 ORDER BY 末尾追加 ≤1 个 tie-breaker**"
            "（或用当前 block 已存在的可见列直接作为该追加键）。\n"
            "- ❌ 除排序外**禁止改动任何其他部分**：SELECT、SELECT 列集合、FROM、JOIN 关系、"
            "JOIN ON 条件、WHERE、HAVING、GROUP BY、LIMIT，全部必须与「不加破平键时」一致。\n"
            "- ❌ **绝对禁止为获取 tie-breaker 而新增任何 JOIN**（即使该 JOIN 两侧列都可见），"
            "也禁止修改 / 重写已有 JOIN 的 ON 条件；破平键只能引用当前 query block **原本就可见**"
            "的列（已有 FROM/JOIN 关系，或当前 CTE/子查询已暴露的输出列）。\n"
            "- ❌ **绝对禁止改写任何日期 / 时间过滤**：不得把范围式（`>=` / `>` / `<=` / `<` / "
            "`BETWEEN`）改写成 `LIKE` / `substr` / `strftime` / `DATE()` / `CAST()` 或任何函数包裹，"
            "也不得改动日期边界、常量、运算符、比较方向或 AND/OR 结构。"
            "反例：`order_date >= '2025-10-01' AND order_date < '2026-01-01'` 不得改写为 "
            "`substr(order_date, 1, 7) = '2025-10'`（会把 Q4 错误收窄成仅 10 月）。\n"
            "- ❌ 禁止为了加入 tie-breaker 而重新生成整个查询逻辑。\n"
            "- 若当前 query block **确实没有**任何可用的可见稳定破平键，则**宁可不追加破平键**，"
            "也绝不为破平键新增 JOIN 或臆造不可见列。\n"
            "- 破平键优先使用当前 block 可见的业务主键 / 唯一标识"
            "（orders.id / order_items.id / products.id / categories.id / users.id / 商品名 / 地区名 / 类别名 / 月份）；\n"
            "- 适用条件：排名 / 截断（ORDER BY … LIMIT n、ROW_NUMBER()/RANK()/DENSE_RANK() … <= n、"
            "前 N 名）且**排序键可能并列**（尤其按 SUM / COUNT / AVG 等聚合指标排序）时追加；\n"
            "- 正确写法示例：`ORDER BY 指标 DESC, p.id ASC`；窗口函数同理："
            "`ROW_NUMBER() OVER (PARTITION BY … ORDER BY 指标 DESC, p.id ASC)`；\n"
            "- ❌ **破平键必须属于当前 query block 可见且实际存在的列**：只能引用当前 "
            "`FROM`/`JOIN` 中**真实存在的关系**的列，或当前 `CTE` / 子查询**已经暴露**"
            "（出现在其输出列中）的列；不得引用当前 `FROM`/`JOIN` 里不存在的关系，"
            "也不得引用当前 `CTE` / 子查询未暴露的列。"
            "反例：`WITH s AS (SELECT o.region, c.name AS category_name, …) … "
            "ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC)` "
            "—— 此处 `c` 是 CTE 别名，而该 CTE 的输出列里**没有** `id`，"
            "执行会直接报 `no such column: c.id`；应改用该 query block **可见**的列"
            "（如 CTE 已暴露的 `region` / `category_name`）。\n"
            "- ❌ **禁止把破平键写进 GROUP BY**：不得出现 `GROUP BY …, p.id` 这类写法。"
            "破平键不是分组维度；写进 GROUP BY 会把「按实体聚合」拆成「按行聚合」，"
            "聚合粒度被改变，结果必然算错。\n"
            "- ❌ **禁止把破平键写进 SELECT**：不得出现 `SELECT …, p.id`，"
            "除非原问题本身明确要求输出该字段（如题目要求「请给出订单 ID」）。"
            "多输出一列会破坏结果列契约。\n"
            "- ❌ **禁止因为本契约改动 WHERE / HAVING 中的任何过滤条件**，尤其是日期 / 时间条件："
            "破平键只影响排序，与过滤无关。不得改写、收窄、放宽或重写已有日期表达式"
            "（反例：把 `order_date >= '2025-10-01' AND order_date < '2026-01-01'` 改写成 "
            "`substr(order_date, 1, 7) = '2025-10'`）。\n"
            "- ❌ **禁止因为本契约改变原有聚合粒度**：GROUP BY 的列集合必须与「不加破平键时」"
            "完全一致；本契约只允许在 ORDER BY 末尾追加一个键。\n"
            "- 不要给所有 ORDER BY 机械追加主键：仅当本题确实是「排名 / Top-N / LIMIT / 名次过滤」"
            "且排序键存在并列可能时才追加。\n"
            "- 原因：排序键并列时，不追加破平键会让「谁进入 Top-N」变得不确定，"
            "同一 SQL 在不同执行计划下可能选中不同实体。\n"
        )


def detect_ranking_tiebreak(question: str) -> RankingTiebreakContract | None:
    """识别 Top-N / 排名题并抽取 N。

    Returns:
        RankingTiebreakContract（需注入 E11 段）或 None（不注入）。

    Notes:
        刻意排除「标量 Top-1」题（如「售价最高的商品价格是多少？」）：
        该类题只返回指标值，破平键不影响返回值，注入只会增加无关约束。
    """
    if not question or not question.strip():
        return None
    q = question.strip()

    m = _RANK_TOPN_PATTERN.search(q)
    if m:
        raw_n = m.group("n") or m.group("n2") or m.group("n3")
        n = int(raw_n) if raw_n else None
        return RankingTiebreakContract(ranking_phrase=m.group(0).strip(), limit_n=n)

    m = _RANK_SUPERLATIVE_SET_PATTERN.search(q)
    if m:
        return RankingTiebreakContract(ranking_phrase=m.group(0).strip(), limit_n=None)

    if _RANK_EXPLICIT_PATTERN.search(q) and not _RANK_SCALAR_ONLY_PATTERN.search(q):
        return RankingTiebreakContract(
            ranking_phrase=_RANK_EXPLICIT_PATTERN.search(q).group(0).strip(), limit_n=None
        )
    return None


__all__ = [
    "GlobalScopeContract",
    "RatioDirectionContract",
    "RankingTiebreakContract",
    "detect_global_scope",
    "detect_ratio_direction",
    "detect_ranking_tiebreak",
    "_PRIMARY_KEYS",
]
