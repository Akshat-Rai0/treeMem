# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (descent gate: premature stops)
- A real run showed the gate stopping at the root for "What hierarchical memory project is the user building?" because the root summary shared the word "memory". The gate now: stems words and drops plain function words; counts a stop as sufficient only when the node summary covers the question's own words (literal match 1.0, synonym match 0.5; `min_stop_coverage=0.5`); prefers a child that matches question words the parent lacks (`specific_term_tiebreak`); and descends when a child scores at least `descend_ratio=0.3` of the parent. `DescentGate.legacy()` restores the old behaviour for comparison.
- `bench/gate_offline_eval.py` (no API calls) measures premature stops on the 12 dev questions plus 26 new held-out questions (`bench/eval/gate_heldout.py`). Results appear in the README, generated from the code. **Not yet confirmed with a real LLM.**

### Fixed (grading)
- The answer grader normalizes Unicode before matching (no-break spaces, curly quotes, dashes) and accepts more phrasings of "not in memory" (for example "don't include any information"). Two correct flat answers from the gpt-oss-120b run were wrongly marked incorrect before this fix.
- `bench/eval/rebuild_aggregate.py --regrade` re-grades saved run files with the current grader (answers and tokens are never changed). Re-grading the three qwen runs changed 0 grades.
- README can show a second model's aggregate from `bench/results_*/llm_eval_aggregate.json`.

### Added (interruption safety)
- `run_eval.py` writes `llm_eval_aggregate.json` and `llm_eval_results.json` after **every** run, and catches rate limits and Ctrl+C, so finished runs are never lost.
- `bench/eval/rebuild_aggregate.py` rebuilds both summary files from `bench/results/llm_eval_runs/run_*.json` with no API calls.
- First real three-arm result committed (`bench/results/llm_eval_runs/run_1..3.json`, `llm_eval_aggregate.json`).

### Added (evaluation and privacy)
- **Server-side reveal policy** (`treemem/reveal_policy.py`): `reveal=true` from an agent is only honored when the operator sets `TREEMEM_ALLOW_REVEAL=1`; otherwise `expand` and `search` return `reveal_denied`. Tests in `tests/test_reveal_policy.py`.
- **Evaluation harness v2**: third arm `tree_follow` (guided descent), `--runs N` with mean and standard deviation (`llm_eval_aggregate.json`), per-run result files, fresh vault copy per run, latency without pacing sleeps. Offline tests with a scripted fake client in `tests/test_eval_harness.py`.
- README generator now also fills the repeated-runs table and the smoke-test block, and shows "Not measured yet" until an aggregate exists.

### Fixed (evaluation)
- The private question is graded as protected when not leaked, and accuracy covers the non-private questions only.
- The negative-control grader no longer accepts any answer containing the word "not".

### Changed
- **Descent gate lexical fallback**: without scikit-learn the combined score now uses 100% lexical weight (previously halved, which made leaf nodes return `search_fallback`). Tests cover both modes.
- **Benchmark numbers are generated**: `bench/make_readme_tables.py` now fills README and `docs/portfolio.md` tables from `bench/results/*.json` and the measured pytest count. No hand-typed benchmark numbers remain.

### Added
- **Guided descent**: `recall(path, query, follow=True, max_depth=3)` follows the gate's suggestions server-side in one call. Read-only, never enters private nodes, emits one `recall` event per step, bounded search fallback (400 tokens). Default `follow=False` is unchanged. Tests in `tests/test_guided_descent.py`.
- `.gitignore` for `.env`, caches, egg-info, runtime lock/event files.

### Security
- **`search` no longer returns facts stored under private nodes** unless `reveal=true` is passed (previously a private fact could be returned by a plain search, and therefore by search fallback).

