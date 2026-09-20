"""最小环境检查脚本。

只负责检查开发环境的各项基础能力，输出 PASS / FAIL：
- Python 版本
- FastAPI 是否可 import
- LangGraph 是否可 import
- sqlglot 是否可 import
- OpenAI SDK 是否可 import
- pytest 是否可运行
- SQLite 是否可用

本脚本不调用任何 LLM API、不创建业务数据库、不执行 SQL、
不启动 FastAPI 服务、不创建 Agent。
"""

import importlib
import importlib.metadata
import sqlite3
import subprocess
import sys

REQUIRED_PYTHON = (3, 12)


def check_python() -> tuple[bool, str]:
    version = sys.version_info
    ok = version >= REQUIRED_PYTHON
    detail = f"{version.major}.{version.minor}.{version.micro}"
    return ok, detail


def import_check(module: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(module)
        version = getattr(mod, "__version__", None)
        if version is None:
            # 部分包（如 langgraph）未定义 __version__，回退到安装元数据
            version = importlib.metadata.version(module)
    except Exception as exc:  # noqa: BLE001 - 检查脚本需要捕获任意导入错误
        return False, f"import 失败: {exc}"
    return True, f"{version}"


def pytest_check() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"pytest 运行失败: {exc}"
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0 or "pytest" not in output:
        return False, output or "pytest 不可用"
    return True, output.splitlines()[0]


def sqlite_check() -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(":memory:")
        version = sqlite3.sqlite_version
        conn.close()
    except Exception:  # noqa: BLE001
        return False, "SQLite 不可用"
    return True, version


def main() -> None:
    checks = [
        ("Python", check_python()),
        ("FastAPI", import_check("fastapi")),
        ("LangGraph", import_check("langgraph")),
        ("sqlglot", import_check("sqlglot")),
        ("OpenAI SDK", import_check("openai")),
        ("pytest", pytest_check()),
        ("SQLite", sqlite_check()),
    ]

    all_ok = True
    for name, (ok, detail) in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"[{status}] {name}: {detail}")

    print()
    if all_ok:
        print("全部检查项通过。")
        sys.exit(0)
    print("存在未通过的检查项，请修复后重新运行。", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()