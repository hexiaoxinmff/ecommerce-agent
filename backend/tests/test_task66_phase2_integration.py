# -*- coding: utf-8 -*-
"""Task66 Phase 2 §13 —— Router 集成式测试（integration-style）。

与 Phase 1 单元测试的分工
-------------------------
Phase 1 的 ``test_task66_fallback_router.py`` 逐个验证分类 / 状态机 / 缓存 /
日志等**单元**行为。本文件只做一件事，把 §13 点名的端到端链路钉在一处：

    primary  -> 403 + AllocationQuota.FreeTierOnly
    Router   -> 切换到 fallback
    fallback -> success

并断言：

* ``actual_model == fallback``
* ``fallback_used is True``
* ``fallback_index == 1``
* **primary 只被调用一次**（不会二次重试同一个已耗尽模型）

为什么单独成文件而不是塞进 Phase 1 的测试文件
----------------------------------------------
Phase 1 交付目录 ``F:\\task66_bailian_model_fallback\\test_fallback_router.py``
的 sha256 已被记录为 ``3a264ae2cd58f934``。原地追加会让该交付副本与仓库源
不再逐字节一致，破坏"交付物可复核"。新开文件两全。

本文件**不做任何真实网络调用**：两个 provider 都是内存替身。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.llm.fallback_router import (  # noqa: E402
    EVENT_MODEL_EXHAUSTED,
    EVENT_MODEL_FALLBACK,
    ERROR_CODE_FREE_QUOTA_EXHAUSTED,
    FreeTierFallbackRouter,
)
from app.llm.model_pool import BailianModelPool  # noqa: E402
from app.llm.provider import LLMAuthenticationError  # noqa: E402

PRIMARY = "primary-model"
FALLBACK = "fallback-model"

MESSAGES = [
    {"role": "system", "content": "You are a Text2SQL assistant."},
    {"role": "user", "content": "列出订单表的全部列。"},
]

# 故意用「真实生产形态」的异常：403 + 结构化 code，而不是自定义异常类。
# 若 provider 层未来丢掉 provider_error_code，本测试必须变红。
_EXHAUSTED = LLMAuthenticationError(
    "Bailian authentication failed",
    http_status=403,
    provider_error_code=ERROR_CODE_FREE_QUOTA_EXHAUSTED,
)


class _RecordingProvider:
    """内存替身：记录每次调用，按需返回内容或抛异常。"""

    def __init__(self, model: str, *, content: str = "", error: BaseException | None = None):
        self.model = model
        self._content = content
        self._error = error
        self.calls: list[dict] = []

    def generate(self, messages, *, temperature: float = 0.0) -> str:
        self.calls.append({"messages": messages, "temperature": temperature})
        if self._error is not None:
            raise self._error
        return self._content


@pytest.fixture()
def rig():
    """构造 §13 链路：primary 耗尽 + fallback 成功。"""
    providers = {
        PRIMARY: _RecordingProvider(PRIMARY, error=_EXHAUSTED),
        FALLBACK: _RecordingProvider(FALLBACK, content="OK"),
    }
    events: list = []
    pool = BailianModelPool(
        primary=PRIMARY,
        fallbacks=(FALLBACK,),
        free_tier_only=True,
        model_lock=False,
    )
    pool.validate()
    router = FreeTierFallbackRouter(
        pool=pool,
        provider_factory=lambda model_id: providers[model_id],
        on_event=events.append,
    )
    return router, providers, events


def test_phase2_router_switches_from_exhausted_primary_to_live_fallback(rig) -> None:
    """§13 主断言：mock primary 耗尽 -> fallback 成功，metadata 三项齐全。"""
    router, providers, _ = rig

    result = router.generate_with_metadata(MESSAGES, temperature=0.0)

    assert result.content == "OK"
    assert result.metadata.actual_model == FALLBACK
    assert result.metadata.fallback_used is True
    assert result.metadata.fallback_index == 1
    assert result.metadata.requested_model == PRIMARY
    # 经 to_dict() 的线上形态也必须一致（防止序列化层丢掉字段）
    as_dict = result.metadata.to_dict()
    assert as_dict["actual_model"] == FALLBACK
    assert as_dict["fallback_used"] is True
    assert as_dict["fallback_index"] == 1


def test_phase2_primary_is_never_retried_after_quota_exhaustion(rig) -> None:
    """§13 循环保护断言：已耗尽的 primary 绝不被第二次调用。"""
    router, providers, _ = rig

    router.generate_with_metadata(MESSAGES)

    assert len(providers[PRIMARY].calls) == 1, "primary 被重复调用了"
    assert len(providers[FALLBACK].calls) == 1


def test_phase2_event_sequence_is_exhausted_then_fallback(rig) -> None:
    """事件序列与错误码必须可对账（§21 监控事件）。"""
    router, _, events = rig

    router.generate_with_metadata(MESSAGES)

    assert [e.name for e in events] == [EVENT_MODEL_EXHAUSTED, EVENT_MODEL_FALLBACK]
    assert events[0].error_code == ERROR_CODE_FREE_QUOTA_EXHAUSTED
    assert events[1].from_model == PRIMARY
    assert events[1].to_model == FALLBACK
    assert events[1].fallback_index == 1


def test_phase2_cache_skips_primary_on_second_request(rig) -> None:
    """跨 request：第二次请求应直接命中缓存跳过 primary（不再触碰网络）。"""
    router, providers, _ = rig

    router.generate_with_metadata(MESSAGES)
    second = router.generate_with_metadata(MESSAGES)

    assert len(providers[PRIMARY].calls) == 1, "缓存未阻止 primary 的二次调用"
    assert second.metadata.actual_model == FALLBACK
    assert second.metadata.fallback_used is True


def test_phase2_messages_are_passed_through_unchanged(rig) -> None:
    """§26：Router 不改写 question / schema / prompt，只换 actual model。"""
    router, providers, _ = rig
    snapshot = [dict(m) for m in MESSAGES]

    router.generate_with_metadata(MESSAGES)

    assert MESSAGES == snapshot
    # 传给 fallback 的就是调用方给的那个对象本身
    assert providers[FALLBACK].calls[0]["messages"] is MESSAGES
