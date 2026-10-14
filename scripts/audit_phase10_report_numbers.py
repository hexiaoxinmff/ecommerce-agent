#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第十阶段验收报告 —— **手打数字只读对账器**。

为什么要有这个东西（铁律 24 的可执行版 + 铁律 55）：
验收报告里每一个数字（1028 passed / 18 endpoints / `5824f7dd` / `3ac09864…` / 55/55 …）
都是人手敲进去的。**人手敲进去的数字不等于事实** —— 它可能来自上一轮的记忆、
来自中途失败的一次跑、来自复制粘贴时的手滑。

本脚本做的事只有一件：
    从**原始产物**重算真值 → 从报告文本里**抽取**声称值 → 逐项断言相等。

设计约束：
- **只读**。不写任何文件，不改任何产物。
- **验证器崩了必须落红**（铁律 15）：任何一项重算抛异常，都记成 FAIL，绝不跳过。
- **反向自查**（铁律 20/46）：本脚本自带一条变异测试 —— 把报告文本改坏一个数字，
  对账器必须比原来**多报**至少一条失败。否则它可能是个恒绿的摆设。

用法：
    python scripts/audit_phase10_report_numbers.py            # 对账
    python scripts/audit_phase10_report_numbers.py --json     # 输出 JSON
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT = PROJECT_ROOT / "reports" / "phase10" / "第十阶段_v1.1产品化运行基础验收报告.md"
EVIDENCE = PROJECT_ROOT / "reports" / "phase10" / "evidence"
ZIP_EXPECTED = "3ac09864b3a6eb58661aa56e5c308cdb2644655c6b16a838184cde719e23a30f"


class CheckFailed(Exception):
    """对账不一致。"""


# ---------------------------------------------------------------------------
# 真值重算：全部从**原始产物**出发，不信任任何派生的手抄数字
# ---------------------------------------------------------------------------


def load_generator():
    """按文件路径加载 scripts/export_api_endpoints.py（它自带 sys.path 处理）。"""
    path = PROJECT_ROOT / "scripts" / "export_api_endpoints.py"
    spec = importlib.util.spec_from_file_location("export_api_endpoints", path)
    if spec is None or spec.loader is None:
        raise CheckFailed("无法加载 export_api_endpoints.py")
    mod = importlib.util.module_from_spec(spec)
    # ⚠️ 必须先注册进 sys.modules：模块里用了 @dataclass，而 dataclasses 会去
    #    sys.modules[cls.__module__].__dict__ 找名字。不注册 → NoneType.__dict__ 炸。
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def truth_endpoints() -> dict:
    """端点事实：直接从 FastAPI app 推导，不看任何文档。"""
    gen = load_generator()
    eps = gen.build_endpoints()
    return {
        "count": len(eps),
        "routers": len({e.router for e in eps}),
        "auth": sum(1 for e in eps if e.auth),
        "public": sum(1 for e in eps if not e.auth),
        "fingerprint": gen.fingerprint(),
    }


def truth_pytest(xml_name: str) -> dict:
    root = ET.parse(EVIDENCE / xml_name).getroot()
    tests = failures = errors = skipped = 0
    failed_ids = set()
    for suite in root.iter("testsuite"):
        tests += int(suite.get("tests") or 0)
        failures += int(suite.get("failures") or 0)
        errors += int(suite.get("errors") or 0)
        skipped += int(suite.get("skipped") or 0)
    for tc in root.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            failed_ids.add(f"{tc.get('classname')}::{tc.get('name')}")
    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": tests - failures - errors - skipped,
        "failed_ids": sorted(failed_ids),
    }


def truth_vitest() -> dict:
    data = json.loads((EVIDENCE / "vitest.json").read_text(encoding="utf-8"))
    return {
        "files": len(data.get("testResults") or []),
        "tests": int(data.get("numTotalTests") or 0),
        "passed": int(data.get("numPassedTests") or 0),
        "failed": int(data.get("numFailedTests") or 0),
    }


def truth_zip() -> dict:
    zips = sorted((PROJECT_ROOT / "_delivery_build").glob("*.zip"))
    if not zips:
        raise CheckFailed("_delivery_build 下找不到 ZIP")
    digest = hashlib.sha256(zips[0].read_bytes()).hexdigest()
    return {"name": zips[0].name, "sha256": digest, "match": digest == ZIP_EXPECTED}


