# -*- coding: utf-8 -*-
"""Phase 4：复核交付包内 21 个带 SHA256 的冻结资产。
1. 解析 00_交付导读/正式资产清单.md 中的 SHA256 表；
2. 对交付包内文件重算 SHA256 并与清单值比对；
3. 对可映射回原项目的文件，再与原项目字节比对。
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent")
PKG = ROOT / "_delivery_build" / "基于Text2SQL的电商智能数据分析Agent"
MANIFEST = PKG / "00_交付导读" / "正式资产清单.md"

# 清单相对路径 -> 原项目相对路径（不一致时给出映射）
PKG_TO_ORIG = {
    "02_数据与评测/01_电商数据库/ecommerce.db": "db/ecommerce.db",
    "02_数据与评测/02_Benchmark/ecommerce_eval_v1.json": "data/eval/ecommerce_eval_v1.json",
    "02_数据与评测/03_Gold与Prompt/ecommerce_examples.json": "data/fewshot/ecommerce_examples.json",
    "02_数据与评测/03_Gold与Prompt/sql_generator_v1.3.txt": "data/prompts/sql_generator_v1.3.txt",
    "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/clean_baseline_v1_1.md": "reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md",
    "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/eval_clean_baseline_v1_1.json": "reports/eval/clean_baseline_v1_1/eval_clean_baseline_v1_1.json",
    "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/experiment_config.json": "reports/eval/clean_baseline_v1_1/experiment_config.json",
    "02_数据与评测/04_正式评测结果/E3_实验冻结/E3_FINAL_FREEZE.md": "reports/eval/E3_FINAL_FREEZE.md",
    "02_数据与评测/04_正式评测结果/E3_实验冻结/task22_freeeze_hash_baseline.json": "reports/eval/task22_freeeze_hash_baseline.json",
    "02_数据与评测/04_正式评测结果/E2E_验证/task23_final_acceptance/e2e_smoke.json": "reports/eval/task23_final_acceptance/e2e_smoke.json",
    "02_数据与评测/04_正式评测结果/FINAL_EXPERIMENT_MATRIX.md": "reports/FINAL_EXPERIMENT_MATRIX.md",
    "02_数据与评测/04_正式评测结果/FINAL_BAD_CASE_CATALOG.md": "reports/FINAL_BAD_CASE_CATALOG.md",
    "02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_MANIFEST.md": "reports/RELEASE_BASELINE_MANIFEST.md",
    "02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_MANIFEST.json": "reports/RELEASE_BASELINE_MANIFEST.json",
    "02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_20260920.md": "reports/RELEASE_BASELINE_20260920.md",
    "02_数据与评测/04_正式评测结果/发布基线冻结/CANDIDATE_A_PROMOTION_MANIFEST.md": "reports/CANDIDATE_A_PROMOTION_MANIFEST.md",
    "02_数据与评测/04_正式评测结果/发布基线冻结/CANDIDATE_A_PROMOTION_REVIEW.md": "reports/CANDIDATE_A_PROMOTION_REVIEW.md",
    "01_项目文档与说明/04_测试与验收/FINAL_ACCEPTANCE_REPORT.md": "reports/FINAL_ACCEPTANCE_REPORT.md",
    "01_项目文档与说明/04_测试与验收/FINAL_REQUIREMENTS_CHECKLIST.md": "reports/FINAL_REQUIREMENTS_CHECKLIST.md",
    "01_项目文档与说明/04_测试与验收/TEST_REPORT.md": "docs/TEST_REPORT.md",
    # 交付版 PPT：第三阶段生成的「极简奶白风格视觉优化版」，清单按其自身字节登记，
    # 与原版 PPT（reports/…pptx，保留于 04_项目源码 快照）字节不同是设计意图，
    # 故本文件只做「清单 vs 交付包」校验，不做原项目映射校验。
    "03_答辩与演示/答辩PPT.pptx": None,
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    rows = re.findall(r"^\| (.+?) \| `(.+?)` \| .+? \| .+? \| `([0-9A-F]{64})` \|$", 
                      MANIFEST.read_text(encoding="utf-8"), re.M)
    print("manifest hashed rows:", len(rows))
    assert len(rows) == 21, f"expected 21 hashed rows, got {len(rows)}"
    ok = 0
    for _cat, rel, expected in rows:
        p = PKG / rel
        if not p.exists():
            print("FAIL missing:", rel)
            continue
        actual = sha(p)
        if actual != expected:
            print(f"FAIL hash mismatch: {rel}\n  manifest={expected}\n  actual  ={actual}")
            continue
        orig_rel = PKG_TO_ORIG.get(rel)
        if orig_rel:
            op = ROOT / orig_rel
            if not op.exists():
                print("WARN no orig:", orig_rel)
                continue
            if sha(op) != actual:
                print(f"FAIL orig mismatch: {orig_rel}")
                continue
        ok += 1
        print(f"OK  {rel}")
    print(f"\nRESULT: {ok}/21 SHA256 一致（交付包内 + 原项目双校验）")
    if ok != 21:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
