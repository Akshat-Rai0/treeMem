# Scaling Benchmark Status

This status is derived only from `progress.jsonl`. Duplicate episode keys are
deduplicated by `(size, arm, run, question_id)`, keeping the latest line.

## Reconciliation

- Raw lines: 305
- Unique episode keys: 305
- Duplicate lines removed: 0
- Total episodes: 305
- By size: 50 = 139, 200 = 161, 1000 = 5, 5000 = 0

The earlier `192+173+5+0=370` and `321` totals were stale report values, not
counts from the current `progress.jsonl`; no duplicate or size-label bug is
present in the current file.

## Lines per (size, arm, run)

| Size | Arm | Run | Lines |
|---:|---|---:|---:|
| 50 | flat | 1 | 46 |
| 50 | flat | 2 | 46 |
| 50 | flat | 3 | 38 |
| 50 | tree_follow | 1 | 3 |
| 50 | rag_bm25 | 1 | 3 |
| 50 | rag_bm25_k10 | 1 | 3 |
| 200 | flat | 1 | 46 |
| 200 | tree_follow | 1 | 46 |
| 200 | rag_bm25 | 1 | 46 |
| 200 | rag_bm25_k10 | 1 | 23 |
| 1000 | rag_bm25 | 1 | 5 |

All omitted `(size, arm, run)` cells have zero lines.
