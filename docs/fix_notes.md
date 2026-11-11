# TreeMem Bug Fix Notes (Second Pass)

## Work Package Summary

| Work Package | Status | Tests | Notes |
|-------------|--------|-------|-------|
| WP-A: Leak validator false positives | Done | `tests/test_fix2_leak_validator.py` (6 tests) | Fixed whole-word tokenization, numeric tokens require 3+ digits, stop-word list preserved |
| WP-B: Path segment rule too strict | Done | `tests/test_fix2_path_segment.py` (24 tests) | Relaxed to Unicode (1-100 chars), NFC normalization, remember returns hint_rejected |
| WP-C: Performance (incremental index) | Done | `tests/test_fix2_performance.py` (2 tests) | Single-pass rebuild_index, refresh_node/remove_node added, commit/split/place use refresh |
| WP-D: Repo hygiene | Done | `tests/test_fix2_dashboard_url.py` (1 test), `tests/test_repo_hygiene.py` | .gitignore updated, .dashboard_url written with mode 0o600, transclusion uses effective privacy |
| WP-E: Misleading search note | Done | `tests/test_fix2_search_note.py` (7 tests) | Separate withheld_private and withheld_unplaced counts, index includes sensitivity |
| WP-F: In-process dashboard coverage | Done | `tests/test_fix2_dashboard_integration.py` (1 test) | End-to-end test with uvicorn thread, Bearer token auth, /api/events verification |
| WP-G: Missing tests from first pass | Done | `tests/test_fix2_missing_tests.py` (5 tests) | Dashboard privacy masks, guided recall never enters private, rebuild corrupt journal handling |
| WP-H: Documentation | Updated | N/A | README and supporting docs track the 11-tool surface, path rules, guarded dashboard writes, `.dashboard_url`, benchmark provenance, and the current 378-test suite |
| Red-Team Privacy Test | Done | `tests/test_red_team_privacy.py` (12 tests) | Adversarial test with 26 attack vectors through all 11 MCP tools: **0 leaks in 26 attempts (0.0% leak rate)** |

## Behavior Changes That May Surprise Users

1. **Path names**: Previously limited to ASCII 64 characters. Now supports Unicode (1-100 chars) with NFC normalization. Names like `node.js`, `C++`, `q3_résumé`, and Hindi are now valid.

2. **Unplaced-fact search**: Unplaced facts with sensitivity `normal` are now searchable. Only unplaced facts with sensitivity `private` are withheld (reported as `withheld_unplaced`). Previously all unplaced facts were withheld.

3. **Reveal environment variable**: The `TREEMEM_ALLOW_REVEAL=1` environment variable is now required for `reveal=true` to be honored. Without it, `expand`, `compress`, and `search` return `reveal_denied: true` and a note telling the agent to ask the user.

4. **Journal file**: The placement journal (`.placements.jsonl`) is now the primary source for rebuild, with hints as fallback. Rebuild preserves sensitivity from the journal.

5. **remember hint rejection**: When a hint is invalid, `remember()` now returns `hint_rejected: true` and `hint_error` with the reason, rather than silently falling back to "general".

## Pass 4 (benchmark instrument)

| Item | Status | Covered by |
|---|---|---|
| Questions not answerable from the vault (size 50 was travel-only) | Done: topic-diverse selection at every size, unique answers | `test_fix4_scaled_vault.py` |
| Private questions targeted secrets absent from the vault | Done: they ask for the 4 real private facts | `test_fix4_scaled_vault.py` |
| Episodes from different question sets could be mixed | Done: hashes on every row, resume refuses mismatches | `test_fix4_run_scaling.py` |
| Failures stored as wrong answers | Done: only ok / context_exceeded are final | `test_fix4_run_scaling.py` |
| Quadratic log appends and lookups | Done | `test_fix4_log_scaling.py` |
| Parent summary could not name a private child | Done (labels are public) | `test_fix3_teaser_privacy.py` |
| A test wrote into the committed sample vault | Done | `test_mcp_layer.py` |
| Scaling results, crossover, LLM red-team | **Not done**: no valid data yet | n/a |

