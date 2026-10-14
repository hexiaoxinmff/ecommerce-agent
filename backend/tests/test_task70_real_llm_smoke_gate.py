"""Task 70 — `RUN_REAL_LLM_SMOKE` 显式 Opt-in 闸门的边界测试。

任务书 §四 要求覆盖四种组合：

====  ====================  ===================  ==========================
      RUN_REAL_LLM_SMOKE    DASHSCOPE_API_KEY    期望
====  ====================  ===================  ==========================
A     未设置                存在                 SKIP，0 网络
B     未设置                不存在               SKIP，0 网络
C     1                     存在                 允许真实 smoke
D     1                     不存在               不得真实请求；SKIP / 明确配置失败
====  ====================  ===================  ==========================

本文件是**结构契约**（in-repo，默认 pytest 就会跑到），
保证「默认不联网」不再是一次观测，而是一条每次跑测试都会被验的规则。

其中「真实 SKIP + 0 网络」的**端到端实测**（子进程 + socket 闸门）在
`<task70>/subprocess_switch_matrix.py`（仓库外，见报告 §五）。
这里做的是**判定表 + 结构判据**，不 spawn 子进程，保持快。

⚠️ 本文件绝不读取 / 回显任何真实凭据：只用 `"sk-fake-*"` 这类假值。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import real_llm_smoke_gate as gate

SMOKE_TEST_FILE = Path(__file__).with_name("test_bailian_provider.py")
GATE_MODULE_FILE = Path(__file__).with_name("real_llm_smoke_gate.py")
SMOKE_TEST_NAME = "test_real_bailian_smoke"

FAKE_KEY = "sk-fake-task70-not-a-real-credential"


# ---------------------------------------------------------------------------
# §四 A / B：开关未设置 ⇒ 一律 SKIP（无论有没有 key）
# ---------------------------------------------------------------------------
def test_A_key_present_flag_unset_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A. key 存在 + 开关未设置 ⇒ DISABLED（0 网络）。"""
    monkeypatch.setenv(gate.KEY_ENV, FAKE_KEY)
    monkeypatch.delenv(gate.ENV_FLAG, raising=False)

    enabled, reason = gate.evaluate()

    assert enabled is False, "有 key 也不能自动联网 —— 开关才是唯一入口"
    assert reason.startswith(gate.REASON_DISABLED), reason
    # 反向自查：确认"key 确实存在"，否则这条测试就是空转
    assert gate.key_present() is True, "场景没搭好：key 并未存在"


def test_B_key_absent_flag_unset_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """B. key 不存在 + 开关未设置 ⇒ DISABLED（0 网络）。"""
    monkeypatch.delenv(gate.KEY_ENV, raising=False)
    monkeypatch.delenv(gate.ENV_FLAG, raising=False)

    enabled, reason = gate.evaluate()

    assert enabled is False
    assert reason.startswith(gate.REASON_DISABLED), reason
    assert gate.key_present() is False, "场景没搭好：key 仍然存在"


# ---------------------------------------------------------------------------
# §四 C：两个条件都满足 ⇒ 才允许真实调用
# ---------------------------------------------------------------------------
def test_C_flag_on_and_key_present_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """C. 开关=1 + key 存在 ⇒ ENABLED。"""
    monkeypatch.setenv(gate.ENV_FLAG, gate.OPEN_VALUE)
    monkeypatch.setenv(gate.KEY_ENV, FAKE_KEY)

    enabled, reason = gate.evaluate()

    assert enabled is True, reason
    assert "enabled" in reason


# ---------------------------------------------------------------------------
# §四 D：开了开关但没 key ⇒ 不得真实请求
# ---------------------------------------------------------------------------
def test_D_flag_on_without_key_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """D. 开关=1 + key 不存在 ⇒ DISABLED，且 reason 说明是 key 缺失。"""
    monkeypatch.setenv(gate.ENV_FLAG, gate.OPEN_VALUE)
    monkeypatch.delenv(gate.KEY_ENV, raising=False)

    enabled, reason = gate.evaluate()

    assert enabled is False, "没有凭据时绝不允许真实请求"
    assert gate.REASON_DISABLED not in reason, "这不是'开关没开'，不该套用默认文案"
    assert gate.KEY_ENV in reason, "reason 必须指明是哪个变量缺失"