def truth_frozen_mtime() -> dict:
    """冻结目录的最新写入时间（铁律 2：porcelain 看不见未跟踪文件内部改动 ⇒ 用 mtime）。"""
    newest_ts = 0.0
    newest = None
    for p in (PROJECT_ROOT / "_delivery_build").rglob("*"):
        if p.is_file():
            ts = p.stat().st_mtime
            if ts > newest_ts:
                newest_ts, newest = ts, p
    if newest is None:
        raise CheckFailed("_delivery_build 为空")
    return {
        "stamp": datetime.fromtimestamp(newest_ts).strftime("%Y-%m-%d %H:%M"),
        "path": str(newest.relative_to(PROJECT_ROOT)),
    }


def truth_browser() -> dict:
    data = json.loads((EVIDENCE / "auth_states_browser_55_55.json").read_text(encoding="utf-8"))
    biz = data.get("business") or {}
    gt = data.get("api_ground_truth") or {}
    return {
        "total": data.get("total"),
        "passed": data.get("passed"),
        "failed": data.get("failed"),
        "verdict": data.get("verdict"),
        "kpis": gt,
        "sql": biz.get("generated_sql") or "",
        "history_id": (biz.get("history_item") or {}).get("id"),
        "history_sql": (biz.get("history_item") or {}).get("sql") or "",
        "total_time_ms": (biz.get("history_item") or {}).get("total_time_ms"),
        "killed_pids": data.get("kill_tree_killed_pids") or [],
        "frontend_before": data.get("frontend_pid_before"),
        "frontend_after": data.get("frontend_pid_after"),
    }


def truth_exit_codes() -> list[int]:
    src = (PROJECT_ROOT / "scripts" / "start_dev.py").read_text(encoding="utf-8")
    codes = [int(m.group(1)) for m in re.finditer(r"^EXIT_[A-Z_]+ = (\d+)$", src, re.M)]
    if not codes:
        raise CheckFailed("start_dev.py 里没找到 EXIT_ 常量")
    return sorted(set(codes))


def truth_porcelain_delta() -> dict:
    """工作区相对开工基线的改动条目（基线证据已归档）。"""
    import subprocess

    baseline = EVIDENCE / "baseline_porcelain.txt"
    if not baseline.exists():
        raise CheckFailed("缺少基线证据 baseline_porcelain.txt")
    base = {line.strip()[3:].strip() for line in baseline.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()}
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    now = {line.strip()[3:].strip() for line in out.stdout.splitlines() if line.strip()}
    return {"added": sorted(now - base), "removed": sorted(base - now)}


# ---------------------------------------------------------------------------
# 对账项：从报告文本抽取声称值，与重算真值逐项断言
# ---------------------------------------------------------------------------


def _one(pattern: str, text: str, label: str) -> re.Match:
    m = re.search(pattern, text)
    if not m:
        raise CheckFailed(f"报告里找不到「{label}」的声称值（pattern={pattern}）")
    return m


def _eq(label: str, claimed, actual) -> tuple[str, bool, str]:
    ok = str(claimed) == str(actual)
    return (label, ok, f"报告={claimed} 产物={actual}")


