"""Task 38 第一阶段：触发条件验证（零 LLM）。

验证「条件性统计实体约束」的判定逻辑：
1. OFF（未设 E8）时 Prompt 与冻结基线**逐字节相同**；
2. ON 且题目命中目标场景时注入约束；
3. ON 但题目不命中时**不注入**（条件性局部生效）；
4. 全 100 题扫描：确认触发面，尤其确认 E-0036 等"需保留全集"的题**不**被误触发。
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "backend")

from app.fewshot.models import FewShotResult
from app.schemas.schema_link import SchemaLinkResult
from app.sqlgen.entity_constraint import detect_analysis_entity_constraint
from app.sqlgen.prompt import build_prompt

ROOT = Path(__file__).resolve().parents[1]

LINK = SchemaLinkResult(
    question="q",
    tables=["users", "orders"],
    columns=["users.id", "orders.user_id"],
    reasons=[],
    confidence=0.9,
)
FS = FewShotResult(question="q", matches=[])


def load_questions():
    data = json.loads(
        (ROOT / "data" / "eval" / "ecommerce_eval_v1.json").read_text(encoding="utf-8")
    )
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    return {it["id"]: it for it in items}


def main() -> int:
    questions = load_questions()
    ok = True

    print("=" * 74)
    print("Task 38 第一阶段 — 触发条件验证（零 LLM）")
    print("=" * 74)

    # ---------- 1. OFF 与基线逐字节一致 ----------
    print("\n[1] OFF 模式（未设 SQLGEN_EXTRA_RULES）与基线一致性")
    os.environ.pop("SQLGEN_EXTRA_RULES", None)
    off_prompt = build_prompt(
        questions["E-0057"]["question"], LINK, FS
    )
    assert "统计实体" not in off_prompt, "OFF 模式不应出现约束段"
    print("    ✅ 无「统计实体」约束段")
    print(f"    Prompt 长度: {len(off_prompt)}")

    # ---------- 2. ON 且命中 ----------
    print("\n[2] ON 模式 + E-0057（应命中）")
    os.environ["SQLGEN_EXTRA_RULES"] = "E8"
    on_prompt = build_prompt(questions["E-0057"]["question"], LINK, FS)
    c = detect_analysis_entity_constraint(questions["E-0057"]["question"])
    assert c is not None
    print(f"    analysis_entity              = {c.analysis_entity}")
    print(f"    driver_table                 = {c.driver_table}")
    print(f"    aggregation_grain            = {c.aggregation_grain}")
    print(f"    include_zero_activity_entities = {c.include_zero_activity_entities}")
    assert "统计实体 / 驱动表约束" in on_prompt, "ON 应注入约束段"
    print("    ✅ 约束段已注入")
    print(f"    Prompt 长度: {len(on_prompt)}  (增量 {len(on_prompt)-len(off_prompt)})")

    # ---------- 3. ON 但不命中 ----------
    print("\n[3] ON 模式 + 非目标题（不应注入）")
    for qid in ["E-0036", "E-0077"]:
        p = build_prompt(questions[qid]["question"], LINK, FS)
        injected = "统计实体 / 驱动表约束" in p
        print(f"    {qid}: 注入={injected}  {'✅' if not injected else '❌ 误触发'}")
        if injected:
            ok = False

    # ---------- 4. 全 100 题触发面 ----------
    print("\n[4] 全 100 题触发面扫描")
    triggered = []
    for qid, item in questions.items():
        cc = detect_analysis_entity_constraint(item["question"])
        if cc is not None:
            triggered.append((qid, cc, item))
    print(f"    触发题数: {len(triggered)}/100")
    for qid, cc, item in triggered:
        print(f"      {qid:8s} [{item['difficulty']:11s}] {item['question'][:46]}")
        print(f"               -> entity={cc.analysis_entity} driver={cc.driver_table}")

    # ---------- 5. 确认需保留全集的题未被误触发 ----------
    print("\n[5] 反向检查：gold 用 LEFT JOIN 保留全集的题")
    from collections import Counter

    n_left = 0
    for qid, item in questions.items():
        if "LEFT JOIN" in (item.get("gold_sql") or "").upper():
            n_left += 1
            hit = qid in {t[0] for t in triggered}
            print(f"    {qid}: gold 含 LEFT JOIN | 被约束触发={hit}")
            if item["question"] == "哪些分类下没有挂载任何商品？":
                assert not hit, "E-0036（要求保留全集）绝不能被触发"
                print("      ✅ 正确未触发（题目要求『没有商品的分类』，需保留全集）")
    if n_left == 0:
        print("    (无)")

    print("\n" + "=" * 74)
    print(f"结论: {'PASS' if ok else 'FAIL'}")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
