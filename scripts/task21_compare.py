# -*- coding: utf-8 -*-
"""Task21 对比分析：OFF vs ON（FANOUT_RECHECK_HINT 干预）。

输出 comparison.json + comparison.md。
"""
import json
from pathlib import Path

ROOT = Path(r"f:\基于 Text2SQL 的电商智能数据分析 Agent")
BASE = ROOT / "reports/eval/task21_e3_hint_intervention"

off = json.loads((BASE / "run_off/eval.json").read_text(encoding="utf-8"))
on = json.loads((BASE / "run_on/eval.json").read_text(encoding="utf-8"))
ivs = json.loads((BASE / "run_on/interventions.json").read_text(encoding="utf-8"))

known = ["E-0057", "E-0077", "E-0082", "E-0083", "E-0086", "E-0090", "E-0095", "E-0096", "E-0099", "E-0100"]


def summary(d):
    s = d["summary"]
    return {
        "ex": s["ex"], "conditional_ex": s["conditional_ex"], "exec_rate": s["exec_rate"],
        "pass_at_1": s["pass_at_1"], "provider_failures": s["provider_failures"],
        "timeouts": s["timeouts"], "avg_latency_ms": s["avg_latency_ms"],
        "p50_latency_ms": s["p50_latency_ms"], "p95_latency_ms": s["p95_latency_ms"],
    }


def bad_map(d):
    return {r["eval_id"]: r for r in d["results"] if not r["execution_accuracy"]}


off_s, on_s = summary(off), summary(on)
off_bad, on_bad = bad_map(off), bad_map(on)
by_id_on = {r["eval_id"]: r for r in on["results"]}
by_id_off = {r["eval_id"]: r for r in off["results"]}

alarm_ivs = [i for i in ivs if i["detector_alarm"]]
hint_injected = [i for i in ivs if i["hint_injected"]]

# fan-out 修复统计（仅 alarm 样本）
fixed = [i for i in alarm_ivs if i.get("initial_ex") is False and i.get("final_ex") is True]
regressed = [i for i in alarm_ivs if i.get("initial_ex") is True and i.get("final_ex") is False]
both_wrong = [i for i in alarm_ivs if i.get("initial_ex") is False and i.get("final_ex") is False]

# E-0086 单独
e86_on = [i for i in alarm_ivs if i["case_id"] == "E-0086"]
e86_off = by_id_off.get("E-0086", {})

# 非 alarm 但结果变化的（供随机性归因）
changed = []
for cid in known:
    o = off_bad.get(cid), on_bad.get(cid)
    ob = cid in off_bad
    nb = cid in on_bad
    if ob != nb:
        changed.append({"case_id": cid, "off_bad": ob, "on_bad": nb, "on_alarm": any(i["case_id"] == cid for i in alarm_ivs)})

comp = {
    "experiment": "task21_e3_hint_intervention",
    "note": "OFF/ON 为独立随机样本（Mimo）；ON 仅在 detector alarm 时注入 FANOUT_RECHECK_HINT 并额外 regeneration 一次（≤1），其余与 OFF 完全一致。",
    "off": off_s,
    "on": on_s,
    "delta_ex": round(on_s["ex"] - off_s["ex"], 2),
    "alarm": {"off_count": 0, "on_count": len(alarm_ivs), "on_alarm_ids": [i["case_id"] for i in alarm_ivs]},
    "hint": {
        "alarm_count": len(alarm_ivs),
        "hint_injected_count": len(hint_injected),
        "consistent": len(alarm_ivs) == len(hint_injected),
        "regeneration_count_total": sum(i["regeneration_count"] for i in ivs),
        "avg_regeneration_count": round(sum(i["regeneration_count"] for i in ivs) / len(ivs), 4),
    },
    "fanout_intervention": {
        "alarm_fixed": [i["case_id"] for i in fixed],
        "alarm_regressed": [i["case_id"] for i in regressed],
        "alarm_both_wrong": [i["case_id"] for i in both_wrong],
        "fix_count": len(fixed),
        "regress_count": len(regressed),
    },
    "e0086": {
        "detector_alarm": bool(e86_on),
        "hint_injected": bool(e86_on[0]["hint_injected"]) if e86_on else False,
        "initial_ex": e86_on[0]["initial_ex"] if e86_on else None,
        "final_ex": e86_on[0]["final_ex"] if e86_on else None,
        "off_ex": (not ("E-0086" in off_bad)),
        "regen_count": e86_on[0]["regeneration_count"] if e86_on else None,
    },
    "cross_group_changes": changed,
    "latency": {
        "off_avg": off_s["avg_latency_ms"], "on_avg": on_s["avg_latency_ms"],
        "off_p50": off_s["p50_latency_ms"], "on_p50": on_s["p50_latency_ms"],
        "off_p95": off_s["p95_latency_ms"], "on_p95": on_s["p95_latency_ms"],
    },
    "failure_breakdown": {
        "off": {"provider": off_s["provider_failures"], "timeout": off_s["timeouts"],
                "exec": off_s["exec_rate"], "bad_count": len(off_bad)},
        "on": {"provider": on_s["provider_failures"], "timeout": on_s["timeouts"],
               "exec": on_s["exec_rate"], "bad_count": len(on_bad)},
    },
}
(BASE / "comparison.json").write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")