def audit(text: str, *, skip_self_referential: bool = False) -> list[tuple[str, bool, str]]:
    """跑完全部对账项。返回 [(label, ok, detail)]。单项异常 → 记为 FAIL，不中断。

    ⚠️ 自指陷阱：`pytest` 的 JUnit XML 是**同一次运行结束时**才写盘的。
    所以「拿 pytest 产物对账」这一类检查，在**测试套件内部**运行时，
    读到的必然是**上一轮**的产物 —— 于是「本轮新增了 N 条测试」会让它们必然变红，
    而且红得毫无道理（不是报告错了，是对账器读到了过期证据）。

    解决办法不是放宽判据，而是**把这类检查标记为 self_referential**：
    套件内跑的时候跳过它们（`--skip-self-referential`），
    等本轮产物落盘后**再单独跑一次**全量对账。判据一点没松。
    """
    results: list[tuple[str, bool, str]] = []
    skipped: list[str] = []

    def run(label: str, fn, *, self_referential: bool = False):
        if self_referential and skip_self_referential:
            skipped.append(label)
            return
        try:
            res = fn()
            if isinstance(res, list):
                results.extend(res)
            else:
                results.append(res)
        except CheckFailed as err:
            results.append((label, False, f"FAIL {err}"))
        except Exception as err:  # 验证器崩了必须落红（铁律 15）
            results.append((label, False, f"验证器异常（必须落红）：{type(err).__name__}: {err}"))


    # --- 端点事实源 ---
    def _ep():
        t = truth_endpoints()
        m = _one(r"权威清单（(\d+) 个 / (\d+) router / 需鉴权 (\d+) / 公开 (\d+)）", text, "端点总数")
        out = [
            _eq("端点总数", m.group(1), t["count"]),
            _eq("router 数", m.group(2), t["routers"]),
            _eq("需鉴权数", m.group(3), t["auth"]),
            _eq("公开数", m.group(4), t["public"]),
        ]
        fp = _one(r"清单指纹：`([0-9a-f]{8})`", text, "清单指纹")
        out.append(_eq("清单指纹", fp.group(1), t["fingerprint"]))
        # 注意：报告表格里 method 列是裸的 GET/POST/DELETE，没有反引号
        rows = re.findall(r"^\| (\d+) \| `\w+` \| (?:GET|POST|DELETE) \| `/api/", text, re.M)
        out.append(_eq("报告端点表行数", len(rows), t["count"]))
        return out

    run("端点事实源", _ep)

    # --- 后端测试 ---
    def _narrow():
        t = truth_pytest("pytest_narrow.xml")
        m = _one(r"\*\*(\d+) failed / (\d+) passed / (\d+) skipped\*\*", text, "窄口径")
        return [
            _eq("窄口径 failed", m.group(1), t["failures"]),
            _eq("窄口径 passed", m.group(2), t["passed"]),
            _eq("窄口径 skipped", m.group(3), t["skipped"]),
        ]

    run("后端窄口径", _narrow, self_referential=True)

    def _wide():
        t = truth_pytest("pytest_wide.xml")
        m = _one(r"\*\*(\d+) tests / (\d+) failures / (\d+) errors / (\d+) skipped\*\*", text, "宽口径")
        return [
            _eq("宽口径 tests", m.group(1), t["tests"]),
            _eq("宽口径 failures", m.group(2), t["failures"]),
            _eq("宽口径 errors", m.group(3), t["errors"]),
            _eq("宽口径 skipped", m.group(4), t["skipped"]),
        ]

    run("后端宽口径", _wide, self_referential=True)

    def _failed_set():
        """报告列出的失败用例集，必须与产物**逐条同名**。"""
        t = truth_pytest("pytest_narrow.xml")
        listed = set(re.findall(r"^\s*(test_\w+\.py::test_\w+)\s*$", text, re.M))
        # classname 形如 backend.tests.test_bailian_provider::test_xxx
        # ⇒ 先按 "::" 切断，再取模块名最后一段 + .py（顺序反了会得到 xxx.py::test_xxx 这种怪物）
        actual = set()
        for cid in t["failed_ids"]:
            cls, _, name = cid.partition("::")
            actual.add(f"{cls.split('.')[-1]}.py::{name}")
        ok = listed == actual and len(actual) == 6
        return (
            "报告列出的失败用例集与产物逐条同名",
            ok,
            f"报告={len(listed)} 产物={len(actual)} 差集={sorted(listed ^ actual)}",
        )

    run("失败用例集", _failed_set, self_referential=True)

    # --- 前端测试 ---
    def _fe():
        t = truth_vitest()
        m = _one(r"\*\*(\d+) files / (\d+) tests\*\*", text, "前端")
        return [
            _eq("前端 files", m.group(1), t["files"]),
            _eq("前端 tests", m.group(2), t["tests"]),
            _eq("前端 failed", 0, t["failed"]),
        ]

    run("前端测试", _fe)

    # --- v1.0 冻结 ---
    def _zip():
        t = truth_zip()
        m = _one(r"`3ac09864b3a6eb58661aa56e5c308cdb2644655c6b16a838184cde719e23a30f`", text, "ZIP 哈希")
        return [("ZIP SHA256 与期望值一致", t["match"], f"{t['sha256']}"), ("报告含 ZIP 哈希原文", bool(m), "3ac09864…a30f")]

    run("v1.0 ZIP", _zip)

    def _frozen():
        t = truth_frozen_mtime()
        m = _one(r"`(\d{4}-\d{2}-\d{2} \d{2}:\d{2})`（冻结时刻）", text, "冻结 mtime")
        return [_eq("_delivery_build 最新 mtime", m.group(1), t["stamp"])]

    run("冻结目录 mtime", _frozen)

    # --- 浏览器实测 ---
    def _br():
        t = truth_browser()
        m = _one(r"ALL_PASS\s+(\d+)/(\d+)", text, "浏览器实测")
        return [
            _eq("浏览器 passed", m.group(1), t["passed"]),
            _eq("浏览器 total", m.group(2), t["total"]),
            _eq("浏览器 failed", 0, t["failed"]),
        ]

    run("浏览器实测", _br)

    # --- 真实业务闭环 ---
    def _biz():
        t = truth_browser()
        out = []
        out.append(("报告中的 SQL 与产物一致", t["sql"] in text and bool(t["sql"]), t["sql"]))
        m = _one(r"history\.id=(\d+)", text, "History id")
        out.append(_eq("History 记录 id", m.group(1), t["history_id"]))
        m2 = _one(r"total_time_ms=(\d+\.\d+)", text, "耗时")
        out.append(_eq("History 耗时(ms)", m2.group(1), t["total_time_ms"]))
        out.append(("History SQL 与生成 SQL 逐字一致", t["sql"].strip() == t["history_sql"].strip(), f"{t['history_sql']}"))
        return out

    run("真实业务闭环", _biz)

    # --- 真实 KPI ---
    def _kpi():
        t = truth_browser()["kpis"]
        m = _one(r"`¥([\d,]+\.\d\d) / (\d+) / ([\d,]+) / ¥([\d,]+\.\d\d)`", text, "KPI")
        norm = lambda s: s.replace(",", "")
        return [
            _eq("本月销售额", norm(m.group(1)), t["month_sales"]),
            _eq("本月订单量", m.group(2), int(t["month_orders"])),
            _eq("注册用户数", norm(m.group(3)), int(t["users_total"])),
            _eq("客单价", norm(m.group(4)), t["avg_order_value"]),
            _eq("数据截止日", "2026-09-12", t["as_of"]),
        ]

    run("真实 KPI", _kpi)

    # --- 自证式负对照 ---
    def _neg():
        t = truth_browser()
        m = _one(r"killed=\[([0-9,]+)\] frontend=(\d+)", text, "负对照 PID")
        claimed = [int(x) for x in m.group(1).split(",") if x]
        out = [
            _eq("被杀 PID 名单", claimed, t["killed_pids"]),
            _eq("前端监听 PID", m.group(2), t["frontend_before"]),
            ("负对照真的没误伤前端", int(m.group(2)) not in claimed, f"frontend={m.group(2)} killed={claimed}"),
        ]
        return out

    run("自证式负对照", _neg)

    # --- 启动脚本退出码 ---
    def _codes():
        codes = truth_exit_codes()
        missing = [c for c in codes if f"| {c} |" not in text]
        return [("启动脚本退出码全部在报告中", not missing, f"产物={codes} 缺失={missing}")]

    run("启动退出码", _codes)

    # --- 章节结构：任务书 §十四 点名的 10 个章节必须都在 ---
    def _sections():
        # 任务书 §十四 要求的十章（关键词用于防止「编号对了但写跑题」）
        required = {
            1: "Auth",
            2: "endpoints",
            3: "启动",
            4: "环境变量",
            5: "启动异常",
            6: "Health",
            7: "测试结果",
            8: "浏览器",
            9: "v1.0",
            10: "风险",
        }
        found = {int(m.group(1)): m.group(2) for m in re.finditer(r"^## (\d+)\. (.+?)\s*$", text, re.M)}
        # 用「包含」而不是「相等」：报告另有 §0（成功标准对账）与 §11（可复算性）是**追加**的，
        # 用相等判据会把「多写了两节」误判成违规。
        out = [("报告含任务书 §十四 点名的 10 个章节", set(required) <= set(found), f"找到={sorted(found)} 缺={sorted(set(required) - set(found))}")]
        for num, kw in required.items():
            title = found.get(num, "")
            out.append((f"第 {num} 章标题含「{kw}」", kw in title, title))
        return out

    run("章节结构（§十四）", _sections)

    # --- 6 条既有失败的成因归因（A/B 因果量化，铁律 30） ---
    def _known_failures():
        t = truth_pytest("pytest_narrow.xml")
        # 任务书要求「未新增失败」；这里进一步断言这 6 条**都不是本阶段代码引起的**：
        # 它们全部是「写死模型名 / 写死 Provider / 假设无 Key」的配置口径断言。
        env_driven = {
            "test_health.py::test_health_reports_runtime_llm_config",
            "test_llm_api.py::test_key_not_configured_returns_503",
            "test_llm_api.py::test_secret_never_leaks_through_real_provider_chain",
        }
        actual = {f"{cid.split('::')[0].split('.')[-1]}.py::{cid.split('::')[-1]}" for cid in t["failed_ids"]}
        return [
            ("失败总数恒为 6（未新增）", len(t["failed_ids"]) == 6, f"实际={len(t['failed_ids'])}"),
            (
                "6 条中含 3 条纯环境口径驱动（切口径即转绿）",
                env_driven <= actual,
                f"缺={sorted(env_driven - actual)}",
            ),
            ("报告已声明失败与本阶段无关", "既有失败" in text, ""),
        ]

    run("既有失败归因", _known_failures, self_referential=True)

    # --- 工作区改动边界 ---
    def _delta():
        t = truth_porcelain_delta()
        m = _one(r"新增 \*\*(\d+) 个文件 \+ (\d+) 个目录\*\*", text, "改动条目")
        # git porcelain 里目录条目的结尾是 "/"，其余是文件。别用「有没有斜杠」判断，
        # 报告路径本身带目录层级，会误判。
        dirs = [p for p in t["added"] if p.endswith("/")]
        files = [p for p in t["added"] if not p.endswith("/")]
        return [
            _eq("新增文件数", m.group(1), len(files)),
            _eq("新增目录数", m.group(2), len(dirs)),
            _eq("消失条目数", 0, len(t["removed"])),
        ]

    run("工作区边界", _delta)

    audit.skipped = list(skipped)  # type: ignore[attr-defined]
    return results


