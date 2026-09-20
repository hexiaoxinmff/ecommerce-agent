"""Few-shot 数据结构（Pydantic）。"""

from pydantic import BaseModel, Field


class FewShotExample(BaseModel):
    """一条人工整理的 Text2SQL 参考示例（来自 data/fewshot/*.json）。"""

    id: str
    question: str
    scenario: str
    tables: list[str]
    columns: list[str]  # 一律使用「表名.字段名」
    sql: str
    explanation: str
    tags: list[str] = []


class FewShotQuery(BaseModel):
    """Few-shot 检索输入。

    - question：用户原问题；
    - tables / columns：来自阶段 4-任务 3 Schema Linking 的结果（可选）；
    - scenario：可选场景标签；
    - top_k：返回条数，默认 3（API 层限制 1~50，Retriever 内部会裁剪到数据集大小）。
    """

    question: str = Field(..., min_length=1, max_length=500)
    tables: list[str] = []
    columns: list[str] = []
    scenario: str | None = None
    top_k: int = 3


class FewShotMatch(BaseModel):
    """一条检索命中的示例。"""

    example_id: str
    score: float
    question: str
    scenario: str
    tables: list[str]
    columns: list[str]
    sql: str
    explanation: str


class FewShotResult(BaseModel):
    """检索结果：按 score 降序（同分按 example_id 稳定排序）。"""

    question: str
    matches: list[FewShotMatch]