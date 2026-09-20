"""真实 Mimo Schema Linking 验证脚本（不进入默认 pytest）。

用法（在项目根目录）：
    python scripts/test_schema_linking.py

要求：先通过 .env / 环境变量配置 MIMO_API_KEY 等（本任务真实验证用）。
输出：Question / Linked Tables / Linked Columns / Confidence / Result。
禁止输出 API Key。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core import config  # noqa: E402
from app.llm.provider import LLMError  # noqa: E402
from app.schema.linker import SchemaLinker  # noqa: E402
from app.schema.validation import SchemaLinkingError  # noqa: E402

QUESTIONS = [
    "近30天销售额最高的商品有哪些？",
    "哪个地区的用户最多？",
    "哪个商品类别销售额最高？",
]


def main() -> int:
    print("=" * 70)
    print("Mimo 真实 Schema Linking 验证")
    print(f"LLM_PROVIDER : {config.LLM_PROVIDER}")
    print(f"MIMO_BASE_URL : {config.MIMO_BASE_URL or '(未设置)'}")
    print(f"MIMO_MODEL    : {config.MIMO_MODEL or '(未设置)'}")
    print(f"MIMO_API_KEY  : {'已设置(不显示内容)' if config.MIMO_API_KEY else '(未设置)'}")
    print("=" * 70)

    if not config.MIMO_API_KEY:
        print("Mimo API key is not configured")
        return 1

    try:
        linker = SchemaLinker()
    except LLMError as exc:
        print(f"创建 Provider 失败：{exc}")
        return 1

    all_ok = True
    for question in QUESTIONS:
        print("-" * 70)
        print(f"Question: {question}")
        try:
            result = linker.link(question)
            print(f"Linked Tables: {result.tables}")
            print(f"Linked Columns: {result.columns}")
            print(f"Confidence: {result.confidence}")
            print(
                "Result: "
                + json.dumps(
                    {
                        "tables": result.tables,
                        "columns": result.columns,
                        "reasons": result.reasons,
                        "confidence": result.confidence,
                    },
                    ensure_ascii=False,
                )
            )
        except SchemaLinkingError as exc:
            print(f"Result: Schema Linking 失败：{exc}")
            all_ok = False
        except LLMError as exc:
            print(f"Result: LLM 调用失败：{exc}")
            all_ok = False

    print("=" * 70)
    print(f"Schema Linking（真实 Mimo）：{'成功' if all_ok else '存在失败'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())