"""Optional local dense, hybrid, and reranked baselines."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..common import ROOT
from ..schemas import MemoryRecord, QueryRecord
from .base import RetrievedItem, RetrievalResult, finalize_result, timer, elapsed_ms, tokens
from .lexical import BM25Retriever

DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _cache_key(memories: Sequence[MemoryRecord], model: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode())
    for m in memories:
        h.update(m.memory_id.encode()); h.update(b"\0"); h.update(m.content.encode()); h.update(b"\0")
    return h.hexdigest()[:24]


def _cache_path(kind: str, key: str) -> Path:
    return ROOT / "benchmark_suite" / "results" / "model_cache" / f"{kind}_{key}.npz"


class DenseRetriever:
    name = "dense"

    def __init__(self, memories: Sequence[MemoryRecord], model: str = DENSE_MODEL):
        self.memories = list(memories)
        self.model_name = model
        self._model = None
        self._embeddings: Optional[np.ndarray] = None
        self._available: Optional[bool] = None
        self._init_ms = 0.0

    def _ensure(self) -> bool:
        if self._available is not None:
            return self._available
        start = timer()
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device="cpu")
            key = _cache_key(self.memories, self.model_name)
            cache = _cache_path("dense", key)
            texts = [f"{m.content} {m.category}" for m in self.memories]
            if cache.exists():
                data = np.load(cache)
                self._embeddings = data["embeddings"].astype(np.float32)
            else:
                self._embeddings = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=64).astype(np.float32)
                cache.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(cache, embeddings=self._embeddings)
            self._available = True
        except Exception:
            self._available = False
            self._embeddings = None
        self._init_ms = elapsed_ms(start)
        return self._available

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        if not self._ensure() or self._embeddings is None:
            return finalize_result(self.name, qid, [], {"retrieve_ms": elapsed_ms(start)}, {"error": "dense model unavailable"}, error="dense model unavailable")
        qvec = self._model.encode([qtext], normalize_embeddings=True, show_progress_bar=False)[0].astype(np.float32)
        sims = self._embeddings @ qvec
        visible = [i for i, m in enumerate(self.memories) if m.sensitivity != "private" or reveal]
        ranked = sorted(visible, key=lambda i: float(sims[i]), reverse=True)[:k]
        items = [RetrievedItem(memory_id=self.memories[i].memory_id, score=float(sims[i]), rank=r, text=self.memories[i].content, path=self.memories[i].path, source="dense") for r, i in enumerate(ranked, 1)]
        return finalize_result(self.name, qid, items, {"retrieve_ms": elapsed_ms(start), "encode_ms": elapsed_ms(start)}, {"model": self.model_name, "init_ms": self._init_ms})


class HybridRetriever:
    name = "hybrid"

    def __init__(self, memories: Sequence[MemoryRecord], dense_model: str = DENSE_MODEL, rrf_k: int = 60):
        self.memories = list(memories)
        self.bm25 = BM25Retriever(memories)
        self.dense = DenseRetriever(memories, dense_model)
        self.rrf_k = rrf_k

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        bm = self.bm25.retrieve(query, k=max(k * 4, 40), reveal=reveal)
        dn = self.dense.retrieve(query, k=max(k * 4, 40), reveal=reveal)
        scores: Dict[str, float] = {}
        texts: Dict[str, MemoryRecord] = {m.memory_id: m for m in self.memories}
        for rank, item in enumerate(bm.items, 1):
            scores[item.memory_id] = scores.get(item.memory_id, 0.0) + 1.0 / (self.rrf_k + rank)
        for rank, item in enumerate(dn.items, 1):
            scores[item.memory_id] = scores.get(item.memory_id, 0.0) + 1.0 / (self.rrf_k + rank)
        ranked_ids = sorted(scores, key=lambda mid: scores[mid], reverse=True)[:k]
        items = [RetrievedItem(memory_id=mid, score=scores[mid], rank=r, text=texts[mid].content, path=texts[mid].path, source="hybrid") for r, mid in enumerate(ranked_ids, 1)]
        return finalize_result(self.name, qid, items, {"retrieve_ms": elapsed_ms(start), "bm25_ms": bm.latency_ms, "dense_ms": dn.latency_ms}, {"rrf_k": self.rrf_k, "dense_available": not dn.error})


class HybridRerankRetriever:
    name = "hybrid_rerank"

    def __init__(self, memories: Sequence[MemoryRecord], candidate_k: int = 50, rerank_k: int = 10, dense_model: str = DENSE_MODEL):
        self.memories = list(memories)
        self.hybrid = HybridRetriever(memories, dense_model=dense_model)
        self.candidate_k = candidate_k
        self.rerank_k = rerank_k
        self._model = None
        self._available: Optional[bool] = None

    def _ensure(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(RERANK_MODEL, device="cpu")
            self._available = True
        except Exception:
            self._available = False
            self._model = None
        return self._available

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        cand = self.hybrid.retrieve(query, k=self.candidate_k, reveal=reveal)
        if not self._ensure() or self._model is None:
            items = cand.items[:k]
            return finalize_result(self.name, qid, items, {"retrieve_ms": elapsed_ms(start), "hybrid_ms": cand.latency_ms}, {"reranker": "unavailable", "candidate_k": self.candidate_k}, error="cross-encoder unavailable")
        texts = {m.memory_id: m.content for m in self.memories}
        pairs = [(qtext, texts.get(item.memory_id, "")) for item in cand.items]
        scores = self._model.predict(pairs, show_progress_bar=False)
        order = sorted(range(len(cand.items)), key=lambda i: float(scores[i]), reverse=True)[:k]
        items = []
        for r, idx in enumerate(order, 1):
            src = cand.items[idx]
            items.append(RetrievedItem(memory_id=src.memory_id, score=float(scores[idx]), rank=r, text=src.text, path=src.path, source="hybrid_rerank"))
        return finalize_result(self.name, qid, items, {"retrieve_ms": elapsed_ms(start), "hybrid_ms": cand.latency_ms, "rerank_ms": elapsed_ms(start)}, {"reranker": RERANK_MODEL, "candidate_k": self.candidate_k})
