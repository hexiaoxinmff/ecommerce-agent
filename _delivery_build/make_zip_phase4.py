# -*- coding: utf-8 -*-
"""Phase 4：重新生成交付包 ZIP（名称与第一层目录名保持不变）。"""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent")
PKG = ROOT / "_delivery_build" / "基于Text2SQL的电商智能数据分析Agent"
OUT = ROOT / "_delivery_build" / "Text2SQL电商智能数据分析Agent_v1.0.0.zip"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    if OUT.exists():
        OUT.unlink()
    files = sorted(p for p in PKG.rglob("*") if p.is_file())
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            arc = "基于Text2SQL的电商智能数据分析Agent/" + p.relative_to(PKG).as_posix()
            zf.write(p, arc)
    print("files:", len(files))
    print("zip:", OUT)
    print("zip size bytes:", OUT.stat().st_size)
    print("zip sha256:", sha256(OUT))


if __name__ == "__main__":
    main()
