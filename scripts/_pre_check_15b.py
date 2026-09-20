# -*- coding: utf-8 -*-
"""Task 15 前置：精确验证 hash 100/100 + DB 行数 + DB sha256（只读）。"""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from evaluation.normalization import gold_hash  # noqa: E402

ds = json.loads((ROOT / "data" / "eval" / "ecommerce_eval_v1.json").read_text(encoding="utf-8"))
items = ds["items"]

mismatch = []
with closing(sqlite3.connect(r"file:db/ecommerce.db?mode=ro", uri=True)) as c:
    for it in items:
        cur = c.execute(it["gold_sql"])
        cols = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        h = gold_hash(cols, rows)
        if h != it["gold_result_hash"]:
            mismatch.append(it["id"])
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("users", "categories", "products", "orders", "order_items")}

print("gold hash mismatch:", mismatch if mismatch else "NONE (100/100 PASS)")
print("行数:", counts)

db_sha = hashlib.sha256((ROOT / "db" / "ecommerce.db").read_bytes()).hexdigest().upper()
print("DB SHA256:", db_sha)
assert db_sha == "65E5D8B2727CFA064174F9A08AA7D4B08209E0EDD1EBA81F3155698F1A4491D9", "DB 不一致!"
assert counts == {"users": 2000, "categories": 30, "products": 500,
                  "orders": 10000, "order_items": 30457}, "行数不一致!"
assert not mismatch, "hash 存在漂移"
print("前置检查全部 PASS")