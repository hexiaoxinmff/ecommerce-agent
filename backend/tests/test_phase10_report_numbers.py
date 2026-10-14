# -*- coding: utf-8 -*-
"""把 `scripts/audit_phase10_report_numbers.py` 接进测试套件。

为什么需要这一层：
验收报告里 30 多处数字（1028 passed / 18 endpoints / `5824f7dd` / `3ac09864…` / 55/55 …）
都是人手敲的。对账器能算，但**没人按按钮就不会响**。接进 pytest 之后，
任何人改了报告或产物导致数字对不上，这里立刻变红。

对账器自带的「反向自查」也是它的一个检查项 ⇒ 本文件只需断言「全部通过」，
「不是恒绿摆设」由对账器自己保证（铁律 20/46）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT = PROJECT_ROOT / "scripts" / "audit_phase10_report_numbers.py"
REPORT = PROJECT_ROOT / "reports" / "phase10" / "第十阶段_v1.1产品化运行基础验收报告.md"


def _run_audit() -> dict:
    if not AUDIT.exists():
        pytest.fail(f"对账器不见了：{AUDIT}（交付物缺失，必须落红）")
    if not REPORT.exists():
        pytest.fail(f"验收报告不见了：{REPORT}（交付物缺失，必须落红）")
    # ⚠️ 必须 --skip-self-referential：pytest 的 JUnit XML 是**本次运行结束时**才写盘的，
    #    在套件内读它必然读到上一轮的旧证据 ⇒ 「本轮新增了测试」会被误报成「报告数字错了」。
    #    那几项留给产物落盘后的独立全量对账（见报告 §11）。
    proc = subprocess.run(
        [sys.executable, str(AUDIT), "--json", "--skip-self-referential"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode not in (0, 1):
        pytest.fail(f"对账器异常退出（rc={proc.returncode}）：{proc.stderr[-2000:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        pytest.fail(f"对账器输出不是 JSON：{err}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}")


def test_report_numbers_reconcile_with_artifacts():
    """报告里每一个手打数字，都必须与原始产物重算出的真值一致。"""
    data = _run_audit()
    bad = [i for i in data["items"] if not i["ok"]]
    detail = "\n".join(f"  - {i['name']}: {i['detail']}" for i in bad)
    assert not bad, f"报告数字与产物不一致（{len(bad)}/{data['total']}）：\n{detail}"


def test_audit_covers_a_meaningful_number_of_claims():
    """对账项不能悄悄缩水：少于 20 项说明有人删了检查（铁律 46 的计数守卫）。"""
    data = _run_audit()
    assert data["total"] >= 20, f"对账项只有 {data['total']} 条，疑似被削减"


def test_audit_mutation_self_check_is_present_and_green():
    """对账器必须自带反向自查，且它自己得是绿的 —— 否则整个对账可能是恒绿摆设。"""
    data = _run_audit()
    items = [i for i in data["items"] if "反向自查" in i["name"]]
    assert items, "对账器缺少反向自查项（无法证明它不是恒绿的）"
    for item in items:
        assert item["ok"], f"反向自查本身没过：{item['name']} — {item['detail']}"
