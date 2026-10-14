# -*- coding: utf-8 -*-
"""交付包完整性审计:04 快照 vs 原项目;冻结资产字节一致性"""
import os
import hashlib

ROOT = r"F:\基于 Text2SQL 的电商智能数据分析 Agent"
PKG = os.path.join(ROOT, "_delivery_build", "基于Text2SQL的电商智能数据分析Agent")
PKG4 = os.path.join(PKG, "04_项目源码")

EXC_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "node_modules",
            ".workbuddy-ai", "_delivery_build", "_task36"}
EXC_FILES = {".env", ".zcodeignore"}


def snap(base):
    out = {}
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in EXC_DIRS]
        for f in fn:
            if f in EXC_FILES or f.endswith((".log", ".pyc")) or f == "app.db":
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, base).replace(os.sep, "/")
            out[rel] = os.path.getsize(p)
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest().upper()


a, b = snap(ROOT), snap(PKG4)
missing = sorted(set(a) - set(b))
extra = sorted(set(b) - set(a))
print("orig files:", len(a), " pkg4 files:", len(b))
print("missing in pkg4:", len(missing))
for m in missing[:15]:
    print("  -", m)
print("extra in pkg4  :", len(extra))
for e in extra[:15]:
    print("  +", e)

print("frozen byte-identical (orig vs pkg4):")
frozen = ["db/ecommerce.db", "data/eval/ecommerce_eval_v1.json",
          "data/fewshot/ecommerce_examples.json", "data/prompts/sql_generator_v1.3.txt",
          "reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md",
          "reports/eval/E3_FINAL_FREEZE.md",
          "reports/RELEASE_BASELINE_MANIFEST.json",
          "reports/基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx"]
for f in frozen:
    p1, p2 = os.path.join(ROOT, f), os.path.join(PKG4, f)
    ok = os.path.exists(p2) and sha(p1) == sha(p2)
    print("  ", "OK " if ok else "FAIL", f)

print("frozen copies in 02_数据与评测:")
pairs = [("db/ecommerce.db", "02_数据与评测/01_电商数据库/ecommerce.db"),
         ("data/eval/ecommerce_eval_v1.json", "02_数据与评测/02_Benchmark/ecommerce_eval_v1.json"),
         ("data/fewshot/ecommerce_examples.json", "02_数据与评测/03_Gold与Prompt/ecommerce_examples.json"),
         ("data/prompts/sql_generator_v1.3.txt", "02_数据与评测/03_Gold与Prompt/sql_generator_v1.3.txt")]
for src, dst in pairs:
    ok = sha(os.path.join(ROOT, src)) == sha(os.path.join(PKG, dst))
    print("  ", "OK " if ok else "FAIL", dst)
