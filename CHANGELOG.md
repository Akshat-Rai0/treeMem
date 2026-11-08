# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Pass 6: Agent-in-the-Loop Evaluation Kit v2)
- **v2 composite questions** (`bench/make_scaled_vault.py`): Overview questions phrased with internal generator path names replaced by 10 composite questions combining 3 distinct facts from a public leaf without taxonomy labels. Non-overview items copied unchanged. Added `--questions-v2` CLI flag, `questions_v2_path`, `manifest_v2_path`. Tests: `tests/test_fix6_questions_v2.py`.
- **v2 prompts and batches** (`bench/agent_eval/make_batches.py`): Minimum-effort rule requiring 3 distinctive-word lookups plus one broader attempt before abstaining; arm-specific tips; composite question answering rule; evidence output requirement in JSON schema. Batches 01 to 04 contain the 40 answerable questions, batch 05 contains the 10 safety questions. Manifest records `"protocol": "v2"` and `"evidence_required": true`. Tests: `tests/test_fix6_batches_v2.py`.
- **v2 offline grader and grounding audit** (`bench/agent_eval/grade_agent_answers.py`): Evidence grounding verification line-by-line against vault log facts (`grounded_correct`, `ungrounded_correct`, `missing_evidence`, `fabricated_evidence`). Pre-registered decision rule with Bonferroni correction for 3 comparisons ($p < 0.0167$). Safety batch reported as `safety: not run` when omitted without penalizing answerable accuracy. Added `--compare-with` option comparing common v1 lookups across runs. Tool calls per question reported in audit. Tests: `tests/test_fix6_grade_v2.py`.
- **Failure listing and e2e integration** (`bench/agent_eval/list_failures.py`): Prints failed answerable questions with question, expected keywords, gold facts, answer, evidence, grounding status, and count breakdown by reason (abstained vs other). Works across v1 and v2 runs. Tests: `tests/test_fix6_list_failures.py` and `tests/test_fix6_e2e_v2.py`.
- **Protocol documentation** (`docs/agent_eval_protocol.md`): Updated protocol specification documenting instrument problems, v2 workflow, session plan, and pre-registered decision rules.

### Fixed (Critical Security and Correctness Bugs)
- **WP1: Log truncation on "|" (data loss)** - Fixed log line parsing to properly escape backslashes and pipes. Facts containing "|" are now correctly round-tripped. Line numbering uses highest parsed line number + 1, not count of lines. Added 6 regression tests in `tests/test_fix_log_escaping.py`.
- **WP2: Path traversal** - Added comprehensive path validation rejecting "..", ".", absolute paths, backslashes, NUL, segments starting with ".", and the reserved "log" segment. Maximum depth enforced at 8. Defense-in-depth check in `Store.node_dir()` ensures resolved paths stay inside root. `split()` validates group and child names before mutation. Dashboard maps ValueError to HTTP 400. Added 8 regression tests in `tests/test_fix_path_traversal.py`.
- **WP3: Privacy: one rule everywhere** - Implemented `TreeManager.is_private()` that checks node and all ancestors. Privacy is inherited by descendants. Private content withheld from recall, expand, compress, search, and index unless reveal is granted via `TREEMEM_ALLOW_REVEAL=1`. AutoCompressor never sends private content to external LLMs without grant. Events persist query length and SHA256 prefix instead of raw query text. Leak validator fixed to match whole words only, numeric tokens only with 3+ digits. Added 3 regression tests in `tests/test_fix_privacy_boundaries.py`.
- **WP4: split and rebuild** - `split()` now preserves ungrouped children with their teasers. Placement journal (.placements.jsonl) records sensitivity for rebuild. `rebuild()` is idempotent, uses journal as primary source, falls back to hints with sensitivity from log, returns errors instead of bare except. Added 2 regression tests in `tests/test_fix_rebuild_split.py`.
- **WP5: Multi-process safety in Store** - Temp file naming uses PID + UUID for uniqueness. Lock file naming uses SHA1 hash of path to avoid "a/b" vs "a__b" collision. Cleanup deletes only .tmp files older than 60 seconds. Added 2 regression tests in `tests/test_fix_store_safety.py`.
- **WP6: Live dashboard inside the MCP process** - CLI `--mcp` now starts dashboard in daemon thread sharing same TreeManager instance. Dashboard URL printed to stderr and written to `.dashboard_url` with mode 0600. EventBus uses `loop.call_soon_threadsafe()` for thread-safe event delivery. Added 1 regression test in `tests/test_fix_events_threadsafe.py`.
- **WP8: Portability and tokenizer honesty** - fcntl imports wrapped with platform guard, raises `RuntimeError("TreeMem currently supports macOS and Linux only")` at startup. `tokenizer_is_fallback()` exposed. Fallback uses 1.3x conservative multiplier. `status()` and `/api/health` report `"tokenizer": "fallback"` with warning. Added 1 regression test in `tests/test_fix_tokenizer_reporting.py`.

