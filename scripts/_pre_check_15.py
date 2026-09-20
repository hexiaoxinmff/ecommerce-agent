# -*- coding: utf-8 -*-
"""Task 15 运行前实验指纹快照（只读，不改任何实验对象）。"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def sha256_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


db = ROOT / "db" / "ecommerce.db"
ds = ROOT / "data" / "eval" / "ecommerce_eval_v1.json"
fs = ROOT / "data" / "fewshot" / "ecommerce_examples.json"

print("DB SHA256:          ", sha256_file(db))
print("dataset SHA256:     ", sha256_file(ds))
print("fewshot SHA256:     ", sha256_file(fs))

from app.sqlgen.prompt import BUSINESS_RULES  # noqa: E402
print("prompt(BR) SHA256:  ", hashlib.sha256(BUSINESS_RULES.encode("utf-8")).hexdigest().upper())

import json  # noqa: E402
meta = json.loads(ds.read_text(encoding="utf-8"))["metadata"]
print("dataset version:    ", meta["version"])
print("seed:               ", meta["seed"])
print("database_version:   ", meta["database_version"])
print("schema_version:     ", meta["schema_version"])

fs_data = json.loads(fs.read_text(encoding="utf-8"))
print("fewshot count:      ", len(fs_data))