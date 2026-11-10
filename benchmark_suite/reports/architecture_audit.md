# TreeMem Architecture Audit

## Status legend
- **implemented**: present in `src/treemem` and exercised by tests or code paths.
- **optional**: requires explicit configuration/provider/credentials.
- **experimental**: present but not part of the default retrieval path.
- **unsupported**: requested benchmark behavior has no native TreeMem API.
- **benchmark-blocking**: would invalidate measurements if left unchanged.

## Capability matrix

| Capability | Status | Evidence / notes |
|---|---|---|
| Append-only log ingestion | implemented | `TreeManager.remember` -> `LogWriter.append`; daily Markdown logs. |
| Hierarchical node storage | implemented | `Store` reads/writes `summary.md` with YAML frontmatter; atomic temp+rename. |
| Placement and dirty propagation | implemented | `TreeManager.place`; `.placements.jsonl`; ancestor dirty flags. |
| Parent-first recall | implemented | `TreeManager.recall(path, query, follow=False)` returns summary+teasers only. |
| Guided traversal | implemented | `_guided_recall` + `DescentGate`; bounded by `max_depth`. |
| Parent-Stop | implemented | Gate `stop` action returns current parent payload. |
| Search fallback | implemented | Guided descent calls bounded `search` on `search_fallback`. |
| BM25 | implemented | `SearchIndex` uses `BM25Okapi` over entries and nodes. |
| TF-IDF candidate scoring | optional | Requires `scikit-learn`; used for placement/gate scoring. |
| Dense embeddings | optional | `EmbeddingProvider`; local sentence-transformers or explicit remote provider. |
| Cross-encoder reranking | unsupported natively | No TreeMem reranker; benchmark supplies `hybrid_rerank` baseline only. |
| RRF hybrid retrieval | unsupported natively | No TreeMem RRF; benchmark supplies `hybrid` baseline. |
| MCP tools | implemented | `remember/place/recall/expand/compress/commit_summary/auto_compress/search/split/rebuild/status`. |
| Compression/summarization | optional | `AutoCompressor` needs an LLM caller/Groq credentials. |
| Persistence/crash recovery | implemented | Atomic writes, append-only log, `.placements.jsonl`, `rebuild`, health checks. |
| Privacy/access control | implemented | Node sensitivity inheritance, withheld hits, reveal policy, private-aware embeddings. |
| Dashboard/observability | implemented with fix | Dashboard exists; compress endpoint had an `AutoCompressor(api_key=...)` blocker, fixed by passing `GroqSummarizerClient.generate` as `llm_caller`. |
| Update/delete lifecycle | partial | Append/replace via `place`, supersession is benchmark metadata; no general delete API. |
| Concurrency | implemented | File locks with root-to-leaf ordering; tests cover concurrent writers. |

## Retrieval pipeline traces

- **Manual TreeMem**: benchmark policy repeatedly calls `recall(follow=False)`, greedily chooses child by teaser overlap, then `expand` on the final node. No server-side gate.
- **Guided TreeMem**: `recall(follow=True)` -> `_guided_recall` -> `DescentGate` -> `descend|stop|search_fallback|leaf|private|max_depth`.
- **Search-only TreeMem**: `TreeManager.search` -> `SearchIndex.query` -> BM25 + overlap/exact bonuses + optional dense similarity. This is **not pure BM25**.
- **Pure BM25 baseline**: benchmark-owned `BM25Okapi` over canonical memory text.
- **Dense/hybrid/rerank baselines**: benchmark-owned adapters; TreeMem is not modified to add RRF or cross-encoder reranking.

## Result-affecting parameters

- `recall(..., follow, max_depth, reveal)`
- `DescentGate`: `parent_stop_threshold`, `min_stop_coverage`, `descend_delta`, `descend_floor`, `descend_ratio`, `specific_term_tiebreak`, `tiebreak_margin`, `eager_descent`
- `search(..., limit, reveal)`
- `EmbeddingProvider` model/dimension/cache/privacy masking
- `Store.lock_paths` timeout and ordering
- `commit_summary` 150-token cap, exact child parity, optimistic `expected_updated`, privacy leak scan
- `children_cap` (default 12), max path depth 8, tokenizer mode
- Benchmark-only: `k`, candidate pool, RRF `k`, reranker model, manual step budget, guided `max_depth`

## Known limitations

- Guided retrieval returns only the final payload plus traversal metadata; intermediate node payloads are timed but not exposed as context.
- Manual traversal is a deterministic benchmark policy, not an LLM agent; comparisons must disclose this asymmetry.
- TreeMem has no native update/delete lifecycle beyond append/replace/journal/rebuild semantics.
- Dense and reranked arms are optional and may be unavailable without model downloads; they are marked `error` rather than silently substituted.
- Synthetic datasets improve ground-truth control but may not represent real user memory distributions.

## Minimal core fixes made

- `src/treemem/dashboard/server.py`: `/api/node/compress` now constructs `GroqSummarizerClient(keys=[groq_key])` and passes `summarizer.generate` to `AutoCompressor(llm_caller=...)`, fixing an unsupported `api_key` argument.