### Fixed (Pass 4: benchmark instrument and scalability)
- **Scaled-vault generator rewritten** (`bench/make_scaled_vault.py`, `scaled_vault_v2`). The old one built the size-50 vault from the first 50 facts of the pool (travel only) while questions came from a different pool, so benchmark questions were not answerable from the vault. Now every size covers 9 to 12 topics, private questions target real private facts, every answer is unique in its vault, and the manifest carries sha256 hashes. Tests: `tests/test_fix4_scaled_vault.py`.
- **Runner safety** (`bench/run_scaling.py`): episodes are stamped with question and vault hashes and a resume refuses to mix them (`--invalidate-stale`); transient failures are retried instead of stored as wrong answers; one vault copy and index per (size, arm, run). Tests: `tests/test_fix4_run_scaling.py`.
- **Sanity gate** (`bench/sanity_check.py`): oracle arm (at least 95%) and flat arm at size 50 (at least 90%) using each question's gold facts; writes `bench/results_scaling/sanity.json`.
- **Log scaling.** `LogWriter.append` and `get_entry` re-parsed the whole day file on every call (quadratic); they now use a stat-validated cache. Tests: `tests/test_fix4_log_scaling.py`.
- **Faster node listing and YAML parsing** (`os.scandir` walk, libyaml when available). Building a 5,000-fact vault went from not finishing in 5 minutes to about 2.5 minutes.
- **Validator:** a parent's summary may now name the label (or alias) of a private child; only content words are checked.
- **Tests no longer write into `examples/sample_memory`** (`test_mcp_layer` works on a copy).
- **Agent-in-the-loop evaluation kit** (`bench/agent_eval/`, `docs/agent_eval_protocol.md`): per-arm shuffled batches and ready-to-paste prompts that expose only id and question, offline grading with the committed grader, exact McNemar test, Wilson intervals, and an audit of the MCP event log. Tests: `tests/test_fix5_agent_eval.py`.
- **Invalidated 305 episodes** collected with question sets that no longer exist (`bench/results_scaling/invalidated.jsonl`), and removed extrapolated figures and stale derived files. No valid scaling result exists yet; see `docs/experiments_report.md`.

### Fixed (Pass 3: remaining gaps from the second review)
- **Private teasers on disk.** `commit_summary` now overwrites the teaser of every effectively-private child with the standard private teaser (reported as `teasers_overwritten`) and scans teasers of normal children for exact private facts and private numbers. Previously an agent-written teaser such as "account number 4921" was stored verbatim in the parent's file. Tests: `tests/test_fix3_teaser_privacy.py`.
- **Leak validator now honors inheritance.** Descendants of a private node are checked even when their own flag is `normal`; validation lives in `TreeManager._find_private_leak`.
- **Search index drift.** Entries added after the last full build never got BM25 statistics, and node refreshes refit everything eagerly and could misalign dense-embedding rows. Lexical statistics are now refit lazily from cached tokens, nodes keep their position on refresh, and embedding rows are updated or deleted with them, so incremental updates give the same scores as `rebuild_index()`. Tests: `tests/test_fix3_index_consistency.py`.
- **`EventBus.get_events`** reads event files newest first and stops once `limit` events are collected (and skips files older than `since`). Tests: `tests/test_fix3_events_window.py`.
- **Case collisions.** `place` and `split` reject names that differ from an existing sibling only by letter case. Tests: `tests/test_fix3_case_collision.py`.
- **Dotted node names.** `HealthChecker.get_all_node_paths` no longer strips leading/trailing dots from paths (a node named `v2.` was listed as `v2`).

