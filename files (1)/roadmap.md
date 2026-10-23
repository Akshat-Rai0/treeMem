# Roadmap

Time is ample, so phases are ordered by dependency and gated by exit criteria, not dates. Do not start a phase until the previous exit criteria pass.

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
- [ ] Dashboard server with token and loopback binding, the read-only API.
- [ ] Graph canvas with the node/edge encoding from UI.md.
- [ ] Recall list, inspector, token meter, replay bar, health indicator.
- [ ] Demo mode and scripted sequence.
- [ ] Accessibility pass and reduced-motion handling.

Exit: UI acceptance checklist in UI.md fully ticked; 60-second demo GIF recorded.

## Phase 4: Evaluation (M)

- [ ] Flat-vs-tree token benchmark at 100, 1k, 10k memories (synthetic, fixed seed).
- [ ] LongMemEval subset runner: same agent and questions, flat memory vs tree memory; record accuracy and tokens.
- [ ] Parent-stop rate and stop-correctness measurement.
- [ ] Dirty-hit rate and latency (p50/p95).
- [ ] Commit raw results to `bench/results/`; generate the README table from them.

Exit: three headline metrics exist with raw data; an honest "where it loses" paragraph is written even if the tree only ties flat memory.

## Phase 5: Hardening and release (S-M)

- [ ] Concurrency test (parallel writers), property tests.
- [ ] Security review: loopback, token, output escaping, injection-in-memory handling.
- [ ] README: pitch, GIF, install in 3 commands, MCP config snippet, AGENTS.md fallback block, diagram, results table, limitations.
- [ ] Licence, version tag, install tested on a clean machine.
- [ ] Portfolio card and one resume bullet drafted from real numbers only.

Exit: a stranger can install and see their first recall in the dashboard in under five minutes.

## v1.5: Transclusion for volatile facts (M)

- [ ] Parse `![[node#line]]` embeds in summaries; resolve at read time.
- [ ] Mark facts as volatile; parent keeps an embed instead of copied text.
- [ ] Cap embeds per parent to bound token cost.
- [ ] Backlink index; changes to an embedded line do not dirty the parent.
- [ ] Re-run benchmark: staleness errors before vs after.

## v2 candidates (pick based on results)

- Learned descent gate: small classifier predicting "parent is enough", evaluated on accuracy vs tokens.
- Obsidian plugin: dirty nodes and token cost per node inside the vault.
- Editing from the dashboard with conflict handling.
- Optional server-side summarizer (Option B) as a pluggable backend.
- Embedding-based candidate scoring for placement.

## Cross-cutting rules

- Every change keeps the invariants test suite green.
- No benchmark number appears in README or resume without raw results committed.
- Scope changes get written into project_difination.md before implementation.
- Before each phase: re-read the risk register in project_difination.md and check whether the plan still addresses each risk.

## Progress log

| Date | Phase | Note |
|---|---|---|
| 2026-10-22 | Pre-0 | Five docs written; stack decisions pending Phase 0 |