# ---------------------------------------------------------------------------
# 只有字面 "1" 才算打开 —— 防止 "true"/"yes"/"on" 造成"看起来开了"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["0", "true", "True", "yes", "on", "2", "", " ", "1 ", " 1"],
)
def test_only_literal_one_opens_the_gate(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """除 ``"1"`` 以外的取值（含 ``"1 "``）一律视为未打开。"""
    monkeypatch.setenv(gate.ENV_FLAG, value)
    monkeypatch.setenv(gate.KEY_ENV, FAKE_KEY)

    enabled, _ = gate.evaluate()

    expected = value.strip() == gate.OPEN_VALUE
    assert enabled is expected, f"RUN_REAL_LLM_SMOKE={value!r} 的判定不符合预期"


# ---------------------------------------------------------------------------
# 「有没有 key」永远不能单独决定联网
# ---------------------------------------------------------------------------
def test_key_alone_never_opens_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """单独存在 key（开关完全缺席）⇒ 必须 DISABLED。"""
    monkeypatch.setenv(gate.KEY_ENV, FAKE_KEY)
    monkeypatch.delenv(gate.ENV_FLAG, raising=False)

    assert gate.key_present() is True  # 反向自查
    assert gate.evaluate()[0] is False


# ---------------------------------------------------------------------------
# 环境真实性：本机 .env 确实配着 key，而闸门依然关闭
# ---------------------------------------------------------------------------
def test_ambient_env_key_does_not_open_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实环境（`.env` 已配 key、开关未设置）⇒ 依然 DISABLED。"""
    monkeypatch.delenv(gate.ENV_FLAG, raising=False)

    if not gate.key_present():
        pytest.skip(
            "ambient 环境未配置凭据；该断言只在'本来会联网'的环境里才有意义"
        )

    enabled, reason = gate.evaluate()
    assert enabled is False, "生产 .env 里有 key ⇒ 这正是本任务要消灭的自动联网路径"
    assert gate.REASON_DISABLED in reason


# ---------------------------------------------------------------------------
# 不回显凭据
# ---------------------------------------------------------------------------
def test_reason_never_echoes_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """reason 只写"存在与否"，绝不写 key 的值。"""
    monkeypatch.setenv(gate.KEY_ENV, FAKE_KEY)

    for flag in ("", "0", gate.OPEN_VALUE):
        monkeypatch.setenv(gate.ENV_FLAG, flag)
        _, reason = gate.evaluate()
        assert FAKE_KEY not in reason, f"reason 泄漏了 key 值：{reason!r}"
        assert "sk-fake" not in reason


# ---------------------------------------------------------------------------
# 结构判据：真实冒烟测试的 skip 条件必须来自闸门，而不是"有没有 key"
# ---------------------------------------------------------------------------
def _skipif_condition_source(func_name: str) -> str:
    """从源码里取出该测试 `@pytest.mark.skipif(<cond>, ...)` 的条件表达式。"""
    tree = ast.parse(SMOKE_TEST_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                # @pytest.mark.skipif(...)  =>  dec.func 是 Attribute(attr="skipif")
                if getattr(dec.func, "attr", None) != "skipif":
                    continue
                if not dec.args:
                    raise AssertionError(f"{func_name} 的 skipif 没有条件参数")
                return ast.unparse(dec.args[0])
            raise AssertionError(f"{func_name} 缺少 skipif 装饰器")
    raise AssertionError(f"源码里找不到 {func_name}")


def test_smoke_test_still_exists_and_is_not_permanently_skipped() -> None:
    """禁止用「删除测试 / 永久 skip」来变绿（任务书 §七）。"""
    src = SMOKE_TEST_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)

    funcs = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
    }
    assert SMOKE_TEST_NAME in funcs, "真实冒烟测试被删掉了"

    markers = [
        ast.unparse(d) for d in funcs[SMOKE_TEST_NAME].decorator_list
    ]
    joined = " ".join(markers)
    assert "skipif" in joined, "必须保留 skipif（条件式跳过），不能无条件跳过"
    assert "pytest.mark.skip(" not in joined.replace(" ", ""), (
        "不得改成永久 skip"
    )


def test_skip_condition_derives_from_gate_not_from_the_key() -> None:
    """skip 条件不得读取 `DASHSCOPE_API_KEY`（那正是旧 bug 的判据）。"""
    cond = _skipif_condition_source(SMOKE_TEST_NAME)

    assert gate.KEY_ENV not in cond, (
        f"skip 条件仍在读凭据环境变量：{cond!r} —— "
        "这会让'有 key'等价于'自动联网'"
    )
    assert "getenv" not in cond, f"skip 条件不应直接读环境：{cond!r}"
    assert "_REAL_SMOKE_ENABLED" in cond, (
        f"skip 条件必须由闸门结果驱动：{cond!r}"
    )


def test_smoke_gate_is_actually_wired_into_the_test_module() -> None:
    """闸门必须真的被调用过（不是 import 了摆着看）。"""
    src = SMOKE_TEST_FILE.read_text(encoding="utf-8")

    assert "from tests.real_llm_smoke_gate import evaluate" in src
    assert "_REAL_SMOKE_ENABLED, _REAL_SMOKE_REASON = _real_llm_smoke_gate()" in src


def test_gate_module_is_pure_stdlib_and_imports_no_app_code() -> None:
    """闸门模块不得 import 应用代码 —— 否则它自己就可能触发 load_dotenv / 网络。"""
    tree = ast.parse(GATE_MODULE_FILE.read_text(encoding="utf-8"))

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    # `__future__` 是编译器指令而非运行时依赖，不算第三方/应用依赖。
    allowed = {"os", "__future__"}
    assert set(imported) <= allowed, (
        f"闸门模块只应 import {sorted(allowed)}，实际：{imported}"
    )
    assert not any(m.startswith("app") for m in imported)
