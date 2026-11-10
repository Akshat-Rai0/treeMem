"""Latency, token, and statistical helpers."""
from __future__ import annotations

import math
import random
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] * (c - k) + vals[c] * (k - f)


def summarize_values(values: Iterable[Optional[float]]) -> Dict[str, Optional[float]]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"count": 0, "mean": None, "median": None, "p90": None, "p95": None, "p99": None, "min": None, "max": None, "std": None}
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
    return {
        "count": len(vals),
        "mean": mean,
        "median": percentile(vals, 50),
        "p90": percentile(vals, 90),
        "p95": percentile(vals, 95),
        "p99": percentile(vals, 99),
        "min": min(vals),
        "max": max(vals),
        "std": math.sqrt(var),
    }


def context_summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    token_vals = [r.get("context_tokens") for r in rows]
    summary = summarize_values(token_vals)
    summary["total_context_tokens"] = sum(v for v in token_vals if v is not None)
    return summary


def bootstrap_ci(values: Sequence[float], stat_fn=None, n_boot: int = 1000, seed: int = 7, alpha: float = 0.05) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None, None, None
    stat_fn = stat_fn or (lambda xs: sum(xs) / len(xs))
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        sample = [vals[rng.randrange(len(vals))] for _ in vals]
        stats.append(stat_fn(sample))
    stats.sort()
    lo = stats[int((alpha / 2) * len(stats))]
    hi = stats[min(len(stats) - 1, int((1 - alpha / 2) * len(stats)))]
    return stat_fn(vals), lo, hi


def paired_bootstrap_diff(a: Sequence[float], b: Sequence[float], n_boot: int = 1000, seed: int = 7) -> Dict[str, Optional[float]]:
    pairs = [(float(x), float(y)) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return {"mean_diff": None, "ci_low": None, "ci_high": None, "n": 0}
    diffs = [x - y for x, y in pairs]
    mean, lo, hi = bootstrap_ci(diffs, n_boot=n_boot, seed=seed)
    return {"mean_diff": mean, "ci_low": lo, "ci_high": hi, "n": len(diffs)}


def cohen_d(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    xa = [float(v) for v in a if v is not None]
    xb = [float(v) for v in b if v is not None]
    if len(xa) < 2 or len(xb) < 2:
        return None
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    va = sum((v - ma) ** 2 for v in xa) / (len(xa) - 1)
    vb = sum((v - mb) ** 2 for v in xb) / (len(xb) - 1)
    pooled = math.sqrt(((len(xa) - 1) * va + (len(xb) - 1) * vb) / (len(xa) + len(xb) - 2))
    return None if pooled == 0 else (ma - mb) / pooled