### Fixed (Repo Hygiene)
- Updated `.gitignore` to include `.placements.jsonl`, `.dashboard_url`, `.locks/`, `.events/`, `__MACOSX/`.
- Removed stray vault directories (`demo/`, `memory/`, `my_memory/`) and cache files (`.DS_Store`, `__pycache__`, `*.pyc`, `*.egg-info`).

### Changed (Documentation)
- Updated README to reflect 11 MCP tools (was 10).
- Added missing parameters to tool table: `place: volatile`, `remember: sensitivity`, `recall: reveal`, `compress: reveal`.
- Moved reveal policy paragraph below tool table.
- Changed "read-only dashboard" to "local dashboard with two write actions".
- Documented `--mcp` in-process dashboard and `.dashboard_url`.
- Added privacy rules section describing inheritance and rebuild behavior.
- Documented rebuild behavior (uses placement journal as primary source).
- Updated test count badge to 277 passing (was 191).
- Replaced absolute file:///Users/... links with relative links.

### Added (Dashboard Conflict Handling)
- **Optimistic Concurrency Control for Summary Edits** (`src/treemem/dashboard/server.py`, `src/treemem/tree_manager.py`):
  - `commit_summary` and `POST /api/node/summary` accept `expected_updated` timestamp and `force` boolean flags.
  - Returns `409 Conflict` if the node was modified concurrently (e.g. by an agent or background auto-compressor) while an operator was editing.
  - Returns current summary, current updated timestamp, and conflict details in response payload.
  - Web Dashboard UI (`app.js`, `index.html`) shows interactive conflict panel with "Load Latest" and "Overwrite Anyway (Force)" buttons.
  - 4 new unit tests in `tests/test_dashboard_edit.py` covering matching timestamps, 409 conflict detection, and force overwrite.

### Added (Real LLM Large Vault Evaluation)
- Real LLM evaluation of the 309-fact mid-size vault (`bench/vaults/midsize_vault`,
  `bench/results_large_vault/`):
  - **Model**: `qwen/qwen3.8-27b` via Groq.
  - **Scope**: one arm (`tree_follow`), one run, the **first 15 questions** of the
    47-question mid-size vault set — all single-entity lookups (hotel, restaurant,
    album, concert, book).  No overview, private, or unanswerable questions were
    included in this run.
  - **Accuracy**: 15/15 correct (100%), 0 private leaks.
  - **Single-call rate**: 14/15 questions answered in one `recall` call (93.3%).
  - **Token usage**: 3,002 payload tokens total (~200 per question); 34,807 wire
    tokens total (~2,320 per question, mostly fixed tool-call overhead re-sent
    per hop).
  - **Size comparison** (not a measured flat run): ~200 returned tokens per
    question versus an 11,624-token flat log dump — a structural size difference,
    not a controlled A/B experiment.
  - **What this run does NOT cover**: there is no flat arm, no BM25 arm, no
    overview questions, no private questions, no unanswerable questions, and only
    one run.  A full three-arm run (flat, tree, tree_follow, plus BM25) on all
    47 questions is still needed.

