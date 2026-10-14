"""端点唯一事实源守卫（第十阶段 P0-2 / P0-4）。

为什么需要这个文件：第十阶段之前，"后端有几个端点"这一个事实被 4 份文档各自
维护，于是必然漂移 —— 实测 `README.md` 写 16、`docs/TEST_REPORT.md` 写 16、
`docs/project-parameters.md` §3.3 手写 10 行表、`docs/DEPLOYMENT.md` 没有，
而代码里实际是 **18**。没有任何测试会因为这种不一致变红。

本文件把"文档 == 代码"变成会响的警报，四道：

1. `sync(check=True)` —— 权威文件与 marker 区块必须与生成结果逐字节一致；
2. 端点总数必须等于显式常量（新增路由而不改常量 → 红）；
3. 文档里声明的 auth 要求必须与**真实 HTTP 行为**一致（无 token 打过去真的 401）；
4. 当前材料里不得残留陈旧口径（历史快照章节除外）。

第 3 条是关键：如果只比文档与文档，`auth=True` 也可能集体撒谎。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import export_api_endpoints as gen  # noqa: E402

from app.main import app  # noqa: E402


# ---------- 1. 派生物与事实源一致 ----------


def test_all_derived_docs_match_generator() -> None:
    """权威文件 + 5 份文档的 marker 区块必须与生成结果一致（不写盘）。"""
    ok, messages = gen.sync(check=True)
    assert ok, "端点清单漂移：\n" + "\n".join(messages)


def test_canonical_files_exist_and_are_marked_generated() -> None:
    for path in (gen.CANONICAL_MD, gen.CANONICAL_JSON):
        assert path.exists(), f"{path} 缺失（请运行 scripts/export_api_endpoints.py）"
    assert "自动生成" in gen.CANONICAL_MD.read_text(encoding="utf-8")


# ---------- 2. 总数是显式常量 ----------


def test_endpoint_count_matches_declared_constant() -> None:
    data = gen.manifest()
    assert data["endpoint_count"] == gen.EXPECTED_ENDPOINT_COUNT, (
        f"实际 {data['endpoint_count']} 个端点，常量声明 "
        f"{gen.EXPECTED_ENDPOINT_COUNT} 个；若是有意新增路由，请一并更新常量与文档"
    )


def test_router_count_is_twelve() -> None:
    """router 数也是口径的一部分（旧文档写 11，实际 12）。"""
    assert gen.manifest()["router_count"] == 12


# ---------- 3. 文档声明的 auth 必须与真实 HTTP 行为一致 ----------


def _concrete_path(path: str) -> str:
    """把 `/api/history/{history_id}` 里的路径参数替换成具体值。"""
    return re.sub(r"\{[^}]+\}", "1", path)


def _call_without_token(client: TestClient, method: str, path: str):
    url = _concrete_path(path)
    if method == "POST":
        return client.post(url, json={})
    if method == "DELETE":
        return client.delete(url)
    return client.get(url)


def _audit_auth_declarations(client: TestClient, endpoints) -> list[str]:
    """把"文档说需要鉴权"与"真的返回 401"逐条对账，返回不一致清单。

    抽成函数是为了让它自己也能被测试（见 `test_auth_auditor_can_actually_fail`）——
    内联断言无法被证伪，护栏就可能悄悄变成恒真。
    """
    offenders: list[str] = []
    for endpoint in endpoints:
        status_code = _call_without_token(client, endpoint.method, endpoint.path).status_code
        if endpoint.auth and status_code != 401:
            offenders.append(f"{endpoint.method} {endpoint.path} 声明需鉴权，实际 {status_code}")
        if not endpoint.auth and status_code == 401:
            offenders.append(f"{endpoint.method} {endpoint.path} 声明公开，实际 401")
    return offenders


@pytest.fixture()
def isolated_client(tmp_path, monkeypatch) -> TestClient:
    """独立临时应用库：不触碰正式 db/app.db（与 test_auth_api.py 同口径）。"""
    from app.core import config
    from app.db import appdb

    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "manifest" / "app.db")
    appdb.init_app_db()
    return TestClient(app)


def test_endpoints_declared_as_auth_required_really_return_401(isolated_client: TestClient) -> None:
    """无 token 调用所有 auth=True 端点 → 必须 401（不是 403、不是 500）。"""
    required = [e for e in gen.build_endpoints() if e.auth]
    assert required, "没有任何端点声明需要鉴权，检查器可能已失效"
    offenders = [o for o in _audit_auth_declarations(isolated_client, required) if "声明需鉴权" in o]
    assert not offenders, "以下端点声明需鉴权但未返回 401：\n" + "\n".join(offenders)


def test_endpoints_declared_as_public_do_not_return_401(isolated_client: TestClient) -> None:
    """反向自查：公开端点无 token 时**不得**返回 401。

    否则说明 auth 判据是"瞎报"（把公开端点也标成需要鉴权），
    上面那条测试就会变成一个永远通过的假绿。
    """
    public = [e for e in gen.build_endpoints() if not e.auth]
    assert public, "没有任何公开端点，检查器可能已失效"
    offenders = [o for o in _audit_auth_declarations(isolated_client, public) if "声明公开" in o]
    assert not offenders, "以下端点声明为公开却返回 401：\n" + "\n".join(offenders)


def test_auth_auditor_can_actually_fail(isolated_client: TestClient) -> None:
    """变异测试：把公开端点谎报成"需鉴权"，对账函数必须报出来。

    没有这一条，上面两条测试可能因为对账函数写坏而永远全绿（铁律 20 / 46）。
    """
    import dataclasses

    lying = dataclasses.replace(
        next(e for e in gen.build_endpoints() if not e.auth), auth=True
    )
    offenders = _audit_auth_declarations(isolated_client, [lying])
    assert offenders, "对账函数对'谎报鉴权'无反应 ⇒ 判据失效"
    assert "声明需鉴权" in offenders[0]

    honest = dataclasses.replace(lying, auth=False)
    assert _audit_auth_declarations(isolated_client, [honest]) == []



# ---------- 4. 当前材料不得残留陈旧口径 ----------


# 运行期拼装，避免扫描器自身成为假阳性来源（铁律 44）。
_STALE_PATTERNS = [
    "16 " + "个端点",
    "17 " + "条路由",
    "17 " + "个端点",
    "17 " + "endpoints",
    "11 " + "个 router",
    "16 " + "条真实可达路由",
    "16 " + "paths",
]
_HISTORICAL_MARKERS = ("历史", "Historical", "快照", "archive", "Archived")


def _scan_stale_counts(text: str) -> list[tuple[int, str, str]]:
    """返回 (行号, 最近标题, 行内容)，只针对"标题未标注历史"的行。"""
    hits: list[tuple[int, str, str]] = []
    heading = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            heading = line
            continue
        if any(pattern in line for pattern in _STALE_PATTERNS):
            hits.append((lineno, heading, line))
    return hits


def test_stale_endpoint_counts_only_live_in_historical_sections() -> None:
    problems: list[str] = []
    for rel, _with_table, _link in gen.SYNC_TARGETS:
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for lineno, heading, line in _scan_stale_counts(text):
            if any(marker in heading for marker in _HISTORICAL_MARKERS):
                continue
            problems.append(f"{rel}:{lineno}（所属标题：{heading or '<无>'}）{line.strip()}")
    assert not problems, (
        "当前材料中出现陈旧端点口径（应统一为权威清单）：\n" + "\n".join(problems)
    )


def test_stale_count_scanner_is_not_a_no_op() -> None:
    """反向自查：喂一个已知陈旧样本，扫描器必须报出来。

    没有这一条，`test_stale_endpoint_counts_only_live_in_historical_sections`
    可能在扫描器坏掉时静默全绿（铁律 15 / 46）。
    """
    bad = "# 当前状态\n\n后端共 " + "16 " + "个端点。\n"
    assert _scan_stale_counts(bad), "扫描器对已知陈旧样本无反应 ⇒ 判据失效"

    historical = "# 历史快照（Historical）\n\n后端共 " + "16 " + "个端点。\n"
    hits = _scan_stale_counts(historical)
    assert len(hits) == 1 and any(m in hits[0][1] for m in _HISTORICAL_MARKERS)


# ---------- 5. marker 重写不得伤及区块外的字节 ----------


def test_marker_rewrite_preserves_everything_outside_the_block(tmp_path: Path) -> None:
    """生成器只允许改 BEGIN/END 之间的内容。"""
    newline = "\r\n"
    original = newline.join(
        [
            "# 标题",
            "",
            gen.MARKER_BEGIN,
            "旧内容（应当被替换）",
            gen.MARKER_END,
            "",
            "尾部内容（必须逐字节保留）",
            "",
        ]
    )
    body = "新内容"
    updated, changed = gen._replace_block(original, body, newline)

    assert changed is True
    assert "旧内容" not in updated
    assert "新内容" in updated
    assert updated.startswith("# 标题" + newline + newline)
    assert updated.endswith(newline + "尾部内容（必须逐字节保留）" + newline)

    # 幂等：再替换一次不再产生变化
    again, changed_again = gen._replace_block(updated, body, newline)
    assert changed_again is False
    assert again == updated


def test_marker_missing_is_reported_not_silently_ignored(tmp_path: Path) -> None:
    """没有 marker 时必须报错，而不是"什么都没做然后返回成功"。"""
    text = "# 没有 marker 的文档\n"
    _updated, changed = gen._replace_block(text, "内容", "\n")
    assert changed is False
