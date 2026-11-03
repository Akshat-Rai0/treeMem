# Fix notes

## Architecture caveats (read before WP1–WP9)

These interactions can bite the fixes below.

1. **Locking order.** `Store.lock_paths` acquires `fcntl.LOCK_EX` in root-to-leaf order (`slash count`, then length, then lex). Nested tools (place → write intermediates + leaf + ancestors) must keep that order; split currently locks only the parent while `os.rename` moves children. LogWriter uses a process-wide `threading.Lock` plus a per-day `.lock` flock. Dashboard/MCP in one process (WP6) will share both.

2. **Lock-file name collisions.** Lock files are `path.replace("/", "__") + ".lock"`, so `a/b` and `a__b` share a lock. WP5 must use a reversible encoding or sha1. Until then, concurrent writes on colliding names can deadlock or skip isolation.

3. **Temp-file cleanup vs multi-process.** Every `Store.__init__` calls `cleanup_temp_files()`, which `unlink`s **all** `*.tmp` under the vault. A second process constructing `Store` can delete another process’s in-flight `summary.md.tmp`. WP5 must age-gate cleanup and uniquify temp names.

4. **Event flow across processes.** `EventBus.emit` appends `.events/*.jsonl` and `put_nowait`s onto in-memory `asyncio.Queue`s. `put_nowait` from a worker/MCP thread is not loop-safe. `--mcp` and the dashboard are separate processes today, so live SSE never sees agent recalls. Search events persist the raw query. WP6 must share one `TreeManager`/`EventBus`, use `call_soon_threadsafe`, and stop storing query text.

5. **Index rebuild cost.** `rebuild_index` calls `get_all_node_paths()` (full `rglob`), then nested-loops private-path detection (`O(N²)` prefix checks) and **reads every node twice**. `commit_summary` and `split` both call a full rebuild. WP7 needs a single pass plus `refresh_node`.

6. **Path handling.** `norm_path` only strips slashes; `Store.node_dir` concatenates onto `root_dir` with no containment check. `split()` uses unvalidated `grp["name"]` / child names with `os.rename`. Health `get_all_node_paths` will follow any `summary.md` under root (and currently would not see files written *outside* the vault). Validator belongs in `norm_path` so CLI, MCP, and dashboard share it.

7. **Log format.** Lines are `- N | time | session=… | fact: … | hint: …`. `_parse_line` splits on every `|`, so facts containing `|` truncate. Line numbers are `count(non-empty lines)+1`, so a gap or a failed parse desynchronizes IDs. WP1 keeps this format with escaping; WP3 adds an optional `| sens: private` trailer. Invariant 8 assumes dense 1..N line numbers in a file.

8. **Privacy is per-node, not inherited, except in search.** `recall`/`expand`/`compress`/`/api/tree` check `node.sensitivity` only. `_is_private_path` already walks ancestors for search. Unplaced log entries are in BM25. AutoCompressor sends `compress()` inputs (including private facts) to Groq. Reveal policy exists only on MCP `expand`/`search`.

9. **Rebuild vs place.** `rebuild()` re-`place()`s every log entry by hint, swallowing all exceptions, duplicating facts if already placed, marking nodes dirty, and dropping `sensitivity`/`volatile` and any placement that differed from the hint. WP4 needs a placement journal.

10. **fcntl and tokenizer.** `fcntl` is imported at module level (macOS/Linux only). Tokenizer fallback undercounts (~1.33 words) and is not reported on `/api/health`.

## WP1 decisions

- Kept the `- N | time | session= | fact: | hint:` line format.
- Escape `\` then `|` after flattening linebreak characters to spaces.
- Split only on unescaped `|`; unescape only `\\` and `\|`.
- Drop a single padding space from non-final fields (` | ` delimiters) so trailing spaces in fact/hint round-trip; legacy lines still parse as before because they had no backslashes and used the same padding.
- Line numbers: max parsed line in today's file + 1.
- `append(..., sensitivity=)` writes `| sens: private` when asked (unused by remember until WP3). Old lines without `sens:` parse as `normal`.
- Tests: `tests/test_fix_log_escaping.py`.

## WP2 decisions

- Single validator in `norm_path` / `validate_segment`; `Store.node_dir` still containment-checks resolved paths.
- `remember()` catches invalid hints and falls back to `suggested_path="general"` without failing the log append.
- `split()` validates names and collisions inside the lock before mkdir/rename.
- MCP tools return `{"ok": false, "error": ...}` JSON on ValueError. Added `set_manager` so tests (and WP6 dashboard) can inject a shared TreeManager.
- Dashboard maps ValueError → HTTP 400 via an exception handler.
- Tests: `tests/test_fix_path_traversal.py`.
