# -*- coding: utf-8 -*-
"""Phase 6：交付包 ZIP 最终完整性检查。
1. zipfile 完整性（testzip）；
2. ZIP 文件集合 ↔ 交付目录文件集合逐一对等；
3. ZIP 内 21/21 冻结资产 SHA256 复验（直接读 ZIP 成员，不经目录）；
4. 关键交付物在场检查。
"""
import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent")
PKG = ROOT / "_delivery_build" / "基于Text2SQL的电商智能数据分析Agent"
ZIP = ROOT / "_delivery_build" / "Text2SQL电商智能数据分析Agent_v1.0.0.zip"
MANIFEST = PKG / "00_交付导读" / "正式资产清单.md"
PREFIX = "基于Text2SQL的电商智能数据分析Agent/"

REQUIRED = [
    "00_交付导读/交付说明.md",
    "00_交付导读/正式资产清单.md",
    "00_交付导读/项目交接说明.md",
    "03_答辩与演示/答辩PPT.pptx",
    "03_答辩与演示/PPT文字记录.md",
    "03_答辩与演示/Demo演示脚本.md",
    "03_答辩与演示/答辩QA预案.md",
    "03_答辩与演示/答辩检查清单.md",
    "04_项目源码/README.md",
    "04_项目源码/.env.example",
    "04_项目源码/reports/eval/eval_20260927_28404.md",
    "05_部署运行版/启动说明.md",
    "05_部署运行版/README.md",
    "05_部署运行版/.env.example",
    "05_部署运行版/backend",
    "05_部署运行版/frontend",
    "02_数据与评测/01_电商数据库/ecommerce.db",
    "02_数据与评测/02_Benchmark/ecommerce_eval_v1.json",
    "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/clean_baseline_v1_1.md",
    "06_历史归档",
    "【项目参数】Text2SQL电商智能数据分析Agent_v1.0.0.md",
]


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest().upper()


def main():
    z = zipfile.ZipFile(ZIP)
    bad = z.testzip()
    print("zip integrity (testzip):", "PASS" if bad is None else f"FAIL at {bad}")

    names = sorted(n for n in z.namelist() if not n.endswith("/"))
    folder = sorted(
        PREFIX + p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*") if p.is_file())
    print(f"zip files: {len(names)}  folder files: {len(folder)}")
    print("file set equality:", "PASS" if names == folder else "FAIL")
    if names != folder:
        only_zip = set(names) - set(folder)
        only_dir = set(folder) - set(names)
        for x in list(only_zip)[:5]:
            print("  only in ZIP:", x)
        for x in list(only_dir)[:5]:
            print("  only in dir:", x)

    rows = re.findall(r"^\| (.+?) \| `(.+?)` \| .+? \| .+? \| `([0-9A-F]{64})` \|$",
                      MANIFEST.read_text(encoding="utf-8"), re.M)
    ok = 0
    for _cat, rel, expected in rows:
        member = PREFIX + rel
        try:
            actual = sha_bytes(z.read(member))
        except KeyError:
            print("FAIL missing in zip:", rel)
            continue
        if actual != expected:
            print(f"FAIL hash mismatch: {rel}")
            continue
        ok += 1
    print(f"frozen assets in ZIP: {ok}/{len(rows)} SHA256 一致")

    missing = [r for r in REQUIRED
               if (PREFIX + r) not in set(names) and not any(n.startswith(PREFIX + r + "/") for n in names)]
    print("required deliverables:", "PASS (all present)" if not missing else f"MISSING: {missing}")

    first_level = sorted(set(n[len(PREFIX):].split("/")[0] for n in names))
    print("first level:", first_level)

    all_pass = bad is None and names == folder and ok == len(rows) == 21 and not missing
    print(f"\nFINAL_ZIP_CHECK={'PASS' if all_pass else 'FAIL'}")
    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