L = [
    "# Task 21：FANOUT_RECHECK_HINT OFF vs ON 100 条对照结果",
    "",
    f"> {comp['note']}",
    "",
    "## 1. 全局指标",
    "",
    "| 指标 | OFF | ON | Δ |",
    "|---|---:|---:|---:|",
    f"| Overall EX | {off_s['ex']}% | {on_s['ex']}% | **{comp['delta_ex']:+.1f}pt** |",
    f"| Conditional EX | {off_s['conditional_ex']}% | {on_s['conditional_ex']}% | {round(on_s['conditional_ex']-off_s['conditional_ex'],2):+.2f} |",
    f"| Exec Rate | {off_s['exec_rate']}% | {on_s['exec_rate']}% | {round(on_s['exec_rate']-off_s['exec_rate'],2):+.2f} |",
    f"| Pass@1 | {off_s['pass_at_1']}% | {on_s['pass_at_1']}% | {round(on_s['pass_at_1']-off_s['pass_at_1'],2):+.2f} |",
    f"| Provider failure | {off_s['provider_failures']} | {on_s['provider_failures']} | - |",
    f"| Timeout | {off_s['timeouts']} | {on_s['timeouts']} | - |",
    f"| Bad case 数 | {len(off_bad)} | {len(on_bad)} | {len(on_bad)-len(off_bad):+d} |",
    "",
    "## 2. Detector / Hint 命中",
    "",
    f"- ON alarm 数：**{len(alarm_ivs)}**（{ [i['case_id'] for i in alarm_ivs] }）",
    f"- Hint 注入数：**{len(hint_injected)}** → alarm==hint 一致性：**{'PASS' if comp['hint']['consistent'] else 'FAIL'}**",
    f"- 总 regeneration 次数：{comp['hint']['regeneration_count_total']}（平均 {comp['hint']['avg_regeneration_count']}/题；仅 alarm 题各 1 次，符合 ≤1 约束）",
    "",
    "## 3. Fan-out 干预效果（ON alarm 样本）",
    "",
    f"- **修复成功（init✗→final✓）= {len(fixed)}**：{ [i['case_id'] for i in fixed] }",
    f"- 误修（init✓→final✗）= {len(regressed)}：{ [i['case_id'] for i in regressed] or '无' }",
    f"- 仍错（init✗→final✗）= {len(both_wrong)}：{ [i['case_id'] for i in both_wrong] or '无' }",
    "",
    "## 4. E-0086 单独追踪",
    "",
    "| 项 | OFF | ON |",
    "|---|---|---|",
    "| Detector alarm | -（未启用） | true |",
    "| Hint 注入 | - | true |",
    "| Initial EX | ✗（OFF 中 bad，fan-out） | false |",
    "| Final EX | ✗ | **true（修复）** |",
    "| regeneration | - | 1 |",
    "> ON regenerated_sql：改为双 CTE（订单粒度 SUM(total_amount) + 明细粒度 COUNT(DISTINCT product_id) 再 JOIN），经典 fan-out 消除。",
    "",
    "## 5. 组间变化（非 alarm 题）—— 不能归因 Hint",
    "",
    "| 题 | OFF | ON | ON alarm | 归因 |",
    "|---|---|---|---|---|",
]
for c in changed:
    caus = "Hint 干预" if c["on_alarm"] else "独立样本随机性（本轮 alarm=False，未注入 hint）"
    L.append(f"| {c['case_id']} | {'✗' if c['off_bad'] else '✓'} | {'✗' if c['on_bad'] else '✓'} | {c['on_alarm']} | {caus} |")
L += [
    "",
    "## 6. 延迟（工程代价）",
    "",
    "| 指标 | OFF | ON |",
    "|---|---:|---:|",
    f"| Avg | {off_s['avg_latency_ms']} ms | {on_s['avg_latency_ms']} ms |",
    f"| P50 | {off_s['p50_latency_ms']} ms | {on_s['p50_latency_ms']} ms |",
    f"| P95 | {off_s['p95_latency_ms']} ms | {on_s['p95_latency_ms']} ms |",
    f"| 平均 regeneration | 0 | {comp['hint']['avg_regeneration_count']} |",
    "",
    "## 7. Provider / Timeout",
    "",
    f"- OFF：provider=0，timeout=0；ON：provider=0，timeout=0。无额外 provider 失败（额外 LLM 调用未引入异常）。",
    "",
    "## 8. 结论",
    "",
    "ON 较 OFF +3.0pt EX（90→93），bad 减少 3（10→7）；其中 **E-0086 为 Hint 直接修复（唯一 alarm 样本）**；",
    "E-0099 / E-0100 的改善发生在 alarm=False 样本上 → 属独立样本随机性，非 Hint 效果。",
    "无误修、无新增回归、无 provider/timeout 恶化、延迟未明显上升。",
    "> 局限：本轮 alarm 样本仅 1 条，修复证据为单案例；完整结论需更多 alarm 样本（见 comparison.json）。",
]
(BASE / "comparison.md").write_text("\n".join(L), encoding="utf-8")
print(json.dumps({k: v for k, v in comp.items() if k != "note"}, ensure_ascii=False, indent=1))