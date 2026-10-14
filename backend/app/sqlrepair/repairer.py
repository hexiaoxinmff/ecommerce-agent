"""SQL Repairer + 有限 Repair 闭环 Orchestrator。

- 只针对「数据库执行阶段」错误触发 Repair；Safety 阶段被拒绝的 SQL 永不进入；
- repair_count <= 1，execute_count <= 2（闭环由本模块保证，不做循环重试）；
- 只依赖 LLMProvider 抽象（当前 MimoProvider），禁止 openai 直连。
"""

from typing import TYPE_CHECKING

from app.fewshot.models import FewShotQuery
from app.fewshot.retriever import FewShotRetriever
from app.llm.provider import LLMError, LLMProvider, get_llm_provider
from app.schema.metadata import SchemaCatalog
from app.sqlrepair.errors import (
    SQLRepairError,
    SQLRepairOutputInvalidError,
    SQLRepairSafetyError,
    SQLRepairSchemaError,
)
from app.sqlrepair.models import (
    SQLExecuteWithRepairResult,
    SQLRepairRequest,
    SQLRepairResult,
    sanitize_execution_error,
)
from app.sqlrepair.prompt import (
    SYSTEM_PROMPT,
    build_repair_prompt,
    format_fewshot,
)
from app.sqlrepair.validator import validate_repair_output
from app.sqlexec.errors import (
    SQLExecutionDatabaseError,
    SQLExecutionSafetyError,
)
from app.sqlexec.executor import execute as execute_sql

if TYPE_CHECKING:  # 仅类型标注；运行时由调用方注入，避免反向依赖
    from app.dbprofile.adapter import DatabaseAdapter

_REPAIR_FEWSHOT_TOP_K = 2


class SQLRepairer:
    """有限单次 SQL 修复器（repair_count <= 1，由 Orchestrator 保证）。"""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        fewshot_retriever: FewShotRetriever | None = None,
        adapter: "DatabaseAdapter | None" = None,
        appendix_rules: str = "",
    ) -> None:
        self._provider = provider or get_llm_provider()
        self._fewshot_retriever = fewshot_retriever or FewShotRetriever()
        # Phase 13：注入 DatabaseAdapter 后，Schema 目录与业务口径来自 Profile；
        # 缺省 None = 原全局行为（默认业务库 + 本模块常量）。
        self._adapter = adapter
        # Phase 15（P0-1）：运行时附录（数据时效契约）；空串 = 不追加。
        self._appendix_rules = appendix_rules

    def repair(self, request: SQLRepairRequest) -> SQLRepairResult:
        """修复一条执行失败的 SQL，返回修复后的 SQL 与理由（不执行）。

        Raises:
            SQLRepairOutputInvalidError / SQLRepairSafetyError /
            SQLRepairSchemaError：Repair 输出校验失败；
            LLMError：Provider 调用失败（原样透传）。
        """
        if self._adapter is not None:
            catalog = self._adapter.get_cached_catalog()
            business_rules = self._adapter.profile.business_rules.repair_rules
            appendix = self._adapter.prompt_appendix()
        else:
            catalog = SchemaCatalog.from_database()
            business_rules = None
            appendix = self._appendix_rules

        # Few-shot 参考（本地检索，仅作上下文增强；失败不阻断修复）
        fewshot_text = "（无匹配 Few-shot 示例）"
        try:
            fs = self._fewshot_retriever.retrieve(
                FewShotQuery(
                    question=request.question,
                    tables=request.tables,
                    columns=request.columns,
                    top_k=_REPAIR_FEWSHOT_TOP_K,
                )
            )
            fewshot_text = format_fewshot(fs)
        except Exception:
            fewshot_text = "（无匹配 Few-shot 示例）"

        prompt = build_repair_prompt(
            request_sql=request.original_sql,
            error_message=sanitize_execution_error(request.error_message),
            question=request.question,
            tables=request.tables,
            columns=request.columns,
            catalog=catalog,
            fewshot_text=fewshot_text,
            business_rules=business_rules,
            appendix_rules=appendix or None,
        )
        raw = self._provider.generate(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        return validate_repair_output(
            raw, request.original_sql, request.tables, catalog
        )


class SQLExecuteWithRepairOrchestrator:
    """有限 Repair 闭环：Execute -> 失败 -> Repair(一次) -> Safety/Schema -> Execute(一次)。

    计数语义：
    - execute_count：对数据库的实际执行次数（Safety 阶段拒绝 = 0）；
    - repair_count：发起 Repair 的次数（<= 1）。
    """

    def __init__(
        self,
        repairer: SQLRepairer | None = None,
        executor=execute_sql,
    ) -> None:
        self._repairer = repairer or SQLRepairer()
        self._executor = executor

    def run(
        self,
        question: str,
        sql: str,
        tables: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> SQLExecuteWithRepairResult:
        tables = tables or []
        columns = columns or []

        # ---- 第一次执行 ----
        try:
            result = self._executor(sql)
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=1,
                repair_count=0,
                result=result,
            )
        except SQLExecutionSafetyError as exc:
            # Safety 阶段拒绝：直接失败，不触发 Repair（execute_count=0）
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=0,
                repair_count=0,
                original_error=sanitize_execution_error(str(exc)),
            )
        except SQLExecutionDatabaseError as exc:
            # 进入 Repair（仅数据库执行阶段错误）
            original_error = sanitize_execution_error(str(exc))
            return self._repair_and_reexecute(
                question, sql, tables, columns, original_error
            )

    def _repair_and_reexecute(
        self,
        question: str,
        sql: str,
        tables: list[str],
        columns: list[str],
        original_error: str,
    ) -> SQLExecuteWithRepairResult:
        # 只修一次：Repair -> 校验 ->（通过才）第二次执行
        try:
            repaired = self._repairer.repair(
                SQLRepairRequest(
                    question=question,
                    original_sql=sql,
                    error_message=original_error,
                    tables=tables,
                    columns=columns,
                )
            )
        except SQLRepairSafetyError as exc:
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=1,
                repair_count=1,
                original_error=original_error,
                repair_error=str(exc),
            )
        except (SQLRepairOutputInvalidError, SQLRepairSchemaError) as exc:
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=1,
                repair_count=1,
                original_error=original_error,
                repair_error=str(exc),
            )
        except SQLRepairError as exc:  # 其他 Repair 层错误
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=1,
                repair_count=1,
                original_error=original_error,
                repair_error=str(exc),
            )
        except LLMError as exc:
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=1,
                repair_count=1,
                original_error=original_error,
                repair_error=f"LLM error: {type(exc).__name__}",
            )

        # 第二次执行（最多一次）
        try:
            result = self._executor(repaired.repaired_sql)
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=2,
                repair_count=1,
                original_error=original_error,
                repaired_sql=repaired.repaired_sql,
                repair_reason=repaired.repair_reason,
                result=result,
            )
        except SQLExecutionDatabaseError as exc:
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=2,
                repair_count=1,
                original_error=original_error,
                repaired_sql=repaired.repaired_sql,
                repair_reason=repaired.repair_reason,
                repair_error=sanitize_execution_error(str(exc)),
            )
        except SQLExecutionSafetyError as exc:
            # 修复后 Safety 拒绝：不进入执行（保持 execute_count=1）
            return SQLExecuteWithRepairResult(
                question=question,
                sql=sql,
                execute_count=1,
                repair_count=1,
                original_error=original_error,
                repaired_sql=repaired.repaired_sql,
                repair_reason=repaired.repair_reason,
                repair_error=f"Repair Safety Rejected: {exc}",
            )