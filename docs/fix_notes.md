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
| WP-H: Documentation | Partial | N/A | README updated with test count (260), tool table (11 tools), path names section, .dashboard_url documented, benchmark numbers fixed to match JSON |

## Behavior Changes That May Surprise Users

1. **Path names**: Previously limited to ASCII 64 characters. Now supports Unicode (1-100 chars) with NFC normalization. Names like `node.js`, `C++`, `q3_résumé`, and Hindi are now valid.

2. **Unplaced-fact search**: Unplaced facts with sensitivity `normal` are now searchable. Only unplaced facts with sensitivity `private` are withheld (reported as `withheld_unplaced`). Previously all unplaced facts were withheld.

3. **Reveal environment variable**: The `TREEMEM_ALLOW_REVEAL=1` environment variable is now required for `reveal=true` to be honored. Without it, `expand`, `compress`, and `search` return `reveal_denied: true` and a note telling the agent to ask the user.

4. **Journal file**: The placement journal (`.placements.jsonl`) is now the primary source for rebuild, with hints as fallback. Rebuild preserves sensitivity from the journal.

5. **remember hint rejection**: When a hint is invalid, `remember()` now returns `hint_rejected: true` and `hint_error` with the reason, rather than silently falling back to "general".

## Final Test Counts

- **Total tests**: 260 passing
- **New test files added**:
  - `tests/test_fix2_leak_validator.py` (6 tests)
  - `tests/test_fix2_path_segment.py` (24 tests)
  - `tests/test_fix2_search_note.py` (7 tests)
  - `tests/test_fix2_dashboard_url.py` (1 test)
  - `tests/test_fix2_performance.py` (2 tests)
  - `tests/test_fix2_dashboard_integration.py` (1 test)
  - `tests/test_fix2_missing_tests.py` (5 tests)
- **Total new tests**: 46

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

Final result: **260 passed in 22.91s**
