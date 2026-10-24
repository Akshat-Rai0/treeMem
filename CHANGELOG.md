# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Learned Descent Gate (`src/treemem/descent_gate.py`)**:
  - Predictive Parent-Stop engine scoring `(query, parent_summary, children)` to recommend `stop`, `descend`, or `search_fallback`.
  - Integrates stopword-filtered query expansion and TF-IDF bigram similarity.
  - Automatically evaluated during `recall(path, query)` and exposed to agents via MCP tool layer.
  - 8 unit tests in `tests/test_descent_gate.py` (71/71 passing).
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
  - 4 unit tests in `tests/test_auto_compress.py` (42/42 passing).
- **v1.5 Transclusion Engine (`src/treemem/transclusion.py`)**:
  - Dynamic at-read resolution of `![[path#ref]]` embeds in parent summaries.
  - Keyword and tag-based reference resolution (`latest`, `volatile`, entry ID, or topic keyword).
  - Cap enforcement: max 5 transclusion embeds per summary to protect token bounds.
  - Transclusion backlink index (`backlink_index`): tracks which parent summaries embed each child node.
  - Volatile fact flag (`volatile=True` in `place` tool): updating volatile facts does not dirty ancestors that transclude them.
  - Comprehensive unit test suite in `tests/test_transclusion.py` (6 tests, 38/38 passing).
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
