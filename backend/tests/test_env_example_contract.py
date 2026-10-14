"""环境变量示例文件的契约（第十阶段 P0-4 / §九）。

任务书 §九 要求 `.env.example` 必须说明 `LLM_PROVIDER` / `BAILIAN_MODEL` /
`DASHSCOPE_API_KEY` 以及前端 API Base URL，并且**不允许把真实 Key 写进仓库**。

这两条都容易"写了就算完成"，所以这里把第二条做成**值级扫描**：

⚠️ 用**值级正则 + 长度下限**，而不是找 `KEY` / `SECRET` 这类标记子串。
按铁律 22，用标记子串扫描必然自指假阳性 —— 本文件与 `.env.example` 里
到处都是 `DASHSCOPE_API_KEY` 这种**变量名**，它们不是密钥。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
FRONTEND_ENV_EXAMPLE = PROJECT_ROOT / "frontend" / ".env.example"

# 文档承诺必须出现的键
REQUIRED_BACKEND_KEYS = (
    "LLM_PROVIDER",
    "DASHSCOPE_API_KEY",
    "BAILIAN_MODEL",
    "BAILIAN_API_BASE",
    "LLM_MODEL_LOCK",
    "CORS_ORIGINS",
    "AUTH_SESSION_TTL_SECONDS",
    "ECOMMERCE_DB_PATH",
    "APP_DB_PATH",
)
REQUIRED_FRONTEND_KEYS = ("VITE_API_BASE_URL",)

# 值级密钥形态（长度下限刻意留足，避免把 "true"/"30" 这类短值误判）
SECRET_VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("OpenAI 风格 sk- 密钥", r"sk-[A-Za-z0-9_\-]{16,}"),
    ("阿里云 AccessKey", r"LTAI[A-Za-z0-9]{12,}"),
    ("JWT", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."),
    ("32+ 位无分隔长串", r"(?<![A-Za-z0-9_\-])[A-Za-z0-9]{32,}(?![A-Za-z0-9_\-])"),
)
# 赋值行：KEY 类变量必须留空
ASSIGNMENT_RE = re.compile(r"^\s*([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)\s*=\s*(.*)$")


def _active_lines(text: str) -> list[str]:
    """去掉注释行（`#` 开头）后的有效配置行。"""
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _scan_secret_values(text: str) -> list[str]:
    """返回形如 `位置: 形态` 的命中清单。"""
    hits: list[str] = []
    for label, pattern in SECRET_VALUE_PATTERNS:
        for match in re.finditer(pattern, text):
            hits.append(f"{label}: {match.group(0)[:8]}…")
    for line in _active_lines(text):
        assignment = ASSIGNMENT_RE.match(line)
        if assignment and assignment.group(2).strip():
            hits.append(f"{assignment.group(1)} 有非空取值")
    return hits


# ---------- 必需键 ----------


@pytest.mark.parametrize("key", REQUIRED_BACKEND_KEYS)
def test_backend_env_example_documents(key: str) -> None:
    assert BACKEND_ENV_EXAMPLE.is_file(), ".env.example 不存在"
    text = BACKEND_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(rf"^\s*#?\s*{key}\s*=", text, re.MULTILINE), (
        f".env.example 未说明 {key}"
    )


@pytest.mark.parametrize("key", REQUIRED_FRONTEND_KEYS)
def test_frontend_env_example_documents(key: str) -> None:
    assert FRONTEND_ENV_EXAMPLE.is_file(), "frontend/.env.example 不存在"
    text = FRONTEND_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(rf"^\s*{key}\s*=", text, re.MULTILINE), (
        f"frontend/.env.example 未说明 {key}"
    )


# ---------- 不得含真实密钥 ----------


def test_env_example_contains_no_real_secret() -> None:
    for path in (BACKEND_ENV_EXAMPLE, FRONTEND_ENV_EXAMPLE):
        hits = _scan_secret_values(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} 疑似含真实密钥：{hits}"


def test_secret_scanner_is_not_a_no_op() -> None:
    """反向自查：喂一个已知假密钥，扫描器必须报出来（铁律 15 / 44）。

    样本在**运行期拼装**：本文件自身在扫描范围内（若被纳入），
    写成完整字面量会造成自指假阳性。
    """
    fake_prefix = "sk" + "-"
    planted = f"DASHSCOPE_API_KEY={fake_prefix}{'a1b2c3d4' * 4}\n"
    hits = _scan_secret_values(planted)
    assert hits, "扫描器对已知假密钥无反应 ⇒ 判据失效"

    # "键名出现但值为空"必须放行（这正是 .env.example 的形态）
    assert _scan_secret_values("DASHSCOPE_API_KEY=\n") == []

    # ⚠️ 但**注释掉的真实密钥仍然必须被抓到**：注释不会让它变得不泄漏。
    #    形态扫描覆盖全文（含注释），只有"KEY= 必须留空"这一条忽略注释行。
    commented = f"# DASHSCOPE_API_KEY={fake_prefix}{'a1b2c3d4' * 4}\n"
    assert _scan_secret_values(commented), "注释里的真实密钥未被抓到 ⇒ 存在泄漏盲区"


def test_real_env_is_not_tracked_by_git() -> None:
    """.env 里可能真有密钥 ⇒ 必须确认它没有被 Git 跟踪。"""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("本机没有 git，跳过跟踪状态检查")

    assert result.returncode != 0, ".env 被 Git 跟踪了 —— 真实密钥可能已进入版本历史"


def test_gitignore_covers_env_files() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    active = [
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert ".env" in active, ".gitignore 未忽略 .env"
