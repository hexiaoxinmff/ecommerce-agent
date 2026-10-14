"""Task 66 — 百炼免费模型自动 Fallback Router 单元测试（全部 mock，REAL_API_CALLS=0）。

覆盖任务书 §23 的 15 项必测 + §25 错误分类矩阵 + §26 语义不变性 +
§10 无密钥泄漏 + §19 配置校验 + §29 向后兼容。

设计原则（承袭本项目既有测试风格）：
- 全部使用内存 fake provider，**绝不发起真实网络请求**；
- 断言「分类结果」而不只是「有没有抛异常」——
  因为本任务最大的风险正是「所有 403 被当成同一类」；
- 每条判据都配反例（例如 429 必须**不**被标成 EXHAUSTED）。

运行（务必屏蔽真实冒烟测试，保证 REAL_API_CALLS=0）：
    DASHSCOPE_API_KEY="" python -m pytest backend/tests/test_task66_fallback_router.py \\
        --deselect backend/tests/test_bailian_provider.py::test_real_bailian_smoke
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core import config
from app.llm.bailian import BailianProvider
from app.llm.fallback_router import (
    EVENT_MODEL_EXHAUSTED,
    EVENT_MODEL_FALLBACK,
    EVENT_MODEL_LOCK_PROVIDER_FAILURE,
    EVENT_MODEL_UNAVAILABLE,
    EVENT_NO_FREE_MODEL_AVAILABLE,
    FALLBACK_ELIGIBLE_KINDS,
    SKIP_STATES,
    CallMetadata,
    FailureKind,
    FreeTierFallbackRouter,
    LLMModelLockProviderFailure,
    LLMNoFreeModelAvailableError,
    ModelState,
    ModelStateCache,
    RouterEvent,
    classify_failure,
    redact,
)
from app.llm.model_pool import (
    ERROR_CODE_ENDPOINT_ACCESS_DENIED,
    ERROR_CODE_FREE_QUOTA_EXHAUSTED,
    BailianModelPool,
    ModelPoolConfigError,
    list_available_models,
    validate_model_pool,
)
from app.llm.provider import (
    LLMApiKeyNotConfiguredError,
    LLMAuthenticationError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    get_llm_provider,
    provider_error_code_of,
)

MESSAGES = [{"role": "user", "content": "统计近30天销售额"}]
FAKE_SECRET = "sk-ws-SUPERSECRET-LEAKCANARY-0123456789"


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class FakeProvider:
    """内存 fake provider：按脚本「返回内容」或「抛指定异常」。"""

    def __init__(self, model_id: str, *, content: str | None = None, error=None):
        self.name = "fake-bailian"
        self._model = model_id
        self._content = content
        self._error = error
        self.calls: list[dict] = []

    @property
    def model(self) -> str:
        return self._model

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        self.calls.append(
            {"messages": messages, "temperature": temperature, "model": self._model}
        )
        if self._error is not None:
            raise self._error
        return self._content if self._content is not None else f"<{self._model}>"


class FakePool:
    """绕过配置校验的池替身，用于直接验证运行期循环保护（§9）。"""

    def __init__(self, models, *, primary=None, model_lock=False):
        self._models = tuple(models)
        self.primary = primary if primary is not None else self._models[0]
        self.model_lock = model_lock

    @property
    def configured_models(self):
        return self._models


# ---------------------------------------------------------------------------
# 异常构造助手（严格模拟 Provider 层产出）
# ---------------------------------------------------------------------------


def _quota_exhausted() -> LLMError:
    """403 + AllocationQuota.FreeTierOnly（Provider 层映射为 LLMAuthenticationError）。"""
    return LLMAuthenticationError(
        "Bailian authentication failed",
        http_status=403,
        provider_error_code=ERROR_CODE_FREE_QUOTA_EXHAUSTED,
    )


def _endpoint_denied() -> LLMError:
    """403 + Endpoint.AccessDenied。"""
    return LLMAuthenticationError(
        "Bailian authentication failed",
        http_status=403,
        provider_error_code=ERROR_CODE_ENDPOINT_ACCESS_DENIED,
    )


def _bare_403() -> LLMError:
    """403 但无可识别 code —— 必须保守 STOP，不得切换。"""
    return LLMAuthenticationError("Bailian authentication failed", http_status=403)


def _auth_401() -> LLMError:
    return LLMAuthenticationError("Bailian authentication failed", http_status=401)


def _rate_limited() -> LLMError:
    return LLMRateLimitError("Bailian rate limited", http_status=429)


def _network() -> LLMError:
    return LLMNetworkError("Bailian network error")


def _timeout() -> LLMError:
    return LLMTimeoutError("Bailian request timeout")


def _server_error() -> LLMError:
    return LLMServiceUnavailableError("Bailian service unavailable", http_status=503)


def _insufficient_balance() -> LLMError:
    return LLMInsufficientBalanceError(
        "Bailian insufficient account balance", http_status=402
    )


def _make_router(script: dict[str, object], pool, **kwargs):
    """按 {model_id: content|Exception} 构造 router，返回 (router, providers, events)。

    ⚠️ provider 按 model_id **复用同一实例**：只有这样才能用 ``provider.calls``
    统计「该模型被调用了几次」。若每次 factory 都新建实例，计数会被重置，
    「同模型不重复调用」「429 不被永久跳过」这类断言就会失去意义。
    """
    providers: dict[str, FakeProvider] = {}
    events: list[RouterEvent] = []

    def factory(model_id: str) -> FakeProvider:
        if model_id in providers:
            return providers[model_id]
        spec = script.get(model_id, f"<{model_id}>")
        if isinstance(spec, BaseException):
            provider = FakeProvider(model_id, error=spec)
        else:
            provider = FakeProvider(model_id, content=str(spec))
        providers[model_id] = provider
        return provider

    router = FreeTierFallbackRouter(
        pool=pool,
        provider_factory=factory,
        on_event=events.append,
        **kwargs,
    )
    return router, providers, events


def _pool(*models, model_lock: bool = False, free_tier_only: bool = True):
    return BailianModelPool(
        primary=models[0],
        fallbacks=tuple(models[1:]),
        free_tier_only=free_tier_only,
        model_lock=model_lock,
    )


# ===========================================================================
# §23-1 primary success
# ===========================================================================


def test_01_primary_success() -> None:
    router, providers, events = _make_router({"A": "SELECT 1;"}, _pool("A", "B", "C"))
    assert router.generate(MESSAGES) == "SELECT 1;"
    assert len(providers["A"].calls) == 1
    assert "B" not in providers and "C" not in providers
    assert events == []


# ===========================================================================
# §23-2 primary exhausted -> fallback success
# ===========================================================================


def test_02_primary_exhausted_falls_back() -> None:
    router, providers, events = _make_router(
        {"A": _quota_exhausted(), "B": "SELECT 2;"}, _pool("A", "B", "C")
    )
    assert router.generate(MESSAGES) == "SELECT 2;"
    assert len(providers["A"].calls) == 1
    assert len(providers["B"].calls) == 1
    assert "C" not in providers
    names = [e.name for e in events]
    assert names == [EVENT_MODEL_EXHAUSTED, EVENT_MODEL_FALLBACK]
    assert events[0].from_model == "A"
    assert events[0].error_code == ERROR_CODE_FREE_QUOTA_EXHAUSTED
    assert events[1].from_model == "A" and events[1].to_model == "B"


# ===========================================================================
# §23-3 primary unavailable -> fallback
# ===========================================================================


def test_03_primary_unavailable_falls_back() -> None:
    router, providers, events = _make_router(
        {"A": _endpoint_denied(), "B": "SELECT 3;"}, _pool("A", "B")
    )
    assert router.generate(MESSAGES) == "SELECT 3;"
    assert [e.name for e in events] == [EVENT_MODEL_UNAVAILABLE, EVENT_MODEL_FALLBACK]
    assert events[0].error_code == ERROR_CODE_ENDPOINT_ACCESS_DENIED
    # 关键反例：UNAVAILABLE 绝不能声称「额度耗尽」
    assert events[0].name != EVENT_MODEL_EXHAUSTED
    assert router.cache.state_of("A") is ModelState.UNAVAILABLE
    assert router.cache.state_of("A") is not ModelState.EXHAUSTED


# ===========================================================================
# §23-4 / §23-5 auth & network -> STOP（绝不换模型）
# ===========================================================================


@pytest.mark.parametrize(
    ("label", "error", "expected_kind"),
    [
        ("401", _auth_401(), FailureKind.AUTHENTICATION),
        ("bare_403", _bare_403(), FailureKind.AUTHENTICATION),
        ("balance_402", _insufficient_balance(), FailureKind.ACCOUNT_LEVEL),
        ("network", _network(), FailureKind.NETWORK),
        ("timeout", _timeout(), FailureKind.NETWORK),
        ("server_503", _server_error(), FailureKind.TRANSIENT),
    ],
)
def test_04_stop_family_never_switches_model(label, error, expected_kind) -> None:
    """认证 / 账户 / 网络 / 5xx：必须 STOP，且不得触碰下一个模型。"""
    router, providers, events = _make_router({"A": error, "B": "SELECT 9;"}, _pool("A", "B"))
    with pytest.raises(LLMError) as excinfo:
        router.generate(MESSAGES)
    assert type(excinfo.value) is type(error), label
    assert "B" not in providers, f"{label} 竟然切换到了 B"
    assert events == [], f"{label} 不应产生任何 fallback 事件"


def test_05_stop_family_classification_is_exact() -> None:
    assert classify_failure(_auth_401()) is FailureKind.AUTHENTICATION
    assert classify_failure(_network()) is FailureKind.NETWORK
    assert classify_failure(_timeout()) is FailureKind.NETWORK
    assert classify_failure(_server_error()) is FailureKind.TRANSIENT
    assert classify_failure(_insufficient_balance()) is FailureKind.ACCOUNT_LEVEL
    assert classify_failure(LLMApiKeyNotConfiguredError("x")) is FailureKind.AUTHENTICATION


def test_05b_no_fallback_eligible_kind_leaks_into_stop_family() -> None:
    """STOP 家族与 FALLBACK 家族必须是互斥集合（防「所有 403 都换模型」）。"""
    stop_kinds = {
        FailureKind.AUTHENTICATION,
        FailureKind.ACCOUNT_LEVEL,
        FailureKind.NETWORK,
        FailureKind.TRANSIENT,
        FailureKind.UNKNOWN,
    }
    assert not (stop_kinds & FALLBACK_ELIGIBLE_KINDS)
    assert FALLBACK_ELIGIBLE_KINDS == {
        FailureKind.FREE_QUOTA_EXHAUSTED,
        FailureKind.MODEL_UNAVAILABLE,
    }


# ===========================================================================
# §23-6 / §25-4 429 -> RATE_LIMITED，不得自动 exhausted
# ===========================================================================


def test_06_rate_limit_is_not_exhaustion() -> None:
    router, providers, events = _make_router({"A": _rate_limited(), "B": "x"}, _pool("A", "B"))
    with pytest.raises(LLMRateLimitError):
        router.generate(MESSAGES)
    assert "B" not in providers, "429 不得直接切换模型"
    assert router.cache.state_of("A") is ModelState.RATE_LIMITED
    assert router.cache.state_of("A") not in SKIP_STATES
    assert events == []


def test_06b_rate_limited_model_is_retried_next_request() -> None:
    """429 之后，下一次 request 仍应尝试该模型（不能被当成 exhausted 跳过）。"""
    router, providers, _ = _make_router(
        {"A": _rate_limited(), "B": "x"}, _pool("A", "B")
    )
    with pytest.raises(LLMRateLimitError):
        router.generate(MESSAGES)
    with pytest.raises(LLMRateLimitError):
        router.generate(MESSAGES)
    assert len(providers["A"].calls) == 2, "429 被错误地永久跳过了"


def test_06c_transient_5xx_is_not_quarantined() -> None:
    router, providers, _ = _make_router({"A": _server_error(), "B": "x"}, _pool("A", "B"))
    for _ in range(2):
        with pytest.raises(LLMServiceUnavailableError):
            router.generate(MESSAGES)
    assert len(providers["A"].calls) == 2, "5xx 被错误地永久 quarantine 了"
    assert router.cache.state_of("A") not in SKIP_STATES


# ===========================================================================
# §23-7 all exhausted -> NO_FREE_MODEL_AVAILABLE
# ===========================================================================


def test_07_all_exhausted_raises_no_free_model_available() -> None:
    router, providers, events = _make_router(
        {"A": _quota_exhausted(), "B": _quota_exhausted(), "C": _quota_exhausted()},
        _pool("A", "B", "C"),
    )
    with pytest.raises(LLMNoFreeModelAvailableError) as excinfo:
        router.generate(MESSAGES)
    exc = excinfo.value
    assert exc.attempted_models == ["A", "B", "C"]
    assert set(exc.model_states) == {"A", "B", "C"}
    assert all(v["state"] == ModelState.EXHAUSTED.value for v in exc.model_states.values())
    assert set(exc.last_errors) == {"A", "B", "C"}
    assert EVENT_NO_FREE_MODEL_AVAILABLE in [e.name for e in events]
    assert exc.to_dict()["error"] == "NO_FREE_MODEL_AVAILABLE"


def test_07b_all_unavailable_mixed_kinds() -> None:
    router, _, _ = _make_router(
        {"A": _quota_exhausted(), "B": _endpoint_denied()}, _pool("A", "B")
    )
    with pytest.raises(LLMNoFreeModelAvailableError) as excinfo:
        router.generate(MESSAGES)
    assert excinfo.value.model_states["A"]["state"] == ModelState.EXHAUSTED.value
    assert excinfo.value.model_states["B"]["state"] == ModelState.UNAVAILABLE.value


def test_07c_empty_pool_raises_immediately() -> None:
    router = FreeTierFallbackRouter(pool=FakePool([], primary=""), provider_factory=lambda m: None)
    with pytest.raises(LLMNoFreeModelAvailableError):
        router.generate(MESSAGES)


# ===========================================================================
# §23-8 duplicate model IDs
# ===========================================================================


def test_08_duplicate_fallback_ids_are_deduped() -> None:
    pool = BailianModelPool(primary="A", fallbacks=("B", "B", "C", "B"))
    assert pool.configured_models == ("A", "B", "C")
    assert pool.size == 3
    pool.validate()  # 不应抛错


def test_08b_primary_duplicated_in_fallbacks_is_config_error() -> None:
    pool = BailianModelPool(primary="A", fallbacks=("A", "B"))
    with pytest.raises(ModelPoolConfigError) as excinfo:
        pool.validate()
    assert "primary model must not appear" in str(excinfo.value)


def test_08c_normalized_removes_duplicates_and_primary_collision() -> None:
    pool = BailianModelPool(primary="A", fallbacks=(" B ", "A", "B", ""))
    normalized = pool.normalized()
    assert normalized.primary == "A"
    assert normalized.fallbacks == ("B",)
    normalized.validate()


# ===========================================================================
# §23-9 same model cannot be retried within one request
# ===========================================================================


def test_09_no_same_model_duplicate_attempt() -> None:
    """池被手工构造出重复项时，运行期也必须每个模型只调一次（§9 循环保护）。"""
    pool = FakePool(["A", "A", "B", "A"])
    router, providers, _ = _make_router(
        {"A": _quota_exhausted(), "B": _quota_exhausted()}, pool
    )
    with pytest.raises(LLMNoFreeModelAvailableError) as excinfo:
        router.generate(MESSAGES)
    assert len(providers["A"].calls) == 1, "A 被重复调用了"
    assert len(providers["B"].calls) == 1
    assert excinfo.value.attempted_models == ["A", "B"]


def test_09b_attempts_never_exceed_pool_size() -> None:
    pool = FakePool(["A", "B", "C"])
    router, providers, _ = _make_router(
        {m: _quota_exhausted() for m in ("A", "B", "C")}, pool
    )
    with pytest.raises(LLMNoFreeModelAvailableError):
        router.generate(MESSAGES)
    total = sum(len(p.calls) for p in providers.values())
    assert total == 3 == len(pool.configured_models)


# ===========================================================================
# §23-10 / §23-13 fallback metadata
# ===========================================================================


def test_10_fallback_metadata() -> None:
    router, _, _ = _make_router(
        {"A": _quota_exhausted(), "B": "SELECT 2;"}, _pool("A", "B", "C")
    )
    result = router.generate_with_metadata(MESSAGES)
    assert result.content == "SELECT 2;"
    assert result.metadata == CallMetadata(
        requested_model="A", actual_model="B", fallback_used=True, fallback_index=1
    )
    assert router.last_call_metadata == result.metadata


def test_13_no_fallback_metadata() -> None:
    router, _, _ = _make_router({"A": "SELECT 1;"}, _pool("A", "B"))
    result = router.generate_with_metadata(MESSAGES)
    assert result.metadata.requested_model == "A"
    assert result.metadata.actual_model == "A"
    assert result.metadata.fallback_used is False
    assert result.metadata.fallback_index == 0
    assert result.metadata.to_dict()["fallback_used"] is False


def test_13b_fallback_index_follows_pool_order_not_attempt_count() -> None:
    """fallback_index = 实际模型在池中的下标（§12 示例：A=0, B=1）。"""
    router, _, _ = _make_router(
        {"A": _quota_exhausted(), "B": _quota_exhausted(), "C": "ok"},
        _pool("A", "B", "C"),
    )
    assert router.generate_with_metadata(MESSAGES).metadata.fallback_index == 2


# ===========================================================================
# §23-11 / §23-12 / §15 MODEL_LOCK
# ===========================================================================


def test_11_lock_mode_never_falls_back_even_on_success_path() -> None:
    pool = _pool("A", "B", "C", model_lock=True)
    assert pool.fallback_router_enabled is False
    router, providers, _ = _make_router({"A": "ok"}, pool)
    assert router.generate(MESSAGES) == "ok"
    assert "B" not in providers and "C" not in providers


def test_12_lock_mode_primary_exhausted_fails_fast() -> None:
    pool = _pool("A", "B", model_lock=True)
    router, providers, events = _make_router({"A": _quota_exhausted(), "B": "x"}, pool)
    with pytest.raises(LLMModelLockProviderFailure) as excinfo:
        router.generate(MESSAGES)
    assert "MODEL_LOCK_PROVIDER_FAILURE" in str(excinfo.value)
    assert "B" not in providers, "锁模式下绝不允许自动切换"
    assert [e.name for e in events] == [EVENT_MODEL_LOCK_PROVIDER_FAILURE]
    assert isinstance(excinfo.value.__cause__, LLMAuthenticationError)


def test_12b_lock_mode_fails_fast_on_every_error_kind() -> None:
    for error in (_auth_401(), _network(), _rate_limited(), _server_error()):
        pool = _pool("A", "B", model_lock=True)
        router, providers, _ = _make_router({"A": error, "B": "x"}, pool)
        with pytest.raises(LLMModelLockProviderFailure):
            router.generate(MESSAGES)
        assert "B" not in providers


def test_12c_lock_mode_never_marks_exhausted_and_never_skips() -> None:
    """锁模式是单模型语义：失败后不得写 EXHAUSTED 缓存（否则污染后续 run）。"""
    pool = _pool("A", "B", model_lock=True)
    router, _, _ = _make_router({"A": _quota_exhausted(), "B": "x"}, pool)
    with pytest.raises(LLMModelLockProviderFailure):
        router.generate(MESSAGES)
    assert router.cache.state_of("A") is ModelState.EXHAUSTED


# ===========================================================================
# §23-14 / §23-15 cache behavior & restart
# ===========================================================================


def test_14_cache_skips_exhausted_on_next_request() -> None:
    router, providers, events = _make_router(
        {"A": _quota_exhausted(), "B": "SELECT 2;"}, _pool("A", "B")
    )
    assert router.generate(MESSAGES) == "SELECT 2;"
    assert len(providers["A"].calls) == 1

    # 第二次 request：A 已被缓存标记 EXHAUSTED，必须直接跳过
    events.clear()
    assert router.generate(MESSAGES) == "SELECT 2;"
    assert len(providers["A"].calls) == 1, "EXHAUSTED 模型被重新尝试了（会退化成 A/B 死循环）"
    assert len(providers["B"].calls) == 2
    # 直接从 B 开始 => 本次没有 fallback 事件（没有发生「切换」）
    assert events == []


def test_14b_cache_prevents_abab_loop() -> None:
    """§6 核心动机：A fail / B fail / A fail / B fail 的无限循环必须被阻断。"""
    router, providers, _ = _make_router(
        {"A": _quota_exhausted(), "B": _quota_exhausted()}, _pool("A", "B")
    )
    with pytest.raises(LLMNoFreeModelAvailableError):
        router.generate(MESSAGES)
    with pytest.raises(LLMNoFreeModelAvailableError):
        router.generate(MESSAGES)
    assert len(providers["A"].calls) == 1
    assert len(providers["B"].calls) == 1


def test_15_process_restart_resets_cache() -> None:
    """应用重启 = 新建 cache（进程内状态），EXHAUSTED 必须被清空。"""
    cache = ModelStateCache()
    cache.mark("A", ModelState.EXHAUSTED, reason="FREE_QUOTA_EXHAUSTED")
    assert cache.is_skipped("A") is True

    restarted = ModelStateCache()  # 模拟新进程
    assert restarted.is_skipped("A") is False
    assert restarted.snapshot() == {}

    # 且「重启」后 router 会重新尝试 A
    providers: dict[str, FakeProvider] = {}

    def factory(model_id: str):
        provider = FakeProvider(model_id, content="ok")
        providers[model_id] = provider
        return provider

    fresh_router = FreeTierFallbackRouter(
        pool=_pool("A", "B"), provider_factory=factory, cache=restarted
    )
    assert fresh_router.generate(MESSAGES) == "ok"
    assert len(providers["A"].calls) == 1


def test_15b_cache_is_never_persisted_to_disk() -> None:
    """§7：缓存绝不落盘 —— 用 AST 检查模块内不存在任何写文件调用。"""
    source_path = (
        Path(__file__).resolve().parents[1] / "app" / "llm" / "fallback_router.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("open", "write_text", "write_bytes", "dump", "dumps", "pickle"):
            offenders.append(f"{source_path.name}:{node.lineno}:{name}")
    assert not offenders, f"缓存疑似落盘: {offenders}"


# ===========================================================================
# §25 错误分类矩阵（403 两类必须分开）
# ===========================================================================


def test_25_error_classification_matrix() -> None:
    assert classify_failure(_quota_exhausted()) is FailureKind.FREE_QUOTA_EXHAUSTED
    assert classify_failure(_endpoint_denied()) is FailureKind.MODEL_UNAVAILABLE
    assert classify_failure(_auth_401()) is FailureKind.AUTHENTICATION
    assert classify_failure(_rate_limited()) is FailureKind.RATE_LIMITED


def test_25b_403_quota_and_endpoint_are_distinguished() -> None:
    """两条错误的 http_status 完全相同（403），只有 code 能区分 —— 这是本任务的核心。"""
    quota, denied = _quota_exhausted(), _endpoint_denied()
    assert quota.http_status == denied.http_status == 403
    assert type(quota) is type(denied) is LLMAuthenticationError
    assert classify_failure(quota) is not classify_failure(denied)


def test_25c_missing_code_on_403_is_conservative_stop() -> None:
    """无可用 code 的 403 必须保守 STOP —— 绝不「所有 403 都换模型」。"""
    assert classify_failure(_bare_403()) is FailureKind.AUTHENTICATION
    assert provider_error_code_of(_bare_403()) is None
    router, providers, _ = _make_router({"A": _bare_403(), "B": "x"}, _pool("A", "B"))
    with pytest.raises(LLMAuthenticationError):
        router.generate(MESSAGES)
    assert "B" not in providers


def test_25d_unrecognized_code_is_not_treated_as_quota_exhaustion() -> None:
    exc = LLMAuthenticationError(
        "x", http_status=403, provider_error_code="Some.Unknown.Code"
    )
    assert classify_failure(exc) is FailureKind.AUTHENTICATION


# ===========================================================================
# §10 错误传播与脱敏
# ===========================================================================


def test_10b_error_payload_has_required_fields() -> None:
    router, _, _ = _make_router(
        {"A": _quota_exhausted(), "B": _endpoint_denied()}, _pool("A", "B")
    )
    with pytest.raises(LLMNoFreeModelAvailableError) as excinfo:
        router.generate(MESSAGES)
    payload = excinfo.value.to_dict()
    for key in ("attempted_models", "model_states", "last_errors"):
        assert key in payload
    assert payload["last_errors"]["A"]["error_type"] == "LLMAuthenticationError"
    assert payload["last_errors"]["A"]["http_status"] == 403
    assert payload["last_errors"]["A"]["provider_error_code"] == (
        ERROR_CODE_FREE_QUOTA_EXHAUSTED
    )


def test_10c_no_secret_leakage_in_error_payload_or_repr() -> None:
    leaky = LLMAuthenticationError(
        f"upstream said: Authorization: Bearer {FAKE_SECRET} (api_key={FAKE_SECRET})",
        http_status=403,
        provider_error_code=ERROR_CODE_FREE_QUOTA_EXHAUSTED,
    )
    # 池内两个模型都失败，才能把 last_errors 载荷逼出来
    router, _, _ = _make_router(
        {"A": leaky, "A2": _quota_exhausted()}, _pool("A", "A2")
    )
    with pytest.raises(LLMNoFreeModelAvailableError) as excinfo:
        router.generate(MESSAGES)
    blob = repr(excinfo.value) + str(excinfo.value) + repr(excinfo.value.to_dict())
    assert FAKE_SECRET not in blob
    assert "Bearer " not in blob
    # 反向自查：确认 message 字段真的被填充（否则上面的断言是空转的假通过）
    summary = excinfo.value.last_errors["A"]["message"]
    assert summary, "last_errors.message 为空 => 脱敏断言形同虚设"
    assert "[REDACTED]" in summary
    assert "upstream said" in summary, "message 应保留可诊断部分，只是凭据被抹掉"


def test_10d_redact_helper() -> None:
    assert FAKE_SECRET not in redact(f"key={FAKE_SECRET}")
    assert "[REDACTED]" in redact(f"key={FAKE_SECRET}")
    assert "Bearer " not in redact(f"Authorization: Bearer {FAKE_SECRET}")
    assert len(redact("x" * 1000)) <= 200


def test_10e_no_secret_leakage_in_logs(caplog) -> None:
    """§21：日志不得出现完整 key / authorization / headers。"""
    router, _, _ = _make_router(
        {"A": _quota_exhausted(), "B": "ok"}, _pool("A", "B")
    )
    with caplog.at_level("INFO", logger="app.llm.fallback"):
        router.generate(MESSAGES)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "LLM_FALLBACK" in text
    assert FAKE_SECRET not in text
    assert "Bearer " not in text
    assert "Authorization" not in text


def test_10f_fallback_log_has_required_fields(caplog) -> None:
    router, _, _ = _make_router({"A": _quota_exhausted(), "B": "ok"}, _pool("A", "B"))
    with caplog.at_level("INFO", logger="app.llm.fallback"):
        router.generate(MESSAGES)
    # getMessage() 已完成 %-格式化，不可再次套用 args
    lines = [record.getMessage() for record in caplog.records]
    fallback_lines = [line for line in lines if line.startswith("LLM_FALLBACK")]
    assert len(fallback_lines) == 1, lines
    for field in ("from_model", "to_model", "reason", "error_code", "fallback_index"):
        assert field in fallback_lines[0], f"日志缺少字段 {field}"


# ===========================================================================
# §26 Fallback 不改变 SQL semantics（纯透传）
# ===========================================================================


def test_26_router_is_pure_passthrough() -> None:
    """Router 只换 actual model；messages / temperature / 返回内容逐字不变。"""
    sql = '{"sql": "SELECT category, SUM(amount) FROM orders GROUP BY category;"}'
    router, providers, _ = _make_router(
        {"A": _quota_exhausted(), "B": sql}, _pool("A", "B")
    )
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}]
    snapshot = [dict(m) for m in messages]

    result = router.generate_with_metadata(messages, temperature=0.0)

    assert result.content == sql
    assert result.metadata.actual_model == "B"
    # 传给 B 的就是调用方给的同一个对象（无重写、无裁剪、无重排）
    assert providers["B"].calls[0]["messages"] is messages
    assert providers["B"].calls[0]["temperature"] == 0.0
    assert messages == snapshot, "Router 修改了 messages"


def test_26b_no_billing_or_extra_params_injected() -> None:
    """§4/§30：Router 绝不注入任何「转付费 / 提额」类参数。"""
    captured: list[dict] = []

    def factory(model_id: str):
        provider = FakeProvider(model_id, content="ok")
        original = provider.generate

        def spy(messages, *, temperature=0.0):
            captured.append({"messages": messages, "temperature": temperature})
            return original(messages, temperature=temperature)

        provider.generate = spy  # type: ignore[method-assign]
        return provider

    router = FreeTierFallbackRouter(pool=_pool("A", "B"), provider_factory=factory)
    router.generate(MESSAGES, temperature=0.3)
    assert captured == [{"messages": MESSAGES, "temperature": 0.3}]


def test_26c_metadata_only_differs_by_model() -> None:
    """同一输入在有 / 无 fallback 下产出完全相同的文本，唯一差异是 actual_model。"""
    payload = "SELECT 1;"
    direct, _, _ = _make_router({"A": payload}, _pool("A", "B"))
    fallen, _, _ = _make_router({"A": _quota_exhausted(), "B": payload}, _pool("A", "B"))

    direct_result = direct.generate_with_metadata(MESSAGES)
    fallen_result = fallen.generate_with_metadata(MESSAGES)

    assert direct_result.content == fallen_result.content
    assert direct_result.metadata.actual_model == "A"
    assert fallen_result.metadata.actual_model == "B"


# ===========================================================================
# §16 lazy fallback（不做预探测）
# ===========================================================================


def test_16_lazy_fallback_no_probe_before_real_request() -> None:
    router, providers, _ = _make_router({"A": "ok", "B": "ok"}, _pool("A", "B"))
    assert providers == {}, "构造 Router 时不应调用任何模型（不做 startup probe）"
    router.generate(MESSAGES)
    assert set(providers) == {"A"}, "成功的 request 不应触碰备用模型"


# ===========================================================================
# §19 配置校验
# ===========================================================================


def test_19_empty_primary_is_config_error() -> None:
    with pytest.raises(ModelPoolConfigError):
        BailianModelPool(primary="", fallbacks=()).validate()
    with pytest.raises(ModelPoolConfigError):
        BailianModelPool(primary="   ", fallbacks=("A",)).validate()


def test_19b_validate_model_pool_makes_zero_real_calls() -> None:
    report = validate_model_pool(_pool("A", "B"))
    assert report.ok is True
    assert report.real_llm_calls == 0
    assert report.models == ("A", "B")

    report_probe = validate_model_pool(_pool("A", "B"), probe=True)
    assert report_probe.real_llm_calls == 0
    assert any("probe" in note for note in report_probe.notes)


def test_19c_validate_model_pool_reports_invalid_config() -> None:
    report = validate_model_pool(BailianModelPool(primary="", fallbacks=()))
    assert report.ok is False
    assert report.notes


def test_19d_list_available_models_does_not_claim_quota() -> None:
    """§18：「模型存在」绝不等于「还有免费额度」。"""
    listed = list_available_models(_pool("A", "B"))
    assert [item["model_id"] for item in listed] == ["A", "B"]
    assert listed[0]["is_primary"] is True
    assert all(item["quota_status"] == "UNKNOWN_AT_CONFIG_TIME" for item in listed)


def test_19e_from_env_priority_and_defaults(monkeypatch) -> None:
    monkeypatch.setattr(config, "BAILIAN_PRIMARY_MODEL", "cfg-primary")
    monkeypatch.setattr(config, "BAILIAN_FALLBACK_MODELS", ("cfg-fb",))
    monkeypatch.setattr(config, "LLM_MODEL_LOCK", False)
    monkeypatch.setattr(config, "BAILIAN_FREE_TIER_ONLY", True)

    from_env = BailianModelPool.from_env(
        {"BAILIAN_PRIMARY_MODEL": "env-primary", "BAILIAN_FALLBACK_MODELS": "b, c"}
    )
    assert from_env.primary == "env-primary"
    assert from_env.fallbacks == ("b", "c")
    assert from_env.model_lock is False

    fallback_to_config = BailianModelPool.from_env({})
    assert fallback_to_config.primary == "cfg-primary"
    assert fallback_to_config.fallbacks == ("cfg-fb",)


# ===========================================================================
# §29 向后兼容：单模型模式行为逐项不变
# ===========================================================================


def test_29_primary_only_pool_is_single_model_mode() -> None:
    pool = BailianModelPool(primary="solo", fallbacks=())
    pool.validate()
    assert pool.size == 1
    assert pool.fallback_router_enabled is False

    router, providers, _ = _make_router({"solo": "ok"}, pool)
    assert router.generate(MESSAGES) == "ok"
    assert len(providers["solo"].calls) == 1


def test_29b_factory_returns_raw_provider_when_fallback_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "bailian")
    monkeypatch.setattr(config, "BAILIAN_FALLBACK_MODELS", ())
    monkeypatch.setattr(config, "LLM_MODEL_LOCK", True)
    assert isinstance(get_llm_provider(), BailianProvider)


def test_29c_factory_returns_router_when_fallback_enabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "bailian")
    monkeypatch.setattr(config, "BAILIAN_PRIMARY_MODEL", "m-a")
    monkeypatch.setattr(config, "BAILIAN_FALLBACK_MODELS", ("m-b", "m-c"))
    monkeypatch.setattr(config, "LLM_MODEL_LOCK", False)
    provider = get_llm_provider()
    assert isinstance(provider, FreeTierFallbackRouter)
    assert provider.model == "m-a"
    assert provider.pool.configured_models == ("m-a", "m-b", "m-c")


def test_29d_lock_mode_never_returns_router(monkeypatch) -> None:
    """正式 benchmark 结构性保证：锁模式下永远拿不到 Router。"""
    monkeypatch.setattr(config, "LLM_PROVIDER", "bailian")
    monkeypatch.setattr(config, "BAILIAN_PRIMARY_MODEL", "m-a")
    monkeypatch.setattr(config, "BAILIAN_FALLBACK_MODELS", ("m-b",))
    monkeypatch.setattr(config, "LLM_MODEL_LOCK", True)
    provider = get_llm_provider()
    assert not isinstance(provider, FreeTierFallbackRouter)
    assert isinstance(provider, BailianProvider)
    # 锁模式固定 primary，且该模型就是唯一被调用的模型
    assert provider.model == "m-a"


def test_29e_factory_still_mimo_by_default(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "mimo")
    from app.llm.mimo import MimoProvider

    assert isinstance(get_llm_provider(), MimoProvider)


# ===========================================================================
# 协议一致性 / Router 自身形状
# ===========================================================================


def test_router_satisfies_llm_provider_shape() -> None:
    import inspect

    router, _, _ = _make_router({"A": "ok"}, _pool("A"))
    assert isinstance(router.name, str)
    assert isinstance(router.model, str)
    assert callable(router.generate)
    sig = inspect.signature(router.generate)
    assert list(sig.parameters) == ["messages", "temperature"]
    assert sig.parameters["temperature"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["temperature"].default == 0.0


def test_sticky_skip_states_are_not_downgraded() -> None:
    cache = ModelStateCache()
    cache.mark("A", ModelState.EXHAUSTED, reason="FREE_QUOTA_EXHAUSTED")
    cache.mark("A", ModelState.RATE_LIMITED, reason="RATE_LIMITED")
    assert cache.state_of("A") is ModelState.EXHAUSTED
    assert cache.is_skipped("A") is True


def test_cache_snapshot_is_structured() -> None:
    cache = ModelStateCache()
    cache.mark("A", ModelState.EXHAUSTED, reason="FREE_QUOTA_EXHAUSTED", error_code="X")
    snapshot = cache.snapshot()
    assert snapshot["A"]["state"] == "EXHAUSTED"
    assert snapshot["A"]["error_code"] == "X"
    assert snapshot["A"]["hits"] == 1
