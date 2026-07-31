"""基于 scikit-learn NearestNeighbors 的向量存储（余弦相似度检索）。
特点：纯 Python 依赖、Windows 友好、无需编译，适合教学 / 演示场景。
生产环境可无缝替换为 FAISS / Milvus 等专用向量库。
"""
import pickle

import numpy as np
from sklearn.neighbors import NearestNeighbors

from config import settings


class VectorStore:
    def __init__(self, dim):
        self.dim = dim
        self.nn = NearestNeighbors(metric="cosine")
        self.texts = []
        self.metas = []
        self._fit = False

    def add(self, vectors, texts, metas):
        X = np.array(vectors, dtype="float32")
        if X.shape[0] == 0:
            return
        self.nn.fit(X)
        self._fit = True
        self.texts.extend(texts)
        self.metas.extend(metas)

    def search(self, vector, k=4):
        if not self._fit:
            return []
        v = np.array([vector], dtype="float32")
        kk = min(k, len(self.texts))
        dist, idx = self.nn.kneighbors(v, n_neighbors=kk)
        results = []
        for d, i in zip(dist[0], idx[0]):
            results.append(
                {
                    "text": self.texts[i],
                    "meta": self.metas[i],
                    # cosine 距离越小越相似，转换为“相似度”便于展示
                    "score": float(1 - d),
                }
            )
        return results

    def save(self, index_path, meta_path):
        with open(index_path, "wb") as f:
            pickle.dump(self.nn, f)
        with open(meta_path, "wb") as f:
            pickle.dump(
                {
                    "texts": self.texts,
                    "metas": self.metas,
                    "dim": self.dim,
                    "_fit": self._fit,
                },
                f,
            )

    @classmethod
    def load(cls, index_path, meta_path):
        store = cls.__new__(cls)
        with open(index_path, "rb") as f:
            store.nn = pickle.load(f)
        with open(meta_path, "rb") as f:
            d = pickle.load(f)
        store.texts = d["texts"]
        store.metas = d["metas"]
        store.dim = d["dim"]
        store._fit = d["_fit"]
        return store
