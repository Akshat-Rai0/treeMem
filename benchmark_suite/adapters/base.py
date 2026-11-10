"""Common retrieval adapter contracts."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

from treemem.tokenizer import count_tokens, tokenizer_is_fallback, tokenizer_name

from ..schemas import MemoryRecord, QueryRecord

_WORD_RE = re.compile(r"\b\w+\b")


def tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def privacy_visible(mem: MemoryRecord, reveal: bool = False) -> bool:
    if reveal:
        return True
    mode = mem.provenance.get("privacy_mode", "public")
    return mem.sensitivity != "private" and mode not in {"private", "inherited_private", "unplaced_private"}


def visible_memories(memories: Sequence[MemoryRecord], reveal: bool = False) -> List[MemoryRecord]:
    return [m for m in memories if privacy_visible(m, reveal)]


@dataclass
class RetrievedItem:
    memory_id: str
    score: float
    rank: int
    text: str
    path: str = ""
    source: str = ""
    entry_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "score": self.score,
            "rank": self.rank,
            "text": self.text,
            "path": self.path,
            "source": self.source,
            "entry_id": self.entry_id,
            "metadata": self.metadata,
        }


@dataclass
class RetrievalResult:
    arm: str
    query_id: str
    items: List[RetrievedItem]
    context_text: str
    context_tokens: int
    latency_ms: float
    timings_ms: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arm": self.arm,
            "query_id": self.query_id,
            "items": [i.to_dict() for i in self.items],
            "retrieved_memory_ids": [i.memory_id for i in self.items],
            "context_text": self.context_text,
            "context_tokens": self.context_tokens,
            "latency_ms": self.latency_ms,
            "timings_ms": self.timings_ms,
            "metadata": self.metadata,
            "error": self.error,
            "tokenizer": tokenizer_name(),
            "tokenizer_fallback": tokenizer_is_fallback(),
        }


class Retriever(Protocol):
    name: str

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        ...


def context_from_items(items: Sequence[RetrievedItem], include_paths: bool = True) -> str:
    parts = []
    for i, item in enumerate(items, 1):
        prefix = f"[{i}] "
        if include_paths and item.path:
            prefix += f"path={item.path} "
        parts.append(prefix + item.text.strip())
    return "\n\n".join(parts)


def finalize_result(
    arm: str,
    query: QueryRecord | str,
    items: Sequence[RetrievedItem],
    timings_ms: Optional[Dict[str, float]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> RetrievalResult:
    qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
    ranked = []
    for rank, item in enumerate(items, 1):
        it = RetrievedItem(**{**item.__dict__, "rank": rank}) if not isinstance(item, RetrievedItem) else item
        it.rank = rank
        ranked.append(it)
    context = context_from_items(ranked)
    return RetrievalResult(
        arm=arm,
        query_id=qid,
        items=ranked,
        context_text=context,
        context_tokens=count_tokens(context),
        latency_ms=sum((timings_ms or {}).values()),
        timings_ms=timings_ms or {},
        metadata=metadata or {},
        error=error,
    )


def timer() -> float:
    return time.perf_counter()


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
