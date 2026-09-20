"""真实 Mimo SQL Generator 验证脚本（不进入默认 pytest）。

用法（在项目根目录）：
    python scripts/test_sql_generator.py

链路：Question -> Schema Linking -> Few-shot Retrieval -> Mimo -> SQL Generation
      -> SQL Safety Validation（**不执行生成 SQL**）。

输出：Question / Schema Tables / Few-shot IDs / Generated SQL / Explanation /
Validation Result。禁止输出 API Key。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core import config  # noqa: E402
from app.sqlgen.generator import SQLGenerator  # noqa: E402

QUESTION_FORMATS = [
    "近30天销售额最高的商品有哪些？",
    "哪个地区的用户最多？",
    "哪个商品类别销售额最高？",
]


def main() -> int:
    print("=" * 70)
    print("Mimo 真实 SQL Generation 验证（只生成与校验，不执行 SQL）")
    print(f"LLM_PROVIDER : {config.LLM_PROVIDER}")
    print(f"MIMO_BASE_URL : {config.MIMO_BASE_URL or '(未设置)'}")
    print(f"MIMO_MODEL    : {config.MIMO_MODEL or '(未设置)'}")
    print(f"MIMO_API_KEY  : {'已设置(不显示内容)' if config.MIMO_API_KEY else '(未设置)'}")
    print("=" * 70)

    if not config.MIMO_API_KEY:
        print("Mimo API key is not configured")
        return 1

    generator = SQLGenerator()
    all_ok = True
    for question in QUESTION_FORMATS:
        print("-" * 70)
        print(f"Question: {question}")
        try:
            result = generator.generate(question)
            print(f"Schema Tables: {result.tables}")
            print(f"Few-shot IDs: {result.fewshot_examples}")
            print(f"Generated SQL: {result.sql}")
            print(f"Explanation: {result.explanation}")
            print(f"Validation Result: PASS")
        except Exception as exc:
            print(f"Validation Result: FAIL -> {type(exc).__name__}: {exc}")
            all_ok = False

    print("=" * 70)
    print(f"SQL Generation（真实 Mimo）：{'成功' if all_ok else '存在失败'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())