### Added
- **Heuristic Descent Gate (`src/treemem/descent_gate.py`)**:
  - Predictive Parent-Stop engine scoring `(query, parent_summary, children)` to recommend `stop`, `descend`, or `search_fallback`.
  - Integrates stopword-filtered query expansion and TF-IDF bigram similarity.
  - Automatically evaluated during `recall(path, query)` and exposed to agents via MCP tool layer.
  - 8 unit tests in `tests/test_descent_gate.py`.
- **Task A: Hybrid Semantic Placement (`src/treemem/index.py`)**:
  - Combined BM25 lexical overlap (40%) with TF-IDF bigram cosine similarity (60%) via scikit-learn for memory candidate placement.
  - Returns ranking metadata with `source` field ('hint', 'tfidf', 'bm25') for full interpretability.
  - 10 unit tests in `tests/test_semantic_placement.py`.
- **Task C: Dashboard Editing & UI Action Buttons (`src/treemem/dashboard/`)**:
  - `POST /api/node/compress` endpoint to trigger server-side LLM auto-compression on individual nodes.
  - `POST /api/node/summary` endpoint to overwrite summaries directly from the dashboard with length constraints (≤4000 chars) and token validation.
  - Interactive Inspector action buttons: "⚡ Auto-Compress" (shows for stale/dirty nodes) and "✏️ Edit Summary" modal dialog with keyboard shortcuts (`Esc` to dismiss).
  - 11 unit tests in `tests/test_dashboard_edit.py`.
- **v2 Option B Background Auto-Summarizer (`src/treemem/auto_compress.py`)**:
  - Server-side LLM auto-compression engine that finds and cleans dirty nodes in strict bottom-up topological order.
  - Validation-retry feedback loop (re-prompts LLM with specific validator error if generated summary fails length or child list checks).
  - Background daemon thread worker (`AutoCompressor.start_background_worker`) with periodic cleanup.
  - New CLI command `treemem compress [path]` and `--auto-compress` daemon flag for `treemem serve`.
  - New MCP tool `auto_compress(path?)` for autonomous agent triggering.
  - 4 unit tests in `tests/test_auto_compress.py`.
- **v1.5 Transclusion Engine (`src/treemem/transclusion.py`)**:
  - Dynamic at-read resolution of `![[path#ref]]` embeds in parent summaries.
  - Keyword and tag-based reference resolution (`latest`, `volatile`, entry ID, or topic keyword).
  - Cap enforcement: max 5 transclusion embeds per summary to protect token bounds.
  - Transclusion backlink index (`backlink_index`): tracks which parent summaries embed each child node.
  - Volatile fact flag (`volatile=True` in `place` tool): updating volatile facts does not dirty ancestors that transclude them.
  - Comprehensive unit test suite in `tests/test_transclusion.py`.
- Portfolio and resume highlight document (`docs/portfolio.md`) with empirical metrics from real Groq LLM benchmarks.

## [0.1.1] - 2026-10-23

### Changed
- Relabeled scaling benchmarks explicitly as synthetic vault with scripted descent (tokens only).
- Renamed smoke test script from `longmemeval_subset.py` to `smoke_test.py` and its results to `smoke_test_results.json`.
- Replaced personal data in `examples/sample_memory/` and test fixtures with a fictional persona (`Alex Mercer`).
- Updated README benchmark section to honest interim status.
- Added harness compatibility status table with untested flags across external tools.

### Removed
- Removed legacy `files (1)` folder after ensuring all documentation is preserved in `docs/`.

### Added
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) running pytest and vault health checks across Python 3.10-3.13.
- Enhanced `.gitignore` rules for `.events/`, API secrets, and large benchmark artifacts.

## [0.1.0] - 2026-10-22

### Added
- Initial core implementation of TreeMem hierarchical memory architecture.
- Append-only daily log writer with root-to-leaf atomic lock ordering.
- Cytoscape.js X-Ray dashboard with live Server-Sent Events (SSE).
- FastMCP / MCPServer stdio integration with 10 tools.
- Health validator enforcing all 8 system invariants.
