# -*- coding: utf-8 -*-
"""Task18 对比分析：OFF vs ON 的 detector telemetry 关联性统计。

读取两个 run 的 detector_telemetry.json，计算：
- alarm 率 / 各组失败率 / 已知 bad case 覆盖 / EX✓ 噪声 / E-0086 单独报告
输出 comparison.json + comparison.md。
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"f:\基于 Text2SQL 的电商智能数据分析 Agent")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/eval/task18_e3_detector_correlation"
KNOWN_BAD = ["E-0057", "E-0077", "E-0082", "E-0083", "E-0086", "E-0090", "E-0095", "E-0096", "E-0099", "E-0100"]


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def load(name: str) -> list[dict]:
    p = OUT / name / "detector_telemetry.json"
    return json.loads(p.read_text(encoding="utf-8"))["items"]


def analyze(items: list[dict], tag: str) -> dict:
    alarm = [i for i in items if i["fan_out_suspected"]]
    no_alarm = [i for i in items if not i["fan_out_suspected"]]
    n = len(items)

    def rates(group: list[dict], label: str) -> dict:
        g = len(group)
        return {
            "name": label,
            "count": g,
            "rate_pct": pct(g, n),
            "exec_fail": sum(1 for i in group if not i["exec_ok"]),
            "exec_fail_rate": pct(sum(1 for i in group if not i["exec_ok"]), g),
            "ex_fail": sum(1 for i in group if not i["ex"]),
            "ex_fail_rate": pct(sum(1 for i in group if not i["ex"]), g),
            "result_mismatch": sum(1 for i in group if i["ex"] is False and i["exec_ok"]),
            "result_mismatch_rate": pct(sum(1 for i in group if i["ex"] is False and i["exec_ok"]), g),
            "timeout": sum(1 for i in group if i["timeout"]),
            "timeout_rate": pct(sum(1 for i in group if i["timeout"]), g),
            "provider_failure": sum(1 for i in group if i["provider_failure"]),
        }

    res = {
        "tag": tag,
        "total": n,
        "alarm": rates(alarm, "alarm"),
        "no_alarm": rates(no_alarm, "no_alarm"),
        "alarm_ids": [i["case_id"] for i in alarm],
        "alarm_severity": {i["case_id"]: i["severity"] for i in alarm},
    }
    # 已知 bad case 覆盖
    res["known_bad"] = {}
    by_id = {i["case_id"]: i for i in items}
    for bid in KNOWN_BAD:
        it = by_id.get(bid)
        res["known_bad"][bid] = {
            "alarm": bool(it and it["fan_out_suspected"]),
            "severity": it["severity"] if it else None,
            "ex": it["ex"] if it else None,
            "exec_ok": it["exec_ok"] if it else None,
            "error_type": it["error_type"] if it else None,
        }
    # EX✓ 噪声：alarm 且 EX 通过
    res["ex_ok_alarmed"] = [i["case_id"] for i in items if i["fan_out_suspected"] and i["ex"]]
    return res


def rel_risk(al: dict, na: dict, key: str) -> float | None:
    r1 = al[key] / al["count"] if al["count"] else 0.0
    r2 = na[key] / na["count"] if na["count"] else 0.0
    return round(r1 / r2, 3) if r2 > 0 else None


off = analyze(load("run_off"), "OFF")
on = analyze(load("run_on"), "ON")
comp = {
    "experiment": "task18_e3_detector_correlation",
    "note": "OFF/ON 为独立生成样本（Mimo 随机性），比较的是『alarm 样本与失败率的关联』，非严格 paired causal effect。",
    "off": off,
    "on": on,
    "comparison": {
        "alarm_count_off": off["alarm"]["count"],
        "alarm_count_on": on["alarm"]["count"],
        "ex_ok_alarmed_off": off["ex_ok_alarmed"],
        "ex_ok_alarmed_on": on["ex_ok_alarmed"],
        "rel_risk_ex_fail_off": rel_risk(off["alarm"], off["no_alarm"], "ex_fail_rate_pct_raw" if False else "ex_fail"),
        "rel_risk_ex_fail_on": rel_risk(on["alarm"], on["no_alarm"], "ex_fail"),
        "rel_risk_exec_fail_off": rel_risk(off["alarm"], off["no_alarm"], "exec_fail"),
        "rel_risk_exec_fail_on": rel_risk(on["alarm"], on["no_alarm"], "exec_fail"),
    },
}
(OUT / "comparison.json").write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")

# Markdown
L = []
L.append("# Task 18：E3 Fan-out Detector 关联性验证 — OFF vs ON 对比")
L.append("")
L.append(f"> 说明：{comp['note']}")
L.append("> OFF = Clean Baseline 100 条（未调用 Detector 的官方样本）；ON = 全新 100 条（相同 Agent，离线补算 telemetry，Detector 只读不干预）。")
L.append("")
for tag in ("OFF", "ON"):
    r = comp[tag.lower()]
    L.append(f"## {tag}（total={r['total']}）")
    L.append("")
    L.append("| 组 | count | exec_fail% | EX_fail% | mismatch% | timeout% | provider |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for grp in (r["alarm"], r["no_alarm"]):
        L.append(f"| {grp['name']} | {grp['count']} | {grp['exec_fail_rate']} | {grp['ex_fail_rate']} | "
                 f"{grp['result_mismatch_rate']} | {grp['timeout_rate']} | {grp['provider_failure']} |")
    L.append("")
    L.append(f"- alarm 样本：{r['alarm_ids']}")
    L.append(f"- EX✓ 中被 alarm（噪声）：{r['ex_ok_alarmed']}")
    L.append("")
L.append("## 已知 Bad Case 覆盖")
L.append("")
known_ids = ["E-0086", "E-0057", "E-0077", "E-0082", "E-0083", "E-0090", "E-0095", "E-0096", "E-0099", "E-0100"]
L.append("| 题 | OFF alarm | ON alarm | OFF ex | ON ex | OFF err | ON err |")
L.append("|---|---|---|---|---|---|---|")
for bid in known_ids:
    o = comp["off"]["known_bad"][bid]
    n = comp["on"]["known_bad"][bid]
    L.append(f"| {bid} | {o['alarm']} | {n['alarm']} | {o['ex']} | {n['ex']} | {o['error_type']} | {n['error_type']} |")
L.append("")
L.append("## E-0086 单独报告")
L.append("")
L.append("| 项目 | OFF | ON |")
L.append("|---|---|---|")
L.append(f"| Detector alarm | {comp['off']['known_bad']['E-0086']['alarm']} | {comp['on']['known_bad']['E-0086']['alarm']} |")
L.append(f"| EX 结果 | {comp['off']['known_bad']['E-0086']['ex']} | {comp['on']['known_bad']['E-0086']['ex']} |")
L.append(f"| error_type | {comp['off']['known_bad']['E-0086']['error_type']} | {comp['on']['known_bad']['E-0086']['error_type']} |")
L.append("")
L.append("样本量过小时不做显著性推断；给出相对风险（仅分母足够时参考）。")
(OUT / "comparison.md").write_text("\n".join(L), encoding="utf-8")
print(json.dumps(comp["comparison"], ensure_ascii=False, indent=1))
print("written comparison.json / comparison.md")