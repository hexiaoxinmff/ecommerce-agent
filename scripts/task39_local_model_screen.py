#!/usr/bin/env python
"""Task 39-L：本地候选模型「可调用性」筛选（provider 顺序，不按强弱排名）。

协议
----
用冻结 benchmark 第 1 题（E-0001）的**真实流水线 prompt** 试跑，模型必须
完成 Schema Linking 且产出通过流水线输出契约校验的 SQL，否则判定为
「对本流水线不可调用」，继续下一个候选。

该脚本只做**能力筛选**，不做模型强弱排名 —— 顺序始终是 provider 自身
``/api/tags`` 的返回顺序。

上下文说明
----------
Ollama 会按显存给默认 ``num_ctx``（本机 6 GiB → 4096）。**thinking 模型
的推理链会把窗口吃光**，导致答案无处输出。因此筛选必须在**充足上下文**
（``OLLAMA_CONTEXT_LENGTH``，建议 ≥8192）下进行，否则会得到假阴性。

用法::

    OLLAMA_HOST=127.0.0.1:11435 OLLAMA_MODELS=F:/Ollama_old/models \\
    OLLAMA_NOPRUNE=1 OLLAMA_CONTEXT_LENGTH=8192 ollama serve

    .venv/Scripts/python.exe scripts/task39_local_model_screen.py \\
        --base-url http://127.0.0.1:11435/v1 --out reports/task39_local_screen.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.llm.local_provider import (  # noqa: E402
    LocalProvider,
    is_embedding_model,
    list_models,
)
from scripts.task39_local_benchmark import (  # noqa: E402
    LocalAgentRunner,
    build_local_components,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Task 39-L candidate model screen")
    p.add_argument("--base-url", default="http://127.0.0.1:11435/v1")
    p.add_argument("--out", default=str(PROJECT_ROOT / "reports" / "task39_local_screen.json"))
    args = p.parse_args(argv)

    items = json.loads(
        (PROJECT_ROOT / "data" / "eval" / "ecommerce_eval_v1.json").read_text(encoding="utf-8")
    )["items"]
    item = items[0]
    print(f"screen item: {item['id']} | {item['question']}", flush=True)

    ids = list_models(args.base_url, timeout=10.0)
    candidates = [m for m in ids if not is_embedding_model(m)]
    print(f"candidates (provider order): {candidates}\n", flush=True)

    rows: list[dict] = []
    selected: str | None = None
    for model in candidates:
        provider = LocalProvider(base_url=args.base_url, model=model)
        runner = LocalAgentRunner(provider, build_local_components(provider))
        start = time.perf_counter()
        try:
            result = runner(item["question"])
            elapsed = (time.perf_counter() - start) * 1000
            sql = (result.generated_sql or "").strip()
            err = result.error_type or ""
            ok = bool(sql) and not err
            row = {
                "model": model, "callable": ok, "e2e_ms": round(elapsed),
                "provider_calls": provider.stats.calls, "sql_len": len(sql),
                "error_type": err, "final_error": str(result.final_error or "")[:160],
                "exec_success": bool(result.success),
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - start) * 1000
            row = {
                "model": model, "callable": False, "e2e_ms": round(elapsed),
                "provider_calls": provider.stats.calls, "sql_len": 0,
                "error_type": type(exc).__name__, "final_error": str(exc)[:160],
                "exec_success": False,
            }
        rows.append(row)
        print(
            f"[{'PASS' if row['callable'] else 'FAIL'}] {model:24} "
            f"e2e={row['e2e_ms']:8}ms calls={row['provider_calls']} "
            f"sql_len={row['sql_len']} err={row['error_type'] or '-'} "
            f"final={row['final_error'][:80]}",
            flush=True,
        )
        if row["callable"] and selected is None:
            selected = model
            print(f"\nFIRST CALLABLE CANDIDATE: {model}", flush=True)
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "screen_item": item["id"],
                "screen_protocol": "真实流水线 prompt 试跑；必须完成 Schema Linking 且产出通过输出契约的 SQL",
                "candidates_provider_order": candidates,
                "results": rows,
                "first_callable": selected,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
