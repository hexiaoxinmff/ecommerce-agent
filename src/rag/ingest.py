"""知识库建库：读取 markdown -> 分段 -> 嵌入 -> 写入 FAISS 索引。"""
import re

from config import settings
from src.rag.embeddings import embed_texts
from src.rag.vector_store import VectorStore


def _load_docs():
    """按 '## ' 二级标题切分为独立文档片段。"""
    docs = []
    for f in sorted(settings.KB_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        page_title = text.splitlines()[0].lstrip("# ").strip() if text else f.stem
        parts = re.split(r"\n## ", text)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            lines = p.splitlines()
            sec_title = lines[0].lstrip("# ").strip()
            body = "\n".join(lines[1:]).strip()
            content = f"{sec_title}\n{body}".strip() if body else sec_title
            docs.append(
                {"source": f.name, "title": sec_title or page_title, "text": content}
            )
    return docs


def _chunk(text, size, overlap):
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += size - overlap
    return chunks


def build():
    raw = _load_docs()
    texts, metas = [], []
    for d in raw:
        for c in _chunk(d["text"], settings.CHUNK_SIZE, settings.CHUNK_OVERLAP):
            texts.append(c)
            metas.append({"source": d["source"], "title": d["title"]})
    vectors = embed_texts(texts)
    store = VectorStore(len(vectors[0]))
    store.add(vectors, texts, metas)
    store.save(settings.INDEX_FILE, settings.META_FILE)
    return len(texts)


if __name__ == "__main__":
    n = build()
    print(f"索引构建完成：共 {n} 个文本块（mock 模式={settings.MOCK_MODE}）")