### Added (Dense Vector Embeddings)
- **Pluggable Dense Vector Embedding Providers** (`src/treemem/embeddings.py`):
  - Optional library feature, off by default (`embedding_provider=None`). Not wired into the descent gate or recall routing.
  - Never embeds private content (nodes or log entries with sensitivity `private` or under private ancestors are skipped).
  - LRU embedding cache in `SearchIndex` prevents re-embedding unchanged texts on index rebuild.
  - Abstract `EmbeddingProvider` protocol with unit L2 normalization and cosine similarity computation.
  - `DeterministicEmbeddingProvider`: deterministic random-projection provider based on token and bigram hashing, enabling instant offline plumbing tests with zero external dependencies. Does not demonstrate semantic benefit.
  - `OpenAICompatibleEmbeddingProvider`: connects to any OpenAI-compatible `/v1/embeddings` API endpoint (OpenAI, Voyage, Ollama, Together, vLLM) via `httpx`. Requires `TREEMEM_EMBEDDING_PROVIDER=openai` (or `api`) explicitly.
  - `SentenceTransformersProvider`: local HuggingFace embedding engine (`all-MiniLM-L6-v2` or configurable model). Requires `TREEMEM_EMBEDDING_PROVIDER=sentence-transformers` explicitly.
  - Dynamic factory `get_embedding_provider(...)`: returns `None` unless a provider is explicitly chosen.
- **Tri-Hybrid Candidate Placement & Search Indexing** (`src/treemem/index.py`):
  - Dynamic hybrid scoring blending dense embeddings (`50%`), TF-IDF bigrams (`30%`), and BM25 lexical overlap (`20%`) when dense vectors are explicitly configured. Gracefully degrades if TF-IDF or dense embeddings are not configured (defaults to BM25 lexical).
  - Transparent attribution reporting dominant score source (`'dense'`, `'tfidf'`, `'bm25'`, or `'hint'`).
  - Dense retrieval in `SearchIndex.query()` when an external embedding provider is explicitly configured (lexical BM25 by default).
  - Unit test suites in `tests/test_dense_embeddings.py` and `tests/test_embedding_safety.py`.

### Changed (Roadmap)
- Removed speculative learned descent classifier gate from roadmap and specifications in favor of the working Heuristic Descent Gate (with stemming, query expansion, and coverage scoring). Set immediate milestones to Dense Vector Embeddings $\to$ Real LLM Large Vault Evaluation $\to$ Dashboard Conflict Handling.

### Added (large-vault benchmark, offline)
- `bench/make_midsize_vault.py`: deterministic 309-fact vault (9 topics, 67 nodes, unique invented answers, one private leaf) built with the real `remember`/`place`/`commit_summary` API, plus 47 questions (lookups, overviews, private, unanswerable). `--teasers rich|minimal` models careful vs careless parent summaries.
- `bench/large_vault_offline.py` (no API): compares flat dump, BM25 top-5 and one guided call, and writes `bench/results_offline/large_vault_offline.json`. Findings: the tree is far smaller than a flat dump; BM25 top-5 matches the tree on single-entity lookups; the tree completes overview questions that top-5 cannot; rich parent teasers remove the premature stops.

### Changed (descent gate: premature stops)
- A real run showed the gate stopping at the root for "What hierarchical memory project is the user building?" because the root summary shared the word "memory". The gate now: stems words and drops plain function words; counts a stop as sufficient only when the node summary covers the question's own words (literal match 1.0, synonym match 0.5; `min_stop_coverage=0.5`); prefers a child that matches question words the parent lacks (`specific_term_tiebreak`); and descends when a child scores at least `descend_ratio=0.3` of the parent. `DescentGate.legacy()` restores the old behaviour for comparison.
- `bench/gate_offline_eval.py` (no API calls) measures premature stops on the 12 dev questions plus 26 new held-out questions (`bench/eval/gate_heldout.py`). Results appear in the README, generated from the code. **Not yet confirmed with a real LLM.**

### Fixed (grading)
- The answer grader normalizes Unicode before matching (no-break spaces, curly quotes, dashes) and accepts more phrasings of "not in memory" (for example "don't include any information"). Two correct flat answers from the gpt-oss-120b run were wrongly marked incorrect before this fix.
- `bench/eval/rebuild_aggregate.py --regrade` re-grades saved run files with the current grader (answers and tokens are never changed). Re-grading the three qwen runs changed 0 grades.
- README can show other real-LLM aggregates from `bench/results_*/llm_eval_aggregate.json`.

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
