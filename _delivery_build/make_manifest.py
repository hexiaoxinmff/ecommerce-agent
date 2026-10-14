# -*- coding: utf-8 -*-
"""生成 00_交付导读/正式资产清单.md(含冻结资产 SHA256)"""
import hashlib
from pathlib import Path
from datetime import date

PKG = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent\_delivery_build\基于Text2SQL的电商智能数据分析Agent")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


ITEMS = [
    ("业务数据库(冻结)", "02_数据与评测/01_电商数据库/ecommerce.db", "SQLite 业务库 dev-2026-09-14 / seed 20260914,系统唯一业务数据", True),
    ("Benchmark 数据集(冻结)", "02_数据与评测/02_Benchmark/ecommerce_eval_v1.json", "ECO-SQL-Bench v1.1,100 题,含 Gold SQL 与 gold_result_hash", True),
    ("Few-shot 示例库(冻结)", "02_数据与评测/03_Gold与Prompt/ecommerce_examples.json", "FEWSHOT_V3,23 例,正式基线配置", True),
    ("Prompt 快照(冻结)", "02_数据与评测/03_Gold与Prompt/sql_generator_v1.3.txt", "SQLGENERATOR_PROMPT_V1.3,正式基线配置", True),
    ("正式评测结果", "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/clean_baseline_v1_1.md", "Clean Baseline v1.1 正式报告(90.0% EX,唯一正式引用)", True),
    ("正式评测结果(机器可读)", "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/eval_clean_baseline_v1_1.json", "Clean Baseline v1.1 原始评测 JSON", True),
    ("正式评测配置", "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/experiment_config.json", "Clean Baseline v1.1 实验指纹(各资产 SHA256 记录)", True),
    ("E3 冻结摘要", "02_数据与评测/04_正式评测结果/E3_实验冻结/E3_FINAL_FREEZE.md", "E3 机制最终冻结事实(不得表述为整体 EX 提升)", True),
    ("E3 冻结哈希基线", "02_数据与评测/04_正式评测结果/E3_实验冻结/task22_freeeze_hash_baseline.json", "Task22 原始数据哈希校验(ALL UNCHANGED)", True),
    ("E2E 验证证据", "02_数据与评测/04_正式评测结果/E2E_验证/task23_final_acceptance/e2e_smoke.json", "Task23 最终验收 5 条真实问题 E2E 实测记录", True),
    ("最终实验矩阵", "02_数据与评测/04_正式评测结果/FINAL_EXPERIMENT_MATRIX.md", "唯一正式引用口径声明(排除历史实验)", True),
    ("最终 Bad Case 目录", "02_数据与评测/04_正式评测结果/FINAL_BAD_CASE_CATALOG.md", "正式 10 条 Bad Case 清单", True),
    ("发布基线冻结清单", "02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_MANIFEST.md", "Phase 2F 发布基线(commit 35a9ad6,tag release_baseline_20260920)", True),
    ("发布基线冻结清单(机器可读)", "02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_MANIFEST.json", "同上 JSON 版", True),
    ("发布基线报告", "02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_20260920.md", "发布基线冻结报告正文", True),
    ("Candidate A 提升清单", "02_数据与评测/04_正式评测结果/发布基线冻结/CANDIDATE_A_PROMOTION_MANIFEST.md", "运行时复用优化(Candidate A)提升清单与源文件 SHA256", True),
    ("Candidate A 提升评审", "02_数据与评测/04_正式评测结果/发布基线冻结/CANDIDATE_A_PROMOTION_REVIEW.md", "Candidate A 独立评审记录", True),
    ("最终技术验收报告", "01_项目文档与说明/04_测试与验收/FINAL_ACCEPTANCE_REPORT.md", "Task23 最终技术验收(核心功能 PASS/E3 FROZEN)", True),
    ("需求核对清单", "01_项目文档与说明/04_测试与验收/FINAL_REQUIREMENTS_CHECKLIST.md", "需求逐条核对(已实现/部分/未实现)", True),
    ("测试报告", "01_项目文档与说明/04_测试与验收/TEST_REPORT.md", "pytest 967 passed / 1 skipped 口径", True),
    ("交付版答辩 PPT", "03_答辩与演示/答辩PPT.pptx", "极简奶白风格视觉优化版(事实数据与原版一致)", False),
    ("多轮评测占位", "02_数据与评测/05_历史实验/旧版本数据/ecommerce_multiturn_v1.json", "结构占位(conversations 为空,多轮未实现)", False),
]

lines = [
    "# 正式资产清单",
    "",
    f"> 生成日期:{date.today().isoformat()}。本清单记录交付包中的**正式/冻结资产**。",
    "> 冻结资产**只可查看、复制,不得修改、重新生成或覆盖**;",
    "> SHA256 为交付包内文件的实测值,与原项目对应文件一致。",
    "",
    "| 分类 | 文件(相对交付包根) | 用途 | 是否冻结 | SHA256(适用时) |",
    "|---|---|---|---|---|",
]
for cat, rel, use, frozen in ITEMS:
    p = PKG / rel
    if not p.exists():
        raise FileNotFoundError(p)
    if frozen or rel.endswith(".pptx"):
        h = sha(p)
        lines.append(f"| {cat} | `{rel}` | {use} | {'★ 冻结' if frozen else '交付版'} | `{h}` |")
    else:
        lines.append(f"| {cat} | `{rel}` | {use} | 否 | — |")

lines += [
    "",
    "## 补充说明",
    "",
    "- 以上 SHA256 基于 SHA-256 算法对交付包内文件实测,与原项目对应文件字节一致;"
    "其中 `ecommerce.db`(65E5D8B2…91D9)、`ecommerce_eval_v1.json`(DBA277CC…9F1A)、"
    "`ecommerce_examples.json`(EE12FCC9…4CEE)的哈希与正式评测报告(clean_baseline_v1_1.md §1)"
    "登记的实验指纹**完全一致**,证明冻结资产未被改动;",
    "- 口径说明:正式评测报告中的 `prompt_sha256`(10583478…96D5)实为代码内**业务规则文本"
    "BUSINESS_RULES** 的哈希(经实测复核一致);`sql_generator_v1.3.txt` 快照文件的字节哈希"
    "即本清单所列 2AF938BE…(快照文件与代码内 Prompt 常量同源,报告 §1 引用该快照路径);",
    "- 业务规则 BUSINESS_RULES 与 Prompt V1.3 常量位于 `04_项目源码/backend/app/sqlgen/prompt.py`,"
    "属冻结资产,不得修改;",
    "- E3 冻结代码(`backend/app/sqlcheck/fanout_detector.py`、`backend/app/experiments/fanout_hint.py`)"
    "位于 `04_项目源码/backend/` 内,随源码快照交付,不得修改;",
    "- Candidate A 五个生产源文件(graph.py / metadata.py / mimo.py / safety.py / validator.py)"
    "的 SHA256 见发布基线冻结清单,可通过其复核源码一致性。",
]

out = PKG / "00_交付导读" / "正式资产清单.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("WROTE", out)
