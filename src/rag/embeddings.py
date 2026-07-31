"""
嵌入层：优先使用云端嵌入 API（通义千问 text-embedding-v3，OpenAI 兼容），
无 API Key 或 provider 不支持文本 embedding 时，自动降级为本地 hash 向量（保证零成本可演示）。

注意：豆包文本 Embedding 已下线、小米无公开文本 Embedding，因此使用 doubao/xiaomi 时
默认走本地 hash 兜底；若需要真实语义检索，可在 .env 中设置 EMBEDDING_PROVIDER=qwen
并填写通义 Key（EMBED_API_KEY），即可在不更换对话模型的前提下升级检索质量。
"""
import hashlib
from config import settings

import numpy as np


def _mock_embed(texts):
    """本地兜底：字符 + 二元gram 的哈希词袋向量，L2 归一化。"""
    dim = settings.EMBED_DIM
    vecs = []
    for t in texts:
        v = np.zeros(dim, dtype=np.float32)
        chars = list(t) + [t[i:i + 2] for i in range(len(t) - 1)]
        for c in chars:
            h = int(hashlib.md5(c.encode("utf-8")).hexdigest(), 16)
            v[h % dim] += 1.0
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        vecs.append(v)
    return vecs


def _real_embed(texts):
    """调用 OpenAI 兼容 /embeddings 接口批量嵌入（默认通义千问 text-embedding-v3）。"""
    import httpx

    base_url = (settings.EMBED_BASE_URL or settings.QWEN_EMBED_BASE_URL).rstrip("/")
    url = base_url + "/embeddings"
    api_key = settings.EMBED_API_KEY or settings.API_KEY
    model = settings.EMBED_MODEL or settings.QWEN_EMBED_MODEL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    vecs = []
    for i in range(0, len(texts), 10):
        batch = texts[i:i + 10]
        resp = httpx.post(
            url,
            headers=headers,
            json={"model": model, "input": batch},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])
        for d in data:
            vecs.append(np.array(d["embedding"], dtype=np.float32))
    return vecs


def embed_texts(texts):
    if settings.USE_REAL_EMBED:
        return _real_embed(texts)
    return _mock_embed(texts)


def embed_query(text):
    return embed_texts([text])[0]
