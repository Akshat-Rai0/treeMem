# TreeMem fix notes (three review passes)

Status key: **Done** = reproduced, fixed, and covered by a named test. Statuses below were checked by running the code, not copied from earlier notes.

## Pass 1 (first review)

| Item | Status | Covered by |
|---|---|---|
| Log truncation on `|` | Done | `test_fix_log_escaping.py` |
| Path traversal in `place` / `split` | Done | `test_fix_path_traversal.py` |
| `split` dropping ungrouped children | Done | `test_fix_rebuild_split.py` |
| `rebuild` duplicates / loses privacy / swallows errors | Done (placement journal `.placements.jsonl`) | `test_fix_rebuild_split.py` |
| Private data in compress / recall / search / dashboard | Done (one `is_private` rule incl. ancestors, operator reveal grant) | `test_fix_privacy_boundaries.py`, `test_fix2_missing_tests.py` |
| Multi-process temp-file / lock-name safety | Done | `test_fix_store_safety.py` |
| Live dashboard inside the MCP process | Done (thread-safe `EventBus`) | `test_fix_events_threadsafe.py`, `test_fix2_dashboard_integration.py` |
| Index refresh instead of full rebuild | Done in pass 2/3 | `test_fix2_performance.py`, `test_fix3_index_consistency.py` |
| fcntl guard, tokenizer fallback reporting | Done | `test_fix_tokenizer_reporting.py` |

## Pass 2

| Item | Status | Covered by |
|---|---|---|
| Leak validator false positives (digits, substrings) | Done | `test_fix2_leak_validator.py` |
| Path segment rule too strict (Unicode, `node.js`, `C++`) | Done | `test_fix2_path_segment.py` |
| Unplaced-fact search notes (`withheld_unplaced`) | Done | `test_fix2_search_note.py` |
| `.dashboard_url` written 0600 | Done | `test_fix2_dashboard_url.py` |
| README / docs / CHANGELOG accuracy | Was Partial; completed in pass 3 | see below |

## Pass 3 (this pass)

| Item | Status | Covered by |
|---|---|---|
| Private child teasers stored raw on disk | Done: server overwrites them; normal teasers scanned for private facts and numbers (3+ digits) | `test_fix3_teaser_privacy.py` (5 tests) |
| Leak validator ignored inherited privacy | Done: descendants of a private node are checked even if their own flag is normal | `test_fix3_teaser_privacy.py` |
| Incremental index scores differed from a full rebuild | Done: entries added after the last build never had BM25 stats; lexical stats now refit lazily; embedding rows stay aligned | `test_fix3_index_consistency.py` (4 tests) |
| `get_events` read every file | Done: newest-first with early stop | `test_fix3_events_window.py` (3 tests) |
| Case-only name collisions | Done: `place` and `split` reject them | `test_fix3_case_collision.py` (5 tests) |
| Node names ending in `.` listed wrongly by health check | Done | `test_fix3_case_collision.py` |
| README stale (read-only dashboard, 191 passed, 63,695 vs 66,758) | Done; numbers match `bench/results/llm_eval_results.json` | `test_readme_tables.py` |
| CHANGELOG, system-wiring, UI, how_it_should_work, roadmap | Done | n/a (documentation) |

## Behavior changes that may surprise users

- `commit_summary` replaces teasers of private children with `contains private details, expand to view`, and reports `teasers_overwritten`.
- A summary on a private node may not quote its private children (same as before; documented now).
- `place` / `split` reject names that differ from a sibling only by letter case.
- Path names: Unicode letters/digits plus `_ - . + #` and space, 1 to 100 characters, NFC-normalized.
- Unplaced facts remembered as normal are searchable; unplaced private facts are withheld.
- `reveal=true` only works when the server operator sets `TREEMEM_ALLOW_REVEAL=1`.

## Known limitations

- Leak validation is lexical; a paraphrase of a private fact can pass `commit_summary`. Read-side gating is the real boundary.
- The dashboard only receives live agent events when started with `treemem serve <vault> --mcp`.
- Case collisions are checked on creation only; an existing vault that already contains `Docs` and `docs` is not repaired.
- `rebuild_index` is still a full pass (used at startup and by `rebuild()`); only single-node updates are incremental.

## Test counts

277 tests (260 from earlier passes + 17 added in pass 3). In the review copy used for this pass 276 passed; the one remaining failure was `test_repo_hygiene`, which needs the repo's `.gitignore` (not present in the review copy).
