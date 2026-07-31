"""构建 / 重建向量索引：python scripts/build_index.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.ingest import build

if __name__ == "__main__":
    n = build()
    print(f"索引构建完成：共 {n} 个文本块")
