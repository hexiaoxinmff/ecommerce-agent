# -*- coding: utf-8 -*-
"""Phase 5：百炼模型最小真实调用验证（Key 只从 config/.env/环境变量读取，绝不打印）。

逐个验证候选模型：qwen3.7-flash / qwen3.7-flash-2026-07-15
记录：Key 有效性、Endpoint 可达性、模型可调用性、文本返回能力。
失败时如实打印异常类型 + http_status + provider_error_code。
"""
import sys
import time

sys.path.insert(0, r"F:\基于 Text2SQL 的电商智能数据分析 Agent\backend")

from app.core import config  # noqa: E402
from app.llm.bailian import BailianProvider  # noqa: E402
from app.llm import provider as pv  # noqa: E402

CANDIDATES = ["qwen3.7-flash", "qwen3.7-flash-2026-07-15"]

MESSAGES = [
    {"role": "system", "content": "你是连通性测试组件，只回复 OK。"},
    {"role": "user", "content": "只回复 OK"},
]


def main() -> None:
    key_present = bool(config.DASHSCOPE_API_KEY)
    print(f"DASHSCOPE_API_KEY present: {key_present}")
    print(f"BAILIAN_BASE_URL: {config.BAILIAN_BASE_URL}")
    print(f"config defaults: BAILIAN_MODEL={config.BAILIAN_MODEL!r} "
          f"PRIMARY={config.BAILIAN_PRIMARY_MODEL!r} LOCK={config.LLM_MODEL_LOCK} "
          f"FALLBACKS={config.BAILIAN_FALLBACK_MODELS!r} FREE_TIER_ONLY={config.BAILIAN_FREE_TIER_ONLY}")
    if not key_present:
        print("VERDICT: no key configured — cannot validate")
        return

    for model in CANDIDATES:
        print(f"\n=== probe model: {model} ===")
        prov = BailianProvider(model=model)
        start = time.perf_counter()
        try:
            content = prov.generate(MESSAGES, temperature=0.0)
            dt = (time.perf_counter() - start) * 1000
            text = (content or "").strip()
            print(f"RESULT: SUCCESS latency_ms={dt:.0f} content_len={len(text)} content={text[:60]!r}")
            print("VERDICT: callable")
        except pv.LLMError as exc:
            dt = (time.perf_counter() - start) * 1000
            code = pv.provider_error_code_of(exc)
            print(f"RESULT: FAIL latency_ms={dt:.0f} type={type(exc).__name__} "
                  f"http_status={getattr(exc, 'http_status', None)} provider_error_code={code!r} "
                  f"msg={exc}")
            print("VERDICT: not callable (see classification above)")
        except Exception as exc:  # noqa: BLE001 — 探针兜底，如实记录
            dt = (time.perf_counter() - start) * 1000
            print(f"RESULT: FAIL latency_ms={dt:.0f} unexpected={type(exc).__name__}: {exc}")
            print("VERDICT: not callable (unexpected)")


if __name__ == "__main__":
    main()