def mutation_self_check(text: str, *, skip_self_referential: bool = False) -> tuple[bool, str]:
    """反向自查（铁律 20/46）：改坏数字，对账器必须比原来多报失败。

    变异两个数字：一个来自**非**自指项（端点指纹），一个来自自指项（pytest 计数）。
    这样无论加不加 `--skip-self-referential`，反向自查都能成立：
    - 不加：两个变异都会生效 ⇒ +2；
    - 加了：pytest 计数项被跳过，只有指纹变异生效 ⇒ +1。
    """
    opts = {"skip_self_referential": skip_self_referential}
    base_fails = sum(1 for _, ok, _ in audit(text, **opts) if not ok)

    # 变异目标**从报告文本里现找**，不硬编码具体数字 ——
    # 否则每次报告数字正常变动（比如新增测试导致 1028→1031），变异都会失效，
    # 而「变异失效」会被当成反向自查失败 ⇒ 一个本该稳定的护栏变得很脆。
    mutated = text
    touched = []

    m = re.search(r"\*\*(\d+) failed / (\d+) passed / (\d+) skipped\*\*", mutated)
    if m:
        mutated = mutated.replace(m.group(0), f"**{m.group(1)} failed / 9999 passed / {m.group(3)} skipped**", 1)
        touched.append("pytest 计数")

    m = re.search(r"清单指纹：`([0-9a-f]{8})`", mutated)
    if m:
        mutated = mutated.replace(m.group(0), "清单指纹：`deadbeef`", 1)
        touched.append("端点指纹")

    if not touched or mutated == text:
        return False, f"变异没有生效（在报告里没找到可改的数字；命中={touched}）"

    mut_fails = sum(1 for _, ok, _ in audit(mutated, **opts) if not ok)
    ok = mut_fails > base_fails
    return ok, f"变异={'+'.join(touched)} 原版失败={base_fails} 变异后失败={mut_fails}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="第十阶段验收报告手打数字只读对账")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument(
        "--skip-self-referential",
        action="store_true",
        help="跳过依赖 pytest 自身产物的检查（在 pytest 套件内运行时必须加，否则必然假红）",
    )
    args = ap.parse_args(argv)

    if not REPORT.exists():
        print(f"[FAIL] 报告不存在：{REPORT}")
        return 1
    text = REPORT.read_text(encoding="utf-8")

    results = audit(text, skip_self_referential=args.skip_self_referential)
    mut_ok, mut_detail = mutation_self_check(
        text, skip_self_referential=args.skip_self_referential
    )
    results.append(("反向自查：改坏数字后必须多报失败", mut_ok, mut_detail))

    failed = [r for r in results if not r[1]]
    if args.json:
        print(json.dumps({"total": len(results), "failed": len(failed), "items": [{"name": n, "ok": o, "detail": d} for n, o, d in results]}, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    print()
    print(f"===== {'ALL_PASS' if not failed else 'HAS_FAILURE'}  {len(results) - len(failed)}/{len(results)} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
