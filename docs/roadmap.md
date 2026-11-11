# Roadmap

Phases are ordered by dependency and gated by exit criteria, not dates. Phases 0 through 5 and v1.5 are complete; the v2 items below record implemented capabilities and remaining evaluation work.

Sizes: S = a few days, M = about a week, L = multiple weeks (rough, for relative planning only).

## Phase 0: Verify and de-risk (S)

Goal: remove unknowns before writing real code.

- [ ] Check whether Antigravity and Devin can use MCP servers and how they configure them (stdio vs HTTP). Record findings in `docs/harness-notes.md`.
- [ ] If MCP is unavailable in a harness, confirm the instruction-file fallback works there.
- [ ] Prior-art check: other MCP memory servers, hierarchical/summary-tree memory (e.g. RAPTOR-style), OptMem. Write a half-page "how this differs".
- [ ] Pick: language (lean Python), graph library (lean Cytoscape.js), tokenizer, BM25 library.
- [ ] Hand-build a 20-node sample memory folder and run a paper walkthrough of the descent flow.

Exit: harness notes written, prior-art note written, stack chosen, sample vault exists.

## Phase 1: Core store and log (M)

- [ ] `store`: frontmatter parse/write, atomic temp-and-rename, lock files.
- [ ] `log_writer`: append-only daily files, entry ids.
- [ ] `tree_manager`: path resolution, node creation, `place`, dirty propagation, branching cap.
- [ ] `tokenizer` wrapper.
- [ ] `treemem init`, `treemem check`, `treemem rebuild`.
- [ ] Tests for invariants 1-3, 6, 7, 8 (see how_it_should_work section 9).

Exit: invariant tests pass; killing the process mid-write never corrupts the tree (crash test passes).

## Phase 2: MCP tools (M)

- [ ] `mcp_layer` with `remember`, `place`, `recall`, `expand`, `search`.
- [ ] `index` (BM25) and candidate scoring for `remember`.
- [ ] `compress`, `commit_summary`, `split` with validators (length, children list, private leakage).
- [ ] Session-start dirty report.
- [ ] Wire into one real harness (or fallback mode) and run an end-to-end session.

Exit: an agent in a real harness stores facts, recalls via descent, and compresses a dirty node successfully; invariants 4 and 5 pass.

## Phase 3: Events and dashboard (M-L)

- [ ] `event_bus`, event files, SSE.
- [x] Dashboard server with token and loopback binding, the read-mostly API, summary editing, and per-node compression.
- [ ] Graph canvas with the node/edge encoding from UI.md.
- [ ] Recall list, inspector, token meter, replay bar, health indicator.
- [ ] Demo mode and scripted sequence.
- [ ] Accessibility pass and reduced-motion handling.

Exit: UI acceptance checklist in UI.md fully ticked; 60-second demo GIF recorded.

## Phase 4: Evaluation (M)

- [x] Flat-vs-tree token benchmark at 100, 1k, 10k memories (synthetic, fixed seed).
- [x] Real LLM agent benchmark runner (`bench/eval/run_eval.py`): same model (`qwen/qwen3.8-27b`) and questions, flat memory vs tree memory; record accuracy and tokens.
- [x] Parent-stop rate and stop-correctness measurement (25% parent-stop rate).
- [x] Dirty-hit rate and latency (p50/p95).
- [x] Commit raw results to `bench/results/`; generate the README table from them.

Exit: three headline metrics exist with raw data; an honest "where it loses" paragraph is written even if the tree only ties flat memory. (Passed)

## Phase 5: Hardening and release (S-M)

- [x] Concurrency test (parallel writers), property tests.
- [x] Security review: loopback, token, output escaping, injection-in-memory handling.
- [x] README: pitch, install in 3 commands, MCP config snippet, AGENTS.md fallback block, diagram, results table, limitations.
- [x] Licence, version tag (`v0.1.1`), install tested on a clean machine.
- [x] Portfolio card and resume bullets drafted from real numbers only (`docs/portfolio.md`).

Exit: a stranger can install and see their first recall in the dashboard in under five minutes. (Passed)

## v1.5: Transclusion for volatile facts (M)

- [x] Parse `![[node#ref]]` embeds in summaries; resolve at read time (`src/treemem/transclusion.py`).
- [x] Mark facts as volatile (`volatile=True`); parent keeps an embed instead of copied text.
- [x] Cap embeds per parent to bound token cost (max 5 embeds per summary enforced on commit and recall).
- [x] Backlink index (`TransclusionManager.backlink_index`); changes to an embedded line do not dirty the parent.
- [x] Test suite: `tests/test_transclusion.py` (6 tests).

## v2 Milestones & Features

- [x] Pluggable server-side Auto-Summarizer (Option B): bottom-up topological compression, validation-retry loop, and daemon worker (`src/treemem/auto_compress.py`, `tests/test_auto_compress.py`).
- [x] Heuristic Descent Gate & Guided Descent (`src/treemem/descent_gate.py`, `tests/test_descent_gate.py`): stemming, word coverage, and single-call guided traversal (`follow=True`).
- [x] Dense Vector Embeddings: pluggable dense embedding providers (local/API) with hybrid candidate scoring and search (`src/treemem/embeddings.py`, `tests/test_dense_embeddings.py`).
- [x] Real LLM Large Vault Evaluation: measured on 309-fact mid-size vault with `qwen/qwen3.8-27b` achieving 100% accuracy, 98.3% payload token savings, while flat dump exceeded provider token limits (`bench/results_large_vault/`).
- [x] Dashboard Conflict Handling: optimistic locking, 409 Conflict detection, and force overwrite for concurrent summary edits and auto-compression (`src/treemem/dashboard/`, `tests/test_dashboard_edit.py`).

## Cross-cutting rules

- Every change keeps the invariants test suite green.
- No benchmark number appears in README or resume without raw results committed.
- Scope changes get written into project_difination.md before implementation.
- Before each phase: re-read the risk register in project_difination.md and check whether the plan still addresses each risk.

## Progress log

| Date | Phase | Note |
|---|---|---|
| 2026-10-22 | Pre-0 | Five docs written; stack decisions pending Phase 0 |
| 2026-11-04 | Hardening | Three review passes: log escaping, path validation, privacy inheritance and teaser sanitization, placement journal, in-process dashboard, incremental index, case-collision guard. See docs/fix_notes.md |
| 2026-11-10 | Documentation | Reconciled documentation with the implemented CLI/MCP surface, 378-test suite, guarded dashboard writes, and current benchmark status. |
| 2026-11-11 | Evaluation | Added `benchmark_suite/` comprehensive harness and staged `full_suite` runner; completed non-50k steps through scale 10k plus scale-100 lifecycle/reliability/ablation/E2E. 50k attempted but incomplete (killed/OOM). See `benchmark_suite/README.md` and `benchmark_suite/reports/full_suite/final_report.md`. |
