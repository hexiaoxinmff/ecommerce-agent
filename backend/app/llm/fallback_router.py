"""百炼免费模型池自动 Fallback Router（Task66）。

问题（Task65 实测）：单一 Bailian model 的免费额度 / 调用状态一旦异常，
正式 100Q 可以在中途大面积 PROVIDER_FAIL。
百炼不同模型 / 快照的免费额度相互独立，且平台**不会**自动把请求切到另一个模型，
因此必须在应用侧实现「免费模型池 + 自动 fallback + exhausted cache + 安全停止」。

核心原则（§2）：**绝不「所有 403 → 换模型」**。同为 403，
``AllocationQuota.FreeTierOnly``（可切下一个免费模型）与
``Endpoint.AccessDenied``（模型不可用，不得声称额度耗尽）处置完全相反，
必须按错误类型分类。

分类总表（唯一权威实现见 ``classify_failure``）：

| 上游情形                                  | 分类              | 处置                     |
|-------------------------------------------|-------------------|--------------------------|
| 403 + AllocationQuota.FreeTierOnly        | FREE_QUOTA_EXHAUSTED | 标记 EXHAUSTED → 下一个 |
| 403 + Endpoint.AccessDenied               | MODEL_UNAVAILABLE | 标记 UNAVAILABLE → 下一个 |
| 401 / 其它 403（无可用 code）              | AUTHENTICATION    | STOP，不换模型           |
| 402 账户余额不足                           | ACCOUNT_LEVEL     | STOP，不换模型           |
| 429 限流                                   | RATE_LIMITED      | STOP，**不得**标记 EXHAUSTED |
| 超时 / 连接失败                            | NETWORK           | STOP，**不得**标记 EXHAUSTED |
| 5xx / 其他未预期                           | TRANSIENT / UNKNOWN | STOP，**不得**永久 quarantine |

设计不变量：
- §9 循环保护：单个 request 内，一个 model 最多尝试一次（``tried`` 集合）。
- §6/§7 缓存：EXHAUSTED / UNAVAILABLE 在**进程生命周期内**保持，绝不落盘
  （第二天额度可能恢复或进入新周期）。
- §5 只有 EXHAUSTED / UNAVAILABLE 会被跳过；RATE_LIMITED / TRANSIENT_ERROR
  只作观测记录，绝不当成额度耗尽。
- §10 错误传播：NO_FREE_MODEL_AVAILABLE 必须含 attempted_models /
  model_states / last_errors，且**绝不含** API Key / Authorization / headers。
- §26 Router 是纯透传：绝不修改 question / schema / fewshot / prompt / SQL /
  result；唯一变化是 actual model。
- §16 lazy fallback：只有当前模型真实请求返回额度耗尽才切换，不做预探测。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from app.llm.model_pool import (
    ERROR_CODE_ENDPOINT_ACCESS_DENIED,
    ERROR_CODE_FREE_QUOTA_EXHAUSTED,
    BailianModelPool,
)
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMProvider,
    LLMProviderNotConfiguredError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    provider_error_code_of,
)

logger = logging.getLogger("app.llm.fallback")

# ---------------------------------------------------------------------------
# 监控事件名（§22）
# ---------------------------------------------------------------------------

EVENT_MODEL_EXHAUSTED = "MODEL_EXHAUSTED"
EVENT_MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
EVENT_MODEL_FALLBACK = "MODEL_FALLBACK"
EVENT_NO_FREE_MODEL_AVAILABLE = "NO_FREE_MODEL_AVAILABLE"
EVENT_MODEL_LOCK_PROVIDER_FAILURE = "MODEL_LOCK_PROVIDER_FAILURE"

# 日志行前缀（§21）
LOG_PREFIX_FALLBACK = "LLM_FALLBACK"


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------

_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{4,}"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{4,}"),
    re.compile(r"(?i)\bauthorization\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bapi[_-]?key\b\s*[:=]\s*\S+"),
)

_MAX_TEXT_LEN = 200


def redact(text: object) -> str:
    """把任意文本中的凭据痕迹替换为 [REDACTED] 并截断（§10 / §21）。

    这是「绝不泄漏 API Key / Authorization / 完整 headers」的兜底闸门：
    即使上游把凭据塞进了错误消息，也不会被写进异常载荷或日志。
    """
    out = str(text)
    for pattern in _REDACT_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    if len(out) > _MAX_TEXT_LEN:
        out = out[: _MAX_TEXT_LEN - 3] + "..."
    return out


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------


class FailureKind(str, Enum):
    """一次模型调用失败的归因分类。"""

    #: 免费额度用尽 —— 唯一允许把模型标记为 EXHAUSTED 的分类。
    FREE_QUOTA_EXHAUSTED = "FREE_QUOTA_EXHAUSTED"
    #: endpoint / 模型不可用 —— 可标记 UNAVAILABLE，但不得声称额度耗尽。
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    #: 认证 / Key / Provider 配置问题 —— 换模型无意义（同一个 Key），必须 STOP。
    AUTHENTICATION = "AUTHENTICATION"
    #: 账户级问题（402 余额不足）—— 换模型同样无意义，必须 STOP。
    ACCOUNT_LEVEL = "ACCOUNT_LEVEL"
    #: 限流（429）—— 默认不是额度耗尽，不得切换、不得标记 EXHAUSTED。
    RATE_LIMITED = "RATE_LIMITED"
    #: 网络 / 超时 —— 不得因一次异常把模型永久标记 exhausted。
    NETWORK = "NETWORK"
    #: 上游 5xx 等瞬态故障 —— 不得永久 quarantine。
    TRANSIENT = "TRANSIENT"
    #: 未预期错误 —— 保守处理（STOP）。
    UNKNOWN = "UNKNOWN"


#: 只有这两个分类允许触发「切换下一个模型」。
FALLBACK_ELIGIBLE_KINDS = frozenset(
    {FailureKind.FREE_QUOTA_EXHAUSTED, FailureKind.MODEL_UNAVAILABLE}
)


def classify_failure(exc: BaseException) -> FailureKind:
    """把 LLM 异常归因为 FailureKind（唯一权威分类实现，§25）。

    ⚠️ 判定顺序至关重要：**结构化错误码优先于异常类型**。
    因为百炼把「额度用尽」和「endpoint 不可用」都映射为
    ``LLMAuthenticationError``（403），若先按类型判断，两者会被
    一起归为 AUTHENTICATION，从而退化成「所有 403 都 STOP」或
    「所有 403 都换模型」—— 两种都是 §2 明令禁止的。
    """
    code = provider_error_code_of(exc)

    # 1) 结构化错误码优先（唯一可区分同类 HTTP 403 的依据）
    if code == ERROR_CODE_FREE_QUOTA_EXHAUSTED:
        return FailureKind.FREE_QUOTA_EXHAUSTED
    if code == ERROR_CODE_ENDPOINT_ACCESS_DENIED:
        return FailureKind.MODEL_UNAVAILABLE

    # 1b) 配额类异常（Phase 4：Provider 层把 403 + AllocationQuota.* 改判为
    # LLMQuotaError）。携带错误码时已被上面的分支命中；此分支兜底覆盖
    # 「异常类型已是配额类但错误码缺失」的防御情形，同样归为额度耗尽。
    if isinstance(exc, LLMQuotaError):
        return FailureKind.FREE_QUOTA_EXHAUSTED

    # 2) 配置 / Key 类：换模型也走同一个 Key，必须 STOP
    if isinstance(exc, (LLMApiKeyNotConfiguredError, LLMProviderNotConfiguredError)):
        return FailureKind.AUTHENTICATION

    # 3) 认证类（401，以及「无可用 code 的 403」）—— 保守 STOP
    if isinstance(exc, LLMAuthenticationError):
        return FailureKind.AUTHENTICATION

    # 4) 账户级（402）：换模型无意义
    if isinstance(exc, LLMInsufficientBalanceError):
        return FailureKind.ACCOUNT_LEVEL

    # 5) 限流（429）：默认 NOT_QUOTA_EXHAUSTED
    if isinstance(exc, LLMRateLimitError):
        return FailureKind.RATE_LIMITED

    # 6) 网络 / 超时：不得误判为额度耗尽
    if isinstance(exc, (LLMTimeoutError, LLMNetworkError)):
        return FailureKind.NETWORK

    # 7) 5xx 等瞬态
    if isinstance(exc, LLMServiceUnavailableError):
        return FailureKind.TRANSIENT

    return FailureKind.UNKNOWN


# ---------------------------------------------------------------------------
# 模型状态与进程内缓存
# ---------------------------------------------------------------------------


class ModelState(str, Enum):
    """模型池中单个模型的运行期状态（§5）。"""

    ACTIVE = "ACTIVE"
    #: 仅允许来自 AllocationQuota.FreeTierOnly。
    EXHAUSTED = "EXHAUSTED"
    #: 来自 Endpoint.AccessDenied 或明确模型不可用。
    UNAVAILABLE = "UNAVAILABLE"
    #: 429 —— 不能视为 exhausted。
    RATE_LIMITED = "RATE_LIMITED"
    #: 5xx 等瞬态 —— 不能视为 exhausted。
    TRANSIENT_ERROR = "TRANSIENT_ERROR"


#: 只有这两个状态会在后续 request 中被跳过。
#: RATE_LIMITED / TRANSIENT_ERROR 刻意不在其中（§5）。
SKIP_STATES = frozenset({ModelState.EXHAUSTED, ModelState.UNAVAILABLE})


@dataclass
class ModelStateRecord:
    """单个模型的状态记录。"""

    model_id: str
    state: ModelState
    reason: str
    error_code: str | None
    first_seen: float
    last_seen: float
    hits: int = 1

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "state": self.state.value,
            "reason": self.reason,
            "error_code": self.error_code,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "hits": self.hits,
        }


class ModelStateCache:
    """进程内模型状态缓存（§6 / §7）。

    - 只存在于内存，**绝不落盘**：第二天免费额度可能恢复或进入新周期，
      持久化会把临时状态变成永久误判。
    - 应用重启 => cache 清空（等价于新建实例）。
    - EXHAUSTED / UNAVAILABLE 为**粘性**状态：一旦进入不会被后续的
      RATE_LIMITED / TRANSIENT_ERROR 覆盖，否则「A fail B fail A fail B fail」
      的无限循环会重新出现。
    """

    def __init__(self) -> None:
        self._records: dict[str, ModelStateRecord] = {}
        self._lock = threading.Lock()

    def get(self, model_id: str) -> ModelStateRecord | None:
        with self._lock:
            return self._records.get(model_id)

    def state_of(self, model_id: str) -> ModelState:
        record = self.get(model_id)
        return record.state if record is not None else ModelState.ACTIVE

    def is_skipped(self, model_id: str) -> bool:
        """该模型是否应在本次 request 中被直接跳过。"""
        return self.state_of(model_id) in SKIP_STATES

    def mark(
        self,
        model_id: str,
        state: ModelState,
        *,
        reason: str,
        error_code: str | None = None,
        now: float | None = None,
    ) -> ModelStateRecord:
        """写入 / 更新状态；粘性跳过态不会被降级。"""
        timestamp = time.time() if now is None else now
        with self._lock:
            existing = self._records.get(model_id)
            if existing is not None:
                # 粘性：已经是跳过态时，保持原状态，只累积观测信息。
                sticky = existing.state in SKIP_STATES
                new_state = existing.state if sticky else state
                existing.state = new_state
                existing.reason = reason if new_state == state else existing.reason
                existing.error_code = (
                    error_code if new_state == state else existing.error_code
                )
                existing.last_seen = timestamp
                existing.hits += 1
                return existing
            record = ModelStateRecord(
                model_id=model_id,
                state=state,
                reason=reason,
                error_code=error_code,
                first_seen=timestamp,
                last_seen=timestamp,
            )
            self._records[model_id] = record
            return record

    def snapshot(self) -> dict[str, dict]:
        """全部状态的结构化快照（用于错误载荷与诊断）。"""
        with self._lock:
            return {mid: rec.to_dict() for mid, rec in self._records.items()}

    def reset(self) -> None:
        """清空缓存。生产语义 = 应用重启（§7）。"""
        with self._lock:
            self._records.clear()


# ---------------------------------------------------------------------------
# 调用结果与事件
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallMetadata:
    """一次成功调用的模型归属元数据（§12）。"""

    requested_model: str
    actual_model: str
    fallback_used: bool
    fallback_index: int

    def to_dict(self) -> dict:
        return {
            "requested_model": self.requested_model,
            "actual_model": self.actual_model,
            "fallback_used": self.fallback_used,
            "fallback_index": self.fallback_index,
        }


@dataclass(frozen=True)
class CallResult:
    """``generate_with_metadata()`` 的返回：内容 + 元数据。"""

    content: str
    metadata: CallMetadata


@dataclass(frozen=True)
class RouterEvent:
    """监控事件（§22）。字段已脱敏，可安全落盘。"""

    name: str
    from_model: str | None
    to_model: str | None
    reason: str
    error_code: str | None
    fallback_index: int
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "from_model": self.from_model,
            "to_model": self.to_model,
            "reason": self.reason,
            "error_code": self.error_code,
            "fallback_index": self.fallback_index,
            "at": self.at,
        }


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class LLMNoFreeModelAvailableError(LLMError):
    """所有配置的免费候选模型都不可用（§4 / §10 / §35）。

    明确停止，绝不「随便找一个模型继续」。
    载荷必须含 attempted_models / model_states / last_errors，
    且**绝不含** API Key / Authorization / headers。
    """

    def __init__(
        self,
        message: str,
        *,
        attempted_models: list[str],
        model_states: dict[str, dict],
        last_errors: dict[str, dict],
    ) -> None:
        super().__init__(message)
        self.attempted_models = list(attempted_models)
        self.model_states = dict(model_states)
        self.last_errors = dict(last_errors)

    def to_dict(self) -> dict:
        return {
            "error": "NO_FREE_MODEL_AVAILABLE",
            "message": str(self),
            "attempted_models": list(self.attempted_models),
            "model_states": dict(self.model_states),
            "last_errors": dict(self.last_errors),
        }


class LLMModelLockProviderFailure(LLMError):
    """``LLM_MODEL_LOCK=true`` 下 primary 不可用（§15）。

    锁模式的唯一合法结果：立即 FAIL_FAST，绝不自动切换 ——
    这样正式实验「一次 run = 一个固定 model」仍然可复现。

    ⚠️ 分类注意事项：本类名**不在** ``evaluation/runner.py`` 的
    ``PROVIDER_ERROR_NAMES`` 集合中，因此若它出现在 benchmark 链路上，
    会被评测器误判为「模型能力失败」而非 provider 失败。
    本任务通过**结构上杜绝该路径**来规避：
    ``get_llm_provider()`` 在 model_lock=True 时返回裸 Provider，
    永远不构造 Router，因此该异常不可能出现在正式评测链路上。
    （既有测试 ``test_lock_mode_never_returns_router`` 锁定该性质。）
    """


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def build_bailian_provider(model_id: str) -> LLMProvider:
    """按 model_id 构造 BailianProvider（默认 provider_factory）。

    延迟导入 bailian，使本模块被导入时不会连带加载 openai SDK 层。
    """
    from app.llm.bailian import BailianProvider

    return BailianProvider(model=model_id)


class FreeTierFallbackRouter:
    """免费模型池自动 Fallback Router。

    实现 ``LLMProvider`` Protocol（name / model / generate），
    因此上层业务代码**无需任何改动**：仍然是 ``provider.generate(messages, ...)``。
    调用方不需要知道当前到底用了 A / B / C；
    若需要，可通过 ``generate_with_metadata()`` 或 ``last_call_metadata`` 取
    ``actual_model``（§11 / §12）。
    """

    name = "bailian-fallback-router"

    def __init__(
        self,
        pool: BailianModelPool,
        provider_factory: Callable[[str], LLMProvider] = build_bailian_provider,
        *,
        cache: ModelStateCache | None = None,
        on_event: Callable[[RouterEvent], None] | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._pool = pool
        self._provider_factory = provider_factory
        self._cache = cache if cache is not None else ModelStateCache()
        self._on_event = on_event
        self._logger = logger_ or logger
        self._last_metadata: CallMetadata | None = None

    # ---------------- 只读视图 ----------------

    @property
    def pool(self) -> BailianModelPool:
        return self._pool

    @property
    def cache(self) -> ModelStateCache:
        return self._cache

    @property
    def model(self) -> str:
        """当前首选模型（``LLMProvider.model`` 语义 = 请求的目标模型）。"""
        return self._pool.primary

    @property
    def last_call_metadata(self) -> CallMetadata | None:
        """最近一次成功调用的元数据。

        注意：实例级状态，并发场景下仅作诊断用途；需要精确归属时请使用
        ``generate_with_metadata()`` 的返回值。
        """
        return self._last_metadata

    # ---------------- 对外接口 ----------------

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
    ) -> str:
        """按池顺序调用模型，返回文本结果（签名与既有 Provider 逐字一致）。"""
        return self.generate_with_metadata(messages, temperature=temperature).content

    def generate_with_metadata(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
    ) -> CallResult:
        """同 ``generate``，但额外返回 actual_model 等元数据（§12）。

        ⚠️ 纯透传：``messages`` / ``temperature`` 原样交给底层 Provider，
        返回内容原样返回 —— 绝不修改 question / schema / fewshot / prompt /
        SQL / result（§26）。
        """
        models = self._pool.configured_models
        if not models:
            raise LLMNoFreeModelAvailableError(
                "NO_FREE_MODEL_AVAILABLE: no model configured in pool",
                attempted_models=[],
                model_states=self._cache.snapshot(),
                last_errors={},
            )

        requested_model = models[0]
        attempted: list[str] = []
        last_errors: dict[str, dict] = {}
        tried: set[str] = set()
        previous_failed: str | None = None
        previous_reason: str = ""

        for model_id in models:
            # §9 同一 request 内同一模型最多一次（防御性，池已去重）
            if model_id in tried:
                continue
            # 锁模式：只允许 primary，其余一律不碰
            if self._pool.model_lock and model_id != requested_model:
                break
            # §6/§7 已 EXHAUSTED / UNAVAILABLE 的模型直接跳过
            if self._cache.is_skipped(model_id):
                continue

            tried.add(model_id)
            index = models.index(model_id)

            if previous_failed is not None:
                # 只有「可 fallback 的失败」才会走到这里（其余分支已 raise）
                self._emit(
                    RouterEvent(
                        name=EVENT_MODEL_FALLBACK,
                        from_model=previous_failed,
                        to_model=model_id,
                        reason=previous_reason,
                        error_code=last_errors.get(previous_failed, {}).get(
                            "provider_error_code"
                        ),
                        fallback_index=index,
                    )
                )

            attempted.append(model_id)
            provider = self._provider_factory(model_id)

            try:
                content = provider.generate(messages, temperature=temperature)
            except LLMError as exc:
                kind = classify_failure(exc)
                summary = _error_summary(exc)
                last_errors[model_id] = summary
                self._record_failure(model_id, kind, exc)

                if self._pool.model_lock:
                    # §15：锁模式绝不自动切换，立即 FAIL_FAST
                    self._emit(
                        RouterEvent(
                            name=EVENT_MODEL_LOCK_PROVIDER_FAILURE,
                            from_model=model_id,
                            to_model=None,
                            reason=kind.value,
                            error_code=summary.get("provider_error_code"),
                            fallback_index=index,
                        )
                    )
                    raise LLMModelLockProviderFailure(
                        f"MODEL_LOCK_PROVIDER_FAILURE: model {model_id} failed "
                        f"({kind.value}); fallback is disabled by LLM_MODEL_LOCK=true"
                    ) from exc

                if kind not in FALLBACK_ELIGIBLE_KINDS:
                    # STOP 家族：认证 / 账户 / 限流 / 网络 / 5xx / 未知
                    raise

                if kind is FailureKind.FREE_QUOTA_EXHAUSTED:
                    self._emit(
                        RouterEvent(
                            name=EVENT_MODEL_EXHAUSTED,
                            from_model=model_id,
                            to_model=None,
                            reason=kind.value,
                            error_code=summary.get("provider_error_code"),
                            fallback_index=index,
                        )
                    )
                else:  # MODEL_UNAVAILABLE
                    self._emit(
                        RouterEvent(
                            name=EVENT_MODEL_UNAVAILABLE,
                            from_model=model_id,
                            to_model=None,
                            reason=kind.value,
                            error_code=summary.get("provider_error_code"),
                            fallback_index=index,
                        )
                    )

                previous_failed = model_id
                previous_reason = kind.value
                continue

            metadata = CallMetadata(
                requested_model=requested_model,
                actual_model=model_id,
                fallback_used=model_id != requested_model,
                fallback_index=index,
            )
            self._last_metadata = metadata
            return CallResult(content=content, metadata=metadata)

        # 全部候选都不可用（或池中无可用候选）
        self._emit(
            RouterEvent(
                name=EVENT_NO_FREE_MODEL_AVAILABLE,
                from_model=previous_failed,
                to_model=None,
                reason=previous_reason or "NO_ACTIVE_MODEL",
                error_code=None,
                fallback_index=-1,
            )
        )
        raise LLMNoFreeModelAvailableError(
            "NO_FREE_MODEL_AVAILABLE: all configured free-tier candidate models "
            f"are unavailable (attempted={attempted})",
            attempted_models=attempted,
            model_states=self._cache.snapshot(),
            last_errors=last_errors,
        )

    # ---------------- 内部 ----------------

    def _record_failure(
        self, model_id: str, kind: FailureKind, exc: BaseException
    ) -> None:
        """按分类写入状态缓存。只有额度耗尽 / 模型不可用才写「跳过态」。"""
        if kind is FailureKind.FREE_QUOTA_EXHAUSTED:
            self._cache.mark(
                model_id,
                ModelState.EXHAUSTED,
                reason=kind.value,
                error_code=provider_error_code_of(exc),
            )
        elif kind is FailureKind.MODEL_UNAVAILABLE:
            self._cache.mark(
                model_id,
                ModelState.UNAVAILABLE,
                reason=kind.value,
                error_code=provider_error_code_of(exc),
            )
        elif kind is FailureKind.RATE_LIMITED:
            # 记录但不跳过（§5：RATE_LIMITED 不能视为 exhausted）
            self._cache.mark(
                model_id, ModelState.RATE_LIMITED, reason=kind.value, error_code=None
            )
        elif kind is FailureKind.TRANSIENT:
            # 记录但不跳过（§5/§2F：不得永久 quarantine）
            self._cache.mark(
                model_id,
                ModelState.TRANSIENT_ERROR,
                reason=kind.value,
                error_code=None,
            )
        # AUTHENTICATION / ACCOUNT_LEVEL / NETWORK / UNKNOWN 是「账户或链路级」
        # 问题，不是模型级状态，刻意不写入模型状态缓存。

    def _emit(self, event: RouterEvent) -> None:
        """记录事件 + 输出脱敏日志（§21 / §22）。"""
        if event.name == EVENT_MODEL_FALLBACK:
            self._logger.info(
                "%s from_model=%s to_model=%s reason=%s error_code=%s fallback_index=%s",
                LOG_PREFIX_FALLBACK,
                event.from_model,
                event.to_model,
                event.reason,
                event.error_code,
                event.fallback_index,
            )
        else:
            self._logger.info(
                "LLM_ROUTER_EVENT name=%s model=%s reason=%s error_code=%s",
                event.name,
                event.from_model,
                event.reason,
                event.error_code,
            )
        if self._on_event is not None:
            self._on_event(event)


def _error_summary(exc: BaseException) -> dict:
    """构造脱敏的错误摘要（供 NO_FREE_MODEL_AVAILABLE 载荷使用）。

    刻意**不含**原始响应体 / headers / URL，且 message 经 redact() 兜底。
    """
    return {
        "error_type": type(exc).__name__,
        "http_status": getattr(exc, "http_status", None),
        "provider_error_code": provider_error_code_of(exc),
        "message": redact(exc),
    }
