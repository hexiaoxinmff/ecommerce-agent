"""检索器：加载索引并提供 query -> 相关片段 的接口。"""
from functools import lru_cache

from config import settings
from src.rag.embeddings import embed_query
from src.rag.vector_store import VectorStore


@lru_cache(maxsize=1)
def get_store():
    return VectorStore.load(settings.INDEX_FILE, settings.META_FILE)


def retrieve(query, k=None):
    k = k or settings.RETRIEVE_TOP_K
    store = get_store()
    vec = embed_query(query)
    return store.search(vec, k=k)
