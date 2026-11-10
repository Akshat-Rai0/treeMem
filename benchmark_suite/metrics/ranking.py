"""Retrieval and ranking metrics."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence


def _rel_map(relevant: Sequence[str], graded: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    graded = graded or {}
    return {rid: float(graded.get(rid, 1.0)) for rid in relevant}


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], graded: Optional[Dict[str, float]] = None, k: int = 10) -> float:
    rel = _rel_map(relevant, graded)
    top = list(retrieved)[:k]
    if not top:
        return 0.0
    return sum(rel.get(mid, 0.0) for mid in top) / k


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], graded: Optional[Dict[str, float]] = None, k: int = 10) -> float:
    rel = _rel_map(relevant, graded)
    if not rel:
        return 1.0 if not retrieved else 0.0
    top = set(list(retrieved)[:k])
    return sum(1 for rid in rel if rid in top) / len(rel)


def f1_at_k(retrieved: Sequence[str], relevant: Sequence[str], graded: Optional[Dict[str, float]] = None, k: int = 10) -> float:
    p = precision_at_k(retrieved, relevant, graded, k)
    r = recall_at_k(retrieved, relevant, graded, k)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    rel = set(relevant)
    for i, mid in enumerate(retrieved, 1):
        if mid in rel:
            return 1.0 / i
    return 0.0


def average_precision(retrieved: Sequence[str], relevant: Sequence[str], graded: Optional[Dict[str, float]] = None) -> float:
    rel = _rel_map(relevant, graded)
    if not rel:
        return 0.0
    hits = 0
    score = 0.0
    seen = set()
    for i, mid in enumerate(retrieved, 1):
        if mid in rel and mid not in seen:
            hits += 1
            seen.add(mid)
            score += hits / i
    return score / len(rel)


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], graded: Optional[Dict[str, float]] = None, k: int = 10) -> float:
    rel = _rel_map(relevant, graded)
    if not rel:
        return 0.0
    def dcg(ids: Sequence[str]) -> float:
        return sum((2 ** rel.get(mid, 0.0) - 1) / _log2(i + 1) for i, mid in enumerate(ids[:k], 1))
    ideal = sorted(rel, key=lambda rid: rel[rid], reverse=True)
    denom = dcg(ideal)
    return 0.0 if denom == 0 else dcg(list(retrieved)) / denom


def _log2(x: float) -> float:
    import math
    return math.log(x, 2)


def full_support_rate(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    if not relevant:
        return 1.0
    top = set(retrieved)
    return 1.0 if all(rid in top for rid in relevant) else 0.0


def evaluate_ranking(retrieved: Sequence[str], query: Dict[str, Any], ks=(1, 3, 5, 10)) -> Dict[str, float]:
    relevant = query.get("relevant_memory_ids", [])
    graded = query.get("graded_relevance") or None
    out: Dict[str, float] = {
        "mrr": reciprocal_rank(retrieved, relevant),
        "map": average_precision(retrieved, relevant, graded),
        "full_support": full_support_rate(retrieved, relevant),
    }
    for k in ks:
        out[f"precision@{k}"] = precision_at_k(retrieved, relevant, graded, k)
        out[f"recall@{k}"] = recall_at_k(retrieved, relevant, graded, k)
        out[f"f1@{k}"] = f1_at_k(retrieved, relevant, graded, k)
        out[f"ndcg@{k}"] = ndcg_at_k(retrieved, relevant, graded, k)
    return out


def aggregate_rankings(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    if not rows:
        return {}
    keys = sorted({k for r in rows for k in r.keys() if isinstance(r.get(k), (int, float))})
    out: Dict[str, Any] = {"count": len(rows)}
    for key in keys:
        vals = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        if vals:
            out[key] = sum(vals) / len(vals)
    return out


def group_metrics(rows: Iterable[Dict[str, Any]], key: str = "category") -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key, "unknown"))].append(r)
    return {g: aggregate_rankings(rs) for g, rs in sorted(groups.items())}
