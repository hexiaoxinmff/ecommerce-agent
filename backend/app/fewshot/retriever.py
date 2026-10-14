"""规则型 Few-shot Retriever。

纯本地、确定性、可解释检索，**不调用 Mimo / OpenAI / Embedding API**。

score = W1 * keyword + W2 * table_overlap + W3 * column_overlap + W4 * scenario
- W1=0.30 / W2=0.25 / W3=0.25 / W4=0.20
- keyword：用户问题与 example（问题+标签）的中文关键词 Jaccard 重合度；
- table_overlap：用户 tables 与 example tables 的 Jaccard；
- column_overlap：用户 columns 与 example columns 的 Jaccard；
- scenario：用户 scenario 与 example scenario 完全相等取 1.0，否则取
  0.5 * tags Jaccard。

输出按 (score, example_id) 稳定降序；top_k 越界不会崩溃：
小于 1 抛 ValueError，大于数据集大小按数据集大小裁剪。

注意：score 是「检索相似度」，不是「SQL 正确性」。
后续 SQL Generator 仍需重新生成并验证 SQL。
"""

from app.fewshot.dataset import get_dataset
from app.fewshot.models import FewShotExample, FewShotMatch, FewShotQuery, FewShotResult

# 中文关键词词表（用于可解释的关键词匹配）
KEYWORDS: tuple[str, ...] = (
    "销售额",
    "销量",
    "订单",
    "用户",
    "地区",
    "区域",
    "商品",
    "类别",
    "分类",
    "排名",
    "趋势",
    "平均",
    "均价",
    "数量",
    "价格",
    "金额",
    "近30天",
    "近7天",
    "上月",
    "本月",
    "时间范围",
    "注册",
    "活跃",
    "在售",
    "占比",
    "取消",
    "Top",
    "客单",
    "复购",
)

# 各分量权重（总和 = 1.0）
WEIGHTS = {"keyword": 0.30, "table": 0.25, "column": 0.25, "scenario": 0.20}


def _matched_keywords(text: str) -> set[str]:
    """提取文本中出现的中文关键词。"""
    return {kw for kw in KEYWORDS if kw in text}


def _jaccard(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _keyword_score(query: str, example: FewShotExample) -> float:
    """用户问题与 example（问题 + 标签）的关键词 Jaccard。"""
    query_keys = _matched_keywords(query)
    example_keys = _matched_keywords(example.question).union(
        set(example.tags)
    )
    return _jaccard(query_keys, example_keys)


def _table_score(query_tables: list[str], example: FewShotExample) -> float:
    return _jaccard(set(query_tables), set(example.tables))


def _column_score(query_columns: list[str], example: FewShotExample) -> float:
    return _jaccard(set(query_columns), set(example.columns))


def _scenario_score(query_scenario: str | None, example: FewShotExample) -> float:
    if query_scenario and query_scenario == example.scenario:
        return 1.0
    if query_scenario:
        return 0.5 * _jaccard({query_scenario}, set(example.tags))
    return 0.0


def score_example(query: FewShotQuery, example: FewShotExample) -> float:
    """计算单个 example 的检索得分（0~1）。"""
    return (
        WEIGHTS["keyword"] * _keyword_score(query.question, example)
        + WEIGHTS["table"] * _table_score(query.tables, example)
        + WEIGHTS["column"] * _column_score(query.columns, example)
        + WEIGHTS["scenario"] * _scenario_score(query.scenario, example)
    )


class FewShotRetriever:
    """基于本地数据集的规则型 Top-K 检索器。"""

    def __init__(
        self,
        dataset: list[FewShotExample] | None = None,
        keywords: tuple[str, ...] | None = None,
    ) -> None:
        self._dataset = dataset if dataset is not None else get_dataset()
        # Phase 13（跨数据库适配）：关键词词表可由 Few-shot Profile 注入；
        # 缺省 None = 本模块 KEYWORDS（默认电商词表，行为不变）。
        self._keywords = keywords if keywords is not None else KEYWORDS

    def _matched_keywords_of(self, text: str) -> set[str]:
        return {kw for kw in self._keywords if kw in text}

    def retrieve(self, query: FewShotQuery) -> FewShotResult:
        """检索 Top-K 示例：按 (score 降序, example_id 升序) 稳定排序。"""
        if query.top_k < 1:
            raise ValueError("top_k 必须大于等于 1")

        scored = [
            (example, round(self._score_example(query, example), 4))
            for example in self._dataset
        ]
        scored.sort(key=lambda item: (-item[1], item[0].id))

        effective_k = min(query.top_k, len(scored))
        matches = [
            FewShotMatch(
                example_id=example.id,
                score=score,
                question=example.question,
                scenario=example.scenario,
                tables=example.tables,
                columns=example.columns,
                sql=example.sql,
                explanation=example.explanation,
            )
            for example, score in scored[:effective_k]
        ]
        return FewShotResult(question=query.question, matches=matches)

    def _score_example(self, query: FewShotQuery, example: FewShotExample) -> float:
        query_keys = self._matched_keywords_of(query.question)
        example_keys = self._matched_keywords_of(example.question).union(
            set(example.tags)
        )
        return (
            WEIGHTS["keyword"] * _jaccard(query_keys, example_keys)
            + WEIGHTS["table"] * _table_score(query.tables, example)
            + WEIGHTS["column"] * _column_score(query.columns, example)
            + WEIGHTS["scenario"] * _scenario_score(query.scenario, example)
        )