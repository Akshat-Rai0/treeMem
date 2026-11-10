"""Flat and pure lexical retrieval baselines."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from rank_bm25 import BM25Okapi

from ..schemas import MemoryRecord, QueryRecord
from .base import RetrievedItem, RetrievalResult, finalize_result, timer, elapsed_ms, tokens, visible_memories


class FlatAllRetriever:
    name = "flat_all"

    def __init__(self, memories: Sequence[MemoryRecord]):
        self.memories = list(memories)

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        visible = visible_memories(self.memories, reveal)
        items = [
            RetrievedItem(memory_id=m.memory_id, score=1.0, rank=i, text=m.content, path=m.path, source="flat_all")
            for i, m in enumerate(visible, 1)
        ]
        # flat_all intentionally ignores k for context measurement; retrieval metrics use all ids.
        return finalize_result(self.name, qid, items, {"retrieve_ms": elapsed_ms(start)}, {"visible_count": len(visible)})


class BM25Retriever:
    """Pure BM25Okapi baseline over canonical memory text."""

    name = "bm25"

    def __init__(self, memories: Sequence[MemoryRecord]):
        self.memories = list(memories)
        self.docs = [tokens(f"{m.content} {m.category} {m.path}") for m in self.memories]
        self.bm25 = BM25Okapi(self.docs) if self.docs else None

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        qtoks = tokens(qtext)
        visible_idx = [i for i, m in enumerate(self.memories) if m.sensitivity != "private" or reveal]
        items: List[RetrievedItem] = []
        if self.bm25 is not None and qtoks:
            scores = self.bm25.get_scores(qtoks)
            ranked = sorted(visible_idx, key=lambda i: float(scores[i]), reverse=True)
            for rank, idx in enumerate(ranked[:k], 1):
                m = self.memories[idx]
                items.append(RetrievedItem(memory_id=m.memory_id, score=float(scores[idx]), rank=rank, text=m.content, path=m.path, source="bm25"))
        return finalize_result(self.name, qid, items, {"retrieve_ms": elapsed_ms(start), "index_ms": 0.0}, {"k": k})
