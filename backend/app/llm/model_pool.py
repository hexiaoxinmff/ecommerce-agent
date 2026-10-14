"""百炼免费模型池配置（Task66）。

职责边界：本模块**只负责「配置了什么候选模型」**，不负责「调用谁」，
也不负责「当前谁还有免费额度」。

核心主张（Task66 §34）：代码里**绝不写死**「当前哪些模型免费」。
百炼不同模型 / 不同快照的免费额度相互独立、且随新周期恢复，
属于运行时 / 控制台状态，不能固化成常量。本模块保存的只是
「运维显式配置的候选序列」。

配置来源优先级（§3）：
    1. 环境变量（含项目根 .env，由 app.core.config 统一加载，真实环境变量优先）
    2. config 模块取值
    3. 代码默认值（最后兜底）

对应配置项（§28）：
    BAILIAN_PRIMARY_MODEL   主模型，默认回落既有 BAILIAN_MODEL
    BAILIAN_FALLBACK_MODELS 备用模型池，逗号分隔、显式有序，默认空
    LLM_MODEL_LOCK          默认 true —— 固定单模型，禁止自动切换
    BAILIAN_FREE_TIER_ONLY  默认 true —— 只允许免费优先模型，绝不转付费

安全性（§4 / §30）：本模块不提供任何「关闭 free-tier-only」「自动转付费」
「充值」「购买资源包」的入口 —— 免费额度用尽时唯一合法结果是明确停止
（NO_FREE_MODEL_AVAILABLE），而不是换个付费路径继续。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.core import config
from app.llm.provider import LLMError

# ---------------------------------------------------------------------------
# 已知的上游结构化错误码（百炼 OpenAI 兼容模式）
# ---------------------------------------------------------------------------

# 403 + 该 code = 当前模型免费额度已用尽且启用「用完即停」。
# 这是**唯一**允许把模型标记为 EXHAUSTED 的依据（§2A / §5）。
ERROR_CODE_FREE_QUOTA_EXHAUSTED = "AllocationQuota.FreeTierOnly"

# 403 + 该 code = endpoint / 模型不可用（模型下线等）。
# 可标记 UNAVAILABLE 并尝试下一个，但**不得**声称免费额度耗尽（§2B）。
ERROR_CODE_ENDPOINT_ACCESS_DENIED = "Endpoint.AccessDenied"


class ModelPoolConfigError(LLMError):
    """模型池配置非法（§19）。"""


@dataclass(frozen=True)
class BailianModelPool:
    """显式有序的百炼候选模型池。

    不可变值对象：构造即确定，运行期不因任何错误而自我改写
    （「当前谁被跳过」属于 Router 的进程内状态缓存，不写回配置）。
    """

    primary: str
    fallbacks: tuple[str, ...] = ()
    free_tier_only: bool = True
    model_lock: bool = False

    # ---------------- 派生属性 ----------------

    @property
    def configured_models(self) -> tuple[str, ...]:
        """去重后的候选序列，顺序 = primary → fallback_1 → fallback_2 → ...（§20）。

        去重是防御性的：即便调用方绕过 validate() 构造出含重复项的池，
        运行时也只会看到每个 model 一次。
        """
        seen: set[str] = set()
        ordered: list[str] = []
        for model_id in (self.primary, *self.fallbacks):
            if model_id and model_id not in seen:
                seen.add(model_id)
                ordered.append(model_id)
        return tuple(ordered)

    @property
    def size(self) -> int:
        """去重后的候选模型数量，即单次 request 的最大尝试次数上限（§9）。"""
        return len(self.configured_models)

    @property
    def fallback_router_enabled(self) -> bool:
        """是否需要 Fallback Router。

        仅当「未锁定模型」且「候选多于一个」时为真。
        默认配置（model_lock=True 或 fallbacks 为空）恒为假 =>
        行为等价于既有单模型模式（§29）。
        """
        return (not self.model_lock) and self.size > 1

    # ---------------- 校验 ----------------

    def validate(self) -> None:
        """配置自检（§19）。任何一条不满足即抛 ModelPoolConfigError。

        - primary 必须非空；
        - fallbacks 内部重复项可被去重（不报错）；
        - primary **不得**出现在 fallbacks 中（否则等于重试同一模型）；
        - 全部为空属配置错误。
        """
        if not self.primary.strip():
            raise ModelPoolConfigError(
                "model pool config error: BAILIAN_PRIMARY_MODEL is empty"
            )
        if not self.configured_models:
            raise ModelPoolConfigError(
                "model pool config error: no model configured "
                "(BAILIAN_PRIMARY_MODEL and BAILIAN_FALLBACK_MODELS are both empty)"
            )
        primary = self.primary.strip()
        duplicates_of_primary = sorted(
            {m.strip() for m in self.fallbacks if m.strip() == primary}
        )
        if duplicates_of_primary:
            raise ModelPoolConfigError(
                "model pool config error: primary model must not appear in "
                f"BAILIAN_FALLBACK_MODELS ({primary})"
            )

    def normalized(self) -> BailianModelPool:
        """返回「已去重、已 strip」的等价池；不改变语义，仅消除重复项。"""
        seen: set[str] = set()
        cleaned: list[str] = []
        for model_id in self.fallbacks:
            model_id = model_id.strip()
            if model_id and model_id not in seen:
                seen.add(model_id)
                cleaned.append(model_id)
        primary = self.primary.strip()
        if primary:
            seen.add(primary)
        return BailianModelPool(
            primary=primary,
            fallbacks=tuple(m for m in cleaned if m != primary),
            free_tier_only=self.free_tier_only,
            model_lock=self.model_lock,
        )

    # ---------------- 构造 ----------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> BailianModelPool:
        """按 §3 优先级构造模型池。

        env 为 None 时读取 ``app.core.config``（它已实现
        「真实环境变量 > .env > 代码默认值」的优先级）；
        传入显式映射时，映射中的键优先，缺项回落 config。
        显式传入 env 主要用于测试注入，不改变生产路径。
        """
        source: Mapping[str, str] = os.environ if env is None else env

        def _resolve(name: str, fallback: str) -> str:
            raw = source.get(name)
            if raw is None or not str(raw).strip():
                return fallback
            return str(raw).strip()

        primary = _resolve("BAILIAN_PRIMARY_MODEL", config.BAILIAN_PRIMARY_MODEL)

        raw_fallbacks = source.get("BAILIAN_FALLBACK_MODELS")
        if raw_fallbacks is None or not str(raw_fallbacks).strip():
            fallbacks: Iterable[str] = config.BAILIAN_FALLBACK_MODELS
        else:
            fallbacks = str(raw_fallbacks).split(",")

        cleaned: list[str] = []
        for item in fallbacks:
            item = str(item).strip()
            if item and item not in cleaned:
                cleaned.append(item)

        free_tier_only = _resolve_bool(
            source, "BAILIAN_FREE_TIER_ONLY", config.BAILIAN_FREE_TIER_ONLY
        )
        model_lock = _resolve_bool(source, "LLM_MODEL_LOCK", config.LLM_MODEL_LOCK)

        return cls(
            primary=primary,
            fallbacks=tuple(cleaned),
            free_tier_only=free_tier_only,
            model_lock=model_lock,
        )


def _resolve_bool(source: Mapping[str, str], name: str, fallback: bool) -> bool:
    """解析布尔配置；键不存在或为空时回落 fallback。"""
    raw = source.get(name)
    if raw is None or not str(raw).strip():
        return fallback
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# 启动期校验 / 模型列表（§17 / §18）
# ---------------------------------------------------------------------------


@dataclass
class ModelPoolValidationReport:
    """``validate_model_pool()`` 的结构化结果（便于落盘与断言）。"""

    ok: bool
    primary: str
    fallbacks: tuple[str, ...]
    models: tuple[str, ...]
    free_tier_only: bool
    model_lock: bool
    fallback_router_enabled: bool
    real_llm_calls: int = 0
    notes: list[str] = field(default_factory=list)


def validate_model_pool(
    pool: BailianModelPool | None = None,
    *,
    probe: bool = False,
) -> ModelPoolValidationReport:
    """启动期配置校验（§17）。

    ⚠️ 默认 ``probe=False`` 即 **REAL_API_CALLS=0**：只检查配置、model ID 形态
    与 endpoint 取值，**不发起任何真实 LLM 调用**，因此不会消耗免费额度。
    本实现刻意不提供「探测额度」的能力 —— §16 要求 lazy fallback，
    探测本身就是浪费额度的反模式。

    Args:
        pool: 待校验模型池；None 时按 from_env() 构造。
        probe: 保留参数。任何取值都不会触发真实调用；置 True 只会在
            notes 中记一条「probe 被忽略」说明，避免调用方误以为探测发生了。
    """
    pool = pool if pool is not None else BailianModelPool.from_env()
    notes: list[str] = []
    if probe:
        notes.append(
            "probe=True 被忽略：本实现不做真实额度探测（§16 lazy fallback），"
            "REAL_API_CALLS 恒为 0"
        )

    try:
        pool.validate()
        ok = True
    except ModelPoolConfigError as exc:
        ok = False
        notes.append(str(exc))

    if not pool.free_tier_only:
        notes.append(
            "BAILIAN_FREE_TIER_ONLY=false：允许使用非免费优先模型，"
            "存在产生付费调用的风险（本任务默认应为 true）"
        )

    return ModelPoolValidationReport(
        ok=ok,
        primary=pool.primary,
        fallbacks=pool.fallbacks,
        models=pool.configured_models,
        free_tier_only=pool.free_tier_only,
        model_lock=pool.model_lock,
        fallback_router_enabled=pool.fallback_router_enabled,
        real_llm_calls=0,
        notes=notes,
    )


def list_available_models(pool: BailianModelPool | None = None) -> list[dict]:
    """列出**已配置**的候选模型及其顺序（§18）。

    ⚠️ 只返回配置事实，**绝不代表**「模型存在」「模型可调用」「还有免费额度」。
    百炼模型列表接口只提供可用模型信息；免费额度必须单独判断，
    且属运行时状态。本函数刻意不发任何网络请求（REAL_API_CALLS=0）。

    返回项字段：
        model_id / order / is_primary / free_tier_eligible
        quota_status = "UNKNOWN_AT_CONFIG_TIME"
    """
    pool = pool if pool is not None else BailianModelPool.from_env()
    out: list[dict] = []
    for index, model_id in enumerate(pool.configured_models):
        out.append(
            {
                "model_id": model_id,
                "order": index,
                "is_primary": index == 0,
                "free_tier_eligible": pool.free_tier_only,
                "quota_status": "UNKNOWN_AT_CONFIG_TIME",
            }
        )
    return out
