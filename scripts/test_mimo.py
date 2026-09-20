"""Mimo 真实 API 连接测试脚本（不进入默认 pytest）。

用法（在项目根目录）：
    python scripts/test_mimo.py

要求：
- 先通过环境变量或项目根 .env 配置 MIMO_API_KEY / MIMO_BASE_URL / MIMO_MODEL；
- 脚本只输出 provider / model / 响应时间 / 模型返回内容，绝不输出 API Key。

退出码：全部测试成功为 0，任一失败为 1。
"""

import sys
import time
from pathlib import Path

# 使脚本能导入 backend 下的 app 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core import config  # noqa: E402
from app.llm.provider import LLMError, get_llm_provider  # noqa: E402

TEST_PROMPTS = [
    "请用一句话说明你是什么模型。",
    "请用一句话说明“电商数据分析 Agent”可以做什么。",
]

SYSTEM_PROMPT = (
    "你是电商智能数据分析 Agent 的语言模型组件。"
    "当前仅用于验证模型连接。"
    "不要执行 SQL，不访问数据库，不假设已经连接数据库。"
    "请准确、简洁地回答用户输入。"
)


def call_once(provider, prompt: str) -> tuple[bool, str, float]:
    """单次真实调用，返回 (是否成功, 内容或错误文案, 耗时毫秒)。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    start = time.perf_counter()
    try:
        content = provider.generate(messages, temperature=0.0)
        return True, content, (time.perf_counter() - start) * 1000
    except LLMError as exc:
        return False, f"{type(exc).__name__}: {exc}", (time.perf_counter() - start) * 1000


def main() -> int:
    print("=" * 60)
    print("Mimo 真实 API 连接测试")
    print(f"LLM_PROVIDER : {config.LLM_PROVIDER}")
    print(f"MIMO_BASE_URL : {config.MIMO_BASE_URL or '(未设置)'}")
    print(f"MIMO_MODEL    : {config.MIMO_MODEL or '(未设置)'}")
    print(f"MIMO_TIMEOUT  : {config.MIMO_TIMEOUT}s")
    print(f"MIMO_API_KEY  : {'已设置(不显示内容)' if config.MIMO_API_KEY else '(未设置)'}")
    print("=" * 60)

    try:
        provider = get_llm_provider()
    except LLMError as exc:
        print(f"Mimo API：失败\n原因：{exc}")
        return 1

    print(f"Provider：{provider.name}")
    print(f"Model：{provider.model or '(未设置)'}")

    all_ok = True
    for index, prompt in enumerate(TEST_PROMPTS, start=1):
        ok, content, elapsed_ms = call_once(provider, prompt)
        print("-" * 60)
        print(f"[{index}] Prompt：{prompt}")
        print(f"    结果：{'成功' if ok else '失败'}")
        print(f"    Response Time：{elapsed_ms:.0f} ms")
        print(f"    内容：{content}")
        if not ok:
            all_ok = False

    print("=" * 60)
    print(f"Mimo API：{'成功' if all_ok else '失败'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())