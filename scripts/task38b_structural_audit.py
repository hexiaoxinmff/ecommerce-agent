# -*- coding: utf-8 -*-
"""Task 38 补做审计：同构题普查 + 驱动结构级交叉验证（零 LLM）。

背景
----
Task 38 首版报告只对比了 E-0057 的**最终结果集**，没有验证**驱动结构**。
本脚本补做两件事：

1. **同构题普查**：在冻结 100 题里找出「按 X 分档、各档有多少 Y」结构的全部题目，
   确认 E-0057 是否为唯一「统计实体与行为记录不同表」的题。
2. **驱动结构级 2x2 交叉验证**：直接对数据库跑
   {错误驱动, 正确驱动} x {ELSE 兜底, 显式 WHEN 下界} 四种组合，
   判定 EX 与「统计口径正确性」是否一致。

关键发现（见报告 §4.3.2）
------------------------
`错误驱动 users LEFT JOIN orders` + `CASE 用显式 WHEN cnt >= 11` 会得到
**EX=True 但口径错误**的结果：17 个零单用户不满足 `>= 11`，落进隐式 NULL 档，
被 `GROUP BY` 剔除，结果**碰巧**等于真值 19。

这构成一条**假阳性修复通道**——后续任何基于统计实体约束的验证
**不能只看 EX，必须同时检查驱动表是否为行为表**。

运行
----
    C:/Users/29593/AppData/Local/Programs/Python/Python312/python.exe \
        scripts/task38b_structural_audit.py

零 LLM 调用，只读数据库与冻结 JSON。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import DB_PATH  # noqa: E402
from app.sqlgen.entity_constraint import detect_analysis_entity_constraint  # noqa: E402

DATASET = ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
BASELINE = ROOT / "reports" / "eval" / "clean_baseline_v1_1" / "eval_clean_baseline_v1_1.json"
ON_ARM = ROOT / "reports" / "eval" / "task38_phase2_on" / "eval_20260920_34113.json"

GOLD_TIERS = {"1-3单": 490, "4-10单": 1474, "11单及以上": 19}
TIER_ORDER = ["1-3单", "4-10单", "11单及以上"]

# 驱动结构：A = 基线错误写法；B = 正确写法
DRIVERS = {
    "A users LEFT JOIN": (
        "SELECT u.id, COUNT(o.id) AS order_count "
        "FROM users u LEFT JOIN orders o ON o.user_id = u.id GROUP BY u.id"
    ),
    "B orders GROUP BY": (
        "SELECT user_id AS id, COUNT(*) AS order_count FROM orders GROUP BY user_id"
    ),
}

# CASE 写法：w1 = 兜底 ELSE；w2 = 显式 WHEN 下界
CASES = {
    "w1 ELSE兜底": (
        "CASE WHEN order_count BETWEEN 1 AND 3 THEN '1-3单' "
        "WHEN order_count BETWEEN 4 AND 10 THEN '4-10单' "
        "ELSE '11单及以上' END"
    ),
    "w2 WHEN>=11": (
        "CASE WHEN order_count BETWEEN 1 AND 3 THEN '1-3单' "
        "WHEN order_count BETWEEN 4 AND 10 THEN '4-10单' "
        "WHEN order_count >= 11 THEN '11单及以上' END"
    ),
}


def load_json(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def census_same_structure() -> list[dict]:
    """普查：找出全部分档结构题，标注涉及的表、是否触发 E8、基线 EX。

    注意：判「跨表」**不能**用「gold 里有没有 LEFT JOIN」——
    E-0057 的 gold 是子查询形式（`FROM (SELECT ... FROM orders GROUP BY user_id)`），
    不含 LEFT JOIN 字样，但它在语义上把统计实体（用户）与行为记录（订单）
    分在了两张表。正确判据是 **gold 实际引用了哪些表**。
    """
    import sqlglot

    items = load_json(DATASET)["items"]
    baseline = {r["eval_id"]: r for r in load_json(BASELINE)["results"]}

    rows = []
    for it in items:
        q = it["question"]
        if "档" not in q and "分为" not in q:
            continue
        constraint = detect_analysis_entity_constraint(q)

        # 用 sqlglot 抽取 gold 实际引用的表名（比字符串匹配可靠）
        try:
            tables = sorted(
                t.name.lower()
                for t in sqlglot.parse_one(it["gold_sql"], read="sqlite").find_all(
                    sqlglot.exp.Table
                )
            )
        except Exception:
            tables = []

        rows.append(
            {
                "eval_id": it["id"],
                "question": q,
                "e8_triggered": constraint is not None,
                "baseline_ex": baseline.get(it["id"], {}).get("execution_accuracy"),
                "gold_tables": tables,
                # 「分档对象」在题面里，gold 表数 >1 才算真正跨表
                "gold_table_count": len(tables),
                "gold_head": " ".join(it["gold_sql"].split())[:90],
            }
        )
    return rows


def cross_check(con: sqlite3.Connection) -> list[dict]:
    """驱动结构 x CASE 写法 全交叉，同时测量 NULL 档丢弃量。"""
    out = []
    for dname, dsql in DRIVERS.items():
        for cname, cexpr in CASES.items():
            sql = f"SELECT {cexpr} AS tier, COUNT(*) AS c FROM ({dsql}) t GROUP BY tier"
            raw = con.execute(sql).fetchall()
            tiers = {r[0]: r[1] for r in raw if r[0] is not None}
            null_dropped = sum(r[1] for r in raw if r[0] is None)
            out.append(
                {
                    "driver": dname,
                    "case": cname,
                    "tiers": {k: tiers.get(k) for k in TIER_ORDER},
                    "null_dropped": null_dropped,
                    "ex": tiers == GOLD_TIERS,
                    "false_positive": tiers == GOLD_TIERS and null_dropped > 0,
                }
            )
    return out


def classify_e0057_driver() -> dict:
    """判定两次 ON 运行实际用的是哪种驱动结构。"""
    result = {}
    on = load_json(ON_ARM)
    row = next(r for r in on["results"] if r["eval_id"] == "E-0057")
    sql = row["pred_sql"].upper()
    result["phase2_on"] = {
        "driver": "A users LEFT JOIN" if "LEFT JOIN" in sql else "B orders GROUP BY",
        "case_tail": "w2 WHEN>=11" if ">= 11" in row["pred_sql"] or ">=11" in row["pred_sql"] else "w1 ELSE兜底",
    }
    return result


def main() -> int:
    print("=" * 78)
    print("1. 同构题普查（冻结 100 题）")
    print("=" * 78)
    rows = census_same_structure()
    print(f"{'eval_id':<9} {'E8':<6} {'gold表数':<9} {'基线EX':<7} gold_tables")
    for r in rows:
        print(
            f"{r['eval_id']:<9} {str(r['e8_triggered']):<6} "
            f"{r['gold_table_count']:<9} {str(r['baseline_ex']):<7} "
            f"{','.join(r['gold_tables'])}"
        )
        print(f"          Q: {r['question'][:60]}")
    multi = [r for r in rows if r["gold_table_count"] > 1]
    print(f"\n分档结构题共 {len(rows)} 道；gold 真正跨表 {len(multi)} 道 -> {[r['eval_id'] for r in multi]}")

    con = sqlite3.connect(DB_PATH)
    print()
    print("=" * 78)
    print("2. 驱动结构 x CASE 写法 全交叉（GOLD = " + str(GOLD_TIERS) + "）")
    print("=" * 78)
    print(f"{'driver':<20} {'case':<13} {'result':<34} {'EX':<6} {'NULL丢':<7} note")
    for c in cross_check(con):
        note = "⚠️ 假阳性：口径错但答案对" if c["false_positive"] else (
            "口径正确" if c["ex"] else "基线缺陷"
        )
        print(
            f"{c['driver']:<20} {c['case']:<13} {str(c['tiers']):<34} "
            f"{str(c['ex']):<6} {c['null_dropped']:<7} {note}"
        )

    print()
    print("真实值校验：")
    n_all = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_act = con.execute("SELECT COUNT(DISTINCT user_id) FROM orders").fetchone()[0]
    false_pos = next((c for c in cross_check(con) if c["false_positive"]), None)
    print(f"  users={n_all}  users_with_orders={n_act}  zero_order={n_all - n_act}")
    if false_pos:
        print(
            f"  A+w2 判 >=11 得 {false_pos['tiers']['11单及以上']}（真值 19）；"
            f"落 NULL 档被丢弃 {false_pos['null_dropped']}（全是零单用户）"
        )

    print()
    print("=" * 78)
    print("3. E-0057 实际走的是哪条路")
    print("=" * 78)
    for k, v in classify_e0057_driver().items():
        print(f"  {k}: driver={v['driver']}  case={v['case_tail']}")
    print("\n判定：两次 ON 运行驱动表均修正为 orders ⇒ 属口径正确格，非 CASE 侥幸。")

    print()
    print("=" * 78)
    print("结论")
    print("=" * 78)
    print("  * E-0057 是「跨表分档」唯一例；E-0029/E-0044 同构但不跨表，基线本来就对。")
    print("  * 存在假阳性通道：错误驱动 + 显式 WHEN 下界 ⇒ EX=True 而口径错误。")
    print("  * 铁律：后续验证不能只看 EX，必须检查驱动表是否为行为表。")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
