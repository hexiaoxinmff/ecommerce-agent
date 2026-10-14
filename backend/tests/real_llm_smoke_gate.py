"""Task 70 — 真实 LLM 冒烟测试的**显式 Opt-in 闸门**（测试侧代码，非生产代码）。

背景
----
此前 `test_real_bailian_smoke` 的跳过条件是::

    skipif(not os.getenv("DASHSCOPE_API_KEY", "").strip(), ...)

而生产 `.env` 里**一直**配着 `DASHSCOPE_API_KEY`，`load_dotenv` 又会把它写进
`os.environ` ⇒ **任何人跑一次全量 pytest 都会真发一次外部 API 请求**。
于是「默认测试 0 网络」只是**一次观测**，不是**结构性事实**；
实际使用中只能靠人工 `DASHSCOPE_API_KEY="" ... --deselect ...` 绕开。

本模块把该语义**反过来**：默认 DISABLED，只有**显式** opt-in 才可能联网。

判定表
------
====================  ===================  ==========================
RUN_REAL_LLM_SMOKE    DASHSCOPE_API_KEY    结果
====================  ===================  ==========================
未设置 / 非 "1"        有                   DISABLED（skip）
未设置 / 非 "1"        无                   DISABLED（skip）
"1"                   有                   ENABLED（可真实调用）
"1"                   无                   DISABLED（skip，reason 说明 key 缺失）
====================  ===================  ==========================

两条不可动摇的规则
------------------
1. **联网的唯一开关是 `RUN_REAL_LLM_SMOKE=1`**。
   「有没有 key」**只**用于在已 opt-in 之后决定*能不能真的跑*，
   **绝不**用于决定*是否要联网* —— 否则 `.env` 里放个 key 就又变成自动联网了。
2. **绝不回显 key 的值**。本模块只暴露 `key_present()`（布尔），
   reason 里也只写"存在与否"，不写任何前缀 / 片段 / 长度。

用法::

    from tests.real_llm_smoke_gate import evaluate as _smoke_gate

    _SMOKE_ENABLED, _SMOKE_REASON = _smoke_gate()

    @pytest.mark.skipif(not _SMOKE_ENABLED, reason=_SMOKE_REASON)
    def test_real_bailian_smoke() -> None: ...
"""

from __future__ import annotations

import os

#: 唯一的联网开关。只有**恰好**等于 :data:`OPEN_VALUE` 才算打开。
ENV_FLAG = "RUN_REAL_LLM_SMOKE"

#: 凭据环境变量。**不参与**"是否联网"的判定，只参与"能不能真跑"。
KEY_ENV = "DASHSCOPE_API_KEY"

#: 视为"打开"的字面值。刻意只认 `"1"`：
#: `"true"` / `"yes"` / `"on"` 一律不算，避免"看起来像打开了"的歧义。
OPEN_VALUE = "1"

#: 默认关闭时的 skip reason 前缀（任务书 §三 指定的措辞，逐字保留）。
REASON_DISABLED = "real LLM smoke disabled; set RUN_REAL_LLM_SMOKE=1"


def flag_raw() -> str:
    """返回开关的原始取值（未设置时为空串）。"""
    return os.getenv(ENV_FLAG, "")


def flag_enabled() -> bool:
    """开关是否**显式**打开（恰好等于 ``"1"``）。"""
    return flag_raw().strip() == OPEN_VALUE


def key_present() -> bool:
    """凭据是否存在（**只回布尔，不回值**）。"""
    return bool(os.getenv(KEY_ENV, "").strip())


def evaluate() -> tuple[bool, str]:
    """返回 ``(enabled, reason)``。

    ``enabled=True`` 才允许真实网络调用。
    ``reason`` 在两个分支下都可诊断（分别指明是"开关没开"还是"key 缺失"）。
    """
    if not flag_enabled():
        raw = flag_raw().strip()
        shown = repr(raw) if raw else "<unset>"
        return False, (
            f"{REASON_DISABLED} "
            f"(current {ENV_FLAG}={shown}; {KEY_ENV} present={key_present()})"
        )

    if not key_present():
        return False, (
            f"{ENV_FLAG}={OPEN_VALUE} but {KEY_ENV} is not set; "
            "refusing to attempt a real API call"
        )

    return True, (
        f"{ENV_FLAG}={OPEN_VALUE} and {KEY_ENV} present; real LLM smoke enabled"
    )


__all__ = [
    "ENV_FLAG",
    "KEY_ENV",
    "OPEN_VALUE",
    "REASON_DISABLED",
    "evaluate",
    "flag_enabled",
    "flag_raw",
    "key_present",
]
