# -*- coding: utf-8 -*-
"""Task17/E3 离线静态扫描：对 Clean Baseline 100 条 Pred SQL 运行 Fan-out Detector。

只读取 Pred SQL（final_sql，回退 initial_sql）；不读取 Gold SQL / Gold Result / Gold Label。
注意：pred_sql/final_sql 中不含语义标签；执行结果（execution_accuracy）仅用于后续
人工对齐标签，不进入 detector。

输出：
- reports/eval/task17_e3_fanout_validator/static_scan_report.json
- reports/eval/task17_e3_fanout_validator/static_scan_report.md
- reports/eval/task17_e3_fanout_validator/detector_rules.md
- reports/eval/task17_e3_fanout_validator/experiment_config.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"f:\基于 Text2SQL 的电商智能数据分析 Agent")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.sqlcheck.fanout_detector import analyze_fanout, to_dict  # noqa: E402

BASELINE = ROOT / "reports/eval/clean_baseline_v1_1/eval_clean_baseline_v1_1.json"
OUT = ROOT / "reports/eval/task17_e3_fanout_validator"

run = json.loads(BASELINE.read_text(encoding="utf-8"))
results = run["results"]

scan = []
for r in results:
    sql = (r.get("final_sql") or "").strip() or (r.get("initial_sql") or "").strip()
    diag = analyze_fanout(sql)
    entry = to_dict(diag, case_id=r["eval_id"])
    entry["sql_source"] = "final_sql" if (r.get("final_sql") or "").strip() else "initial_sql"
    entry["pred_sql_text"] = sql[:2000]
    # 仅记录观测标签（不进入 detector 决策）：baseline 执行结果用于人工对齐
    entry["_baseline_exec_accuracy"] = r["execution_accuracy"]
    scan.append(entry)

OUT.mkdir(parents=True, exist_ok=True)
report = {
    "generator": "app.sqlcheck.fanout_detector.analyze_fanout",
    "input": str(BASELINE),
    "input_count": len(results),
    "suspected": [e for e in scan if e["fan_out_suspected"]],
    "not_suspected": [e for e in scan if not e["fan_out_suspected"]],
    "items": scan,
}
(OUT / "static_scan_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)

# 摘要输出
sus = report["suspected"]
not_sus = report["not_suspected"]
print(f"扫描 {len(scan)} 条 Pred SQL")
print(f"fan_out_suspected=True : {len(sus)}")
for e in sus:
    print(f"   {e['case_id']} severity={e['severity']} patterns={e['patterns']} exec_ok={e['_baseline_exec_accuracy']}")
print(f"fan_out_suspected=False: {len(not_sus)}")

# 严重度分布
from collections import Counter
print("severity:", dict(Counter(e["severity"] for e in scan)))
print("patterns:", dict(Counter(p for e in sus for p in e["patterns"])))

# 已知 Bad Case 交叉
known_bad = {"E-0057", "E-0077", "E-0082", "E-0083", "E-0086", "E-0090", "E-0095", "E-0096", "E-0099", "E-0100"}
print("\n已知 Bad Case 中被报警:", [e["case_id"] for e in sus if e["case_id"] in known_bad])
print("已知 Bad Case 中未报警:", sorted(known_bad - {e["case_id"] for e in sus}))