## Pass 6 (Agent-in-the-Loop Evaluation Kit v2)

| Work Package | Status | Covered by |
|---|---|---|
| WP1: Overview questions taxonomy leakage -> 10 composite questions | Done: 10 composite questions without path labels, `--questions-v2` flag | `tests/test_fix6_questions_v2.py` (25 tests) |
| WP2: False abstentions -> minimum-effort rule, tips, evidence output | Done: protocol v2 batches (4 answerable + 1 safety), `--protocol v2` | `tests/test_fix6_batches_v2.py` (5 tests) |
| WP3: Evidence grounding -> line-by-line fact check, Bonferroni rule, `--compare-with` | Done: offline grader v2, safety not run handling, tool calls/q | `tests/test_fix6_grade_v2.py` (5 tests) |
| WP4: Failure listing CLI, protocol doc, end-to-end integration | Done: list_failures.py, agent_eval_protocol.md rewritten | `tests/test_fix6_list_failures.py` (1 test), `tests/test_fix6_e2e_v2.py` (1 test) |

## Pass 7 (comprehensive benchmark suite)

| Item | Status | Covered by |
|---|---|---|
| Dashboard compress `AutoCompressor(api_key=...)` blocker | Done: endpoint builds `GroqSummarizerClient(keys=[groq_key])` and passes `summarizer.generate` as `llm_caller` | `tests/test_dashboard_compress.py` |
| `benchmark_suite/` package | Done: schemas, deterministic dataset generation/validation, lexical/neural/TreeMem adapters, metrics, resumable runners, reporting, CLI | `benchmark_suite/tests/test_benchmark_suite.py` |
| Full staged run | Partial: completed through scale 10k plus scale-100 lifecycle/reliability/ablation/E2E; 50k attempted but incomplete (killed/OOM) | `benchmark_suite/results/full_suite/status.json`, `benchmark_suite/reports/full_suite/final_report.md` |

## Final Test Counts

- **Total tests**: 378 collected and passing in the current repository.
- **New test files added**:
  - `tests/test_fix2_leak_validator.py` (6 tests)
  - `tests/test_fix2_path_segment.py` (24 tests)
  - `tests/test_fix2_search_note.py` (7 tests)
  - `tests/test_fix2_dashboard_url.py` (1 test)
  - `tests/test_fix2_performance.py` (2 tests)
  - `tests/test_fix2_dashboard_integration.py` (1 test)
  - `tests/test_fix2_missing_tests.py` (5 tests)
  - `tests/test_red_team_privacy.py` (12 tests)
- **Total new tests**: 58

## Red-Team Privacy Test Results

`tests/test_red_team_privacy.py` is a **scripted regression suite**: 26 scenarios (direct recall, reveal bypass,
guided recall, search, compress, commit_summary, unplaced facts, transclusion, split, inheritance, rebuild) through
the MCP layer. All pass, i.e. none of those 26 fixed scenarios extracts private content.

That is **not** the planned red-team experiment. Not done: an LLM attacker, 100 attempts, a canary vault with a
positive control, or a metadata-leak analysis. No leak rate or confidence bound may be quoted from this suite.

## Architecture Caveats

### Locking Order
- Lock acquisition always follows root-to-leaf order to prevent deadlocks
- Store uses `fcntl` file locking on macOS/Linux
- Lock file names use reversible encoding (percent-encode `/`) to avoid collisions between paths like `a/b` and `a__b`

### Cross-Process Event Flow
- EventBus uses `loop.call_soon_threadsafe(queue.put_nowait, event)` for worker-thread to event-loop delivery
- Events are persisted to `.events/YYYY-MM-DD.jsonl` files
- SSE subscribers register with (loop, queue) pairs

### Index Rebuild Cost
- Full rebuild is O(N) where N is the number of nodes
- Incremental updates via `refresh_node()` are O(1) for single nodes
- commit_summary, split, and place now use refresh_node instead of full rebuild
- Private path computation is single-pass using prefix matching, not nested loops

## Verification

All work packages have been verified by running:
```bash
PYTHONPATH=src python -m pytest tests -q
```

Final result for the current repository: **378 passed in 30.01s**
