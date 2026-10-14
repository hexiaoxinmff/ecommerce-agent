"""Benchmark Runner 配置契约（Task72）。

把 **formal benchmark** 从「依赖环境约定」升级为「runner 强制执行的实验契约」，
阻断 Task71 暴露的两条逃逸路径：

* ``scripts/run_eval.py`` 对 provider / model / model-lock / fallback **零强制**；
* 报告的 ``meta.model`` 读的是 ``config.MIMO_MODEL``（**MIMO** 键），
  与真实调用的 **Bailian** 键完全不相干 ⇒ 产物与模型之间没有可信绑定。

本模块是 **benchmark runner 专属**的契约层：只做「校验 + 快照」，**不修改任何
生产代码**（``app.llm.provider`` / ``Router`` / Agent 一律不动），也不发任何网络请求
（只构造 provider 对象 / 读 config，不触发真实调用）。

正式 benchmark 契约（全部必须显式满足，否则 **FAIL FAST**）：

* ``LLM_PROVIDER == "bailian"``         —— 不允许 provider 缺失后静默回到 mimo；
* ``BAILIAN_PRIMARY_MODEL`` 非空         —— 契约声明的固定 model（唯一权威来源）；
* ``BAILIAN_FALLBACK_MODELS`` 为空       —— 正式 benchmark 不允许 fallback 池；
* ``LLM_MODEL_LOCK == True``             —— 一次 run 固定单模型；
* 解析到的实际 provider 是**裸 BailianProvider**（Router 不出现）；
* 解析到的实际 model **等于** ``BAILIAN_PRIMARY_MODEL``
  （回归 Task71 头号陷阱：只设 primary、而有效模型落在别的键上会被静默忽略）。

只要任意一条不满足 ⇒ ``BENCHMARK_PREFLIGHT=FAIL``，runner 立即停止，禁止进入真实
generation loop。所有缺失 / 冲突配置一律 FAIL FAST，**不自动纠正**，
**不从 runtime fallback 配置猜测 benchmark 配置**。

``meta.provider / meta.model`` 必须取自本模块解析出的 **实际 provider / model**。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core import config


class BenchmarkContractError(Exception):
    """Benchmark 配置契约未满足（preflight FAIL，禁止进入 generation loop）。"""

    def __init__(self, failures: list[str]) -> None:
        self.failures = list(failures)
        super().__init__("; ".join(self.failures))


#: formal benchmark 唯一允许的显式 provider。
BENCHMARK_PROVIDER = "bailian"
_BAILIAN_NAME = "bailian"
#: Router 类名（fallback router 出现即违反「Router 禁入 benchmark」）。
_ROUTER_CLASS_NAMES = ("FreeTierFallbackRouter",)


@dataclass(frozen=True)
class BenchmarkSnapshot:
    """preflight 通过后，runner 用于写入报告 meta 的实际 provider/model 快照。"""

    provider: str
    model: str
    base_url: str
    provider_class: str
    router_in_path: bool
    declared_provider: str
    declared_model: str
    declared_fallbacks: tuple[str, ...]
    model_lock: bool
    free_tier_only: bool
    failures: list[str] = field(default_factory=list)

    @property
    def preflight(self) -> str:
        return "PASS" if not self.failures else "FAIL"


def snapshot_runtime() -> BenchmarkSnapshot:
    """解析**实际生效**的 provider / model（0 网络）。

    通过 ``app.llm.provider.get_llm_provider()`` 得到真实分派后的 provider 对象，
    并读取其 ``name`` / ``model`` —— 这是 runner 写入 meta 的**唯一**权威来源，
    与生产 Agent / Router 共用同一条分派路径。
    """
    from app.llm.model_pool import BailianModelPool
    from app.llm.provider import get_llm_provider

    pool = BailianModelPool.from_env()
    provider = get_llm_provider()
    provider_class = type(provider).__name__
    provider_name = str(getattr(provider, "name", "") or "")
    resolved_model = str(getattr(provider, "model", "") or "")

    return BenchmarkSnapshot(
        provider=provider_name,
        model=resolved_model,
        base_url=config.BAILIAN_BASE_URL if provider_name == _BAILIAN_NAME
        else (config.MIMO_BASE_URL or ""),
        provider_class=provider_class,
        router_in_path=provider_class in _ROUTER_CLASS_NAMES,
        declared_provider=config.LLM_PROVIDER,
        declared_model=config.BAILIAN_PRIMARY_MODEL,
        declared_fallbacks=tuple(config.BAILIAN_FALLBACK_MODELS),
        model_lock=bool(config.LLM_MODEL_LOCK),
        free_tier_only=bool(config.BAILIAN_FREE_TIER_ONLY),
    )


def enforce_benchmark_contract() -> BenchmarkSnapshot:
    """校验并执行 formal benchmark 配置契约。

    Returns: 通过校验的 BenchmarkSnapshot（供 meta 使用）。
    Raises: BenchmarkContractError —— 任一契约条目不满足（FAIL FAST）。
    """
    import os as _os

    snap = snapshot_runtime()

    # ⚠️ 契约的「声明值」必须读**原始环境变量**，不能读 config 的回落值：
    # config.BAILIAN_PRIMARY_MODEL 在未显式配置时会回落到 BAILIAN_MODEL（Task71
    # 的 primary 被静默忽略），若读它，只设 BAILIAN_MODEL 的旧兼容配置就永远查不出来。
    raw_provider = _os.environ.get("LLM_PROVIDER", "").strip().lower()
    raw_model = _os.environ.get("BAILIAN_PRIMARY_MODEL", "").strip()
    raw_lock = _os.environ.get("LLM_MODEL_LOCK", "").strip().lower()
    lock_explicit_true = raw_lock != "" and raw_lock in ("1", "true", "yes", "on")

    failures: list[str] = []

    # 1) provider 必须显式为 benchmark provider（禁止静默回到 mimo）。
    if raw_provider != BENCHMARK_PROVIDER:
        failures.append(
            f"LLM_PROVIDER must be exactly '{BENCHMARK_PROVIDER}' "
            f"(got {raw_provider or '<unset>'!r}); no silent fallback to mimo allowed"
        )

    # 2) 契约 model 键 BAILIAN_PRIMARY_MODEL 必须显式非空
    #    （只配 BAILIAN_MODEL 的旧兼容字段一律拒绝）。
    if not raw_model:
        failures.append(
            "BAILIAN_PRIMARY_MODEL must be explicitly set (non-empty); "
            "setting only BAILIAN_MODEL is NOT accepted as the benchmark contract"
        )

    # 3) formal benchmark 不允许 fallback 池。
    if snap.declared_fallbacks:
        failures.append(
            f"BAILIAN_FALLBACK_MODELS must be empty for a formal benchmark "
            f"(got {snap.declared_fallbacks!r})"
        )

    # 4) 正式 benchmark 强制单模型锁（必须显式 true）。
    if not lock_explicit_true:
        failures.append(
            "LLM_MODEL_LOCK must be explicitly true for a formal benchmark "
            "(missing or lock=false rejected)"
        )

    # 5) 实际分派得到的 provider 必须是裸 BailianProvider（Router 禁入路径）。
    is_router = snap.router_in_path
    bare_bailian = (
        snap.provider == _BAILIAN_NAME
        and snap.provider_class == "BailianProvider"
        and not is_router
    )
    if not bare_bailian:
        if is_router:
            failures.append(
                f"fallback Router ({snap.provider_class}) must not appear in a "
                f"formal benchmark"
            )
        else:
            failures.append(
                f"resolved provider is not a bare 'BailianProvider' "
                f"(got {snap.provider!r} / {snap.provider_class})"
            )

    # 6) 实际 model 必须等于契约声明的 model（回归 Task71：primary 被静默忽略）。
    if raw_model and snap.model and snap.model != raw_model:
        failures.append(
            f"resolved model {snap.model!r} != declared benchmark model "
            f"{raw_model!r}; refusing to run on an unstated model"
        )

    if failures:
        raise BenchmarkContractError(failures)

    return BenchmarkSnapshot(
        provider=snap.provider, model=snap.model, base_url=snap.base_url,
        provider_class=snap.provider_class, router_in_path=snap.router_in_path,
        declared_provider=snap.declared_provider,
        declared_model=snap.declared_model,
        declared_fallbacks=snap.declared_fallbacks,
        model_lock=snap.model_lock, free_tier_only=snap.free_tier_only,
        failures=failures,
    )