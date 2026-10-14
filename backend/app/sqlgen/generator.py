"""SQL Generator：question + Schema Linking + Few-shot -> Mimo -> 校验 -> SQL。

流程（必须按此顺序）：
1. SchemaLinker.link(question)
2. FewShotRetriever.retrieve(...)
3. 拼接 SQL Generation Prompt
4. LLMProvider.generate(...)
5. 解析模型返回 JSON
6. 校验（SQL 安全 / Schema 一致性 / 表引用一致）
7. 输出 SQLGenerationResult

本阶段只生成与校验 SQL，不执行 SQL，不做失败重试 / SQL Repair。

上层只能依赖 LLMProvider 抽象；禁止直接 import openai / Mimo API。

两种入口：
- generate(question)：自带 Schema Linking + Few-shot（默认行为，不变）；
- generate_with_context(question, link_result, fs_result)：使用调用方
  （如 LangGraph）已准备好的 Schema Linking 与 Few-shot，**不会重复调用**
  SchemaLinker / FewShotRetriever，避免 graph 中的重复 Mimo 调用。
"""

from typing import TYPE_CHECKING

from app.fewshot.models import FewShotQuery, FewShotResult
from app.fewshot.retriever import FewShotRetriever
from app.llm.provider import LLMProvider, get_llm_provider
from app.schema.linker import SchemaLinker
from app.schema.metadata import SchemaCatalog
from app.sqlgen.prompt import SYSTEM_PROMPT, build_prompt, system_prompt_for
from app.sqlgen.validator import parse_llm_output, validate_output
from app.schemas.schema_link import SchemaLinkResult
from app.schemas.sql_generate import SQLGenerationResult

if TYPE_CHECKING:  # 仅类型标注；运行时由调用方注入，避免反向依赖
    from app.dbprofile.adapter import DatabaseAdapter

FEWSHOT_TOP_K = 3


class SQLGenerator:
    """Text2SQL 生成器（组合 SchemaLinker + FewShotRetriever + LLMProvider）。"""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        schema_linker: SchemaLinker | None = None,
        fewshot_retriever: FewShotRetriever | None = None,
        adapter: "DatabaseAdapter | None" = None,
        appendix_rules: str = "",
    ) -> None:
        self._provider = provider or get_llm_provider()
        # 未显式注入时，SchemaLinker 复用同一个 provider 实例
        self._schema_linker = schema_linker or SchemaLinker(provider=self._provider)
        self._fewshot_retriever = fewshot_retriever or FewShotRetriever()
        # Phase 13：注入 DatabaseAdapter 后，System Prompt 与业务口径来自 Profile；
        # 缺省 None = 原全局行为（冻结基线逐字节不变）。
        self._adapter = adapter
        # Phase 15（P0-1/P0-2）：运行时附录（KPI 口径定义 + 数据时效契约）。
        # 显式传入时追加到 Prompt；空串 = 不追加（冻结基线逐字节不变）。
        self._appendix_rules = appendix_rules

    def generate(self, question: str) -> SQLGenerationResult:
        """自带 Schema Linking + Few-shot 的完整生成（默认入口，行为不变）。

        Raises:
            SchemaLinkingInvalidError / LLMError：Schema Linking / Provider 失败；
            FewShotDatasetError：Few-shot 数据集异常；
            SQLGenOutputInvalidError / SQLGenSchemaMismatchError /
            SQLUnsafeError / SQLTableMismatchError：模型输出校验失败。
        """
        link_result = self._schema_linker.link(question)
        fs_result = self._fewshot_retriever.retrieve(
            FewShotQuery(
                question=question,
                tables=link_result.tables,
                columns=link_result.columns,
                top_k=FEWSHOT_TOP_K,
            )
        )
        return self.generate_with_context(question, link_result, fs_result)

    def generate_with_context(
        self,
        question: str,
        link_result: SchemaLinkResult,
        fs_result: FewShotResult,
    ) -> SQLGenerationResult:
        """使用调用方已准备好的 Schema Linking 与 Few-shot 生成 SQL（不重复执行前两步）。

        Raises:
            SQLGenOutputInvalidError / SQLGenSchemaMismatchError /
            SQLUnsafeError / SQLTableMismatchError：模型输出校验失败；
            LLMError：Provider 调用失败（原样透传）。
        """
        if self._adapter is not None:
            system_prompt = system_prompt_for(self._adapter.profile.domain_name)
            business_rules = self._adapter.profile.business_rules.generation_rules
            catalog = self._adapter.get_cached_catalog()
            appendix = self._adapter.prompt_appendix()
        else:
            system_prompt = SYSTEM_PROMPT
            business_rules = None
            catalog = SchemaCatalog.from_database()
            appendix = self._appendix_rules

        prompt = build_prompt(
            question,
            link_result,
            fs_result,
            business_rules=business_rules,
            appendix_rules=appendix or None,
        )
        raw = self._provider.generate(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )

        data = parse_llm_output(raw)
        validated = validate_output(data, link_result.tables, catalog)

        # question 必须保留用户原始问题
        return SQLGenerationResult(
            question=question,
            sql=validated["sql"],
            tables=validated["tables"],
            columns=validated["columns"],
            fewshot_examples=[m.example_id for m in fs_result.matches],
            explanation=validated["explanation"],
        )