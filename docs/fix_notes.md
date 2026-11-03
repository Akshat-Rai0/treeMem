# Fix notes

## Architecture caveats observed before the fixes

- Mutating operations take per-path advisory locks, but some follow-up work (index and transclusion refreshes, events) happens after the lock.  The fixes must preserve the root-to-leaf locking order and avoid treating an unlocked snapshot as authoritative.
- The event bus persists events to disk but its live subscribers are asyncio queues.  A dashboard in another process cannot receive those in-memory notifications, and cross-thread delivery must be scheduled on the subscriber's event loop.
- `rebuild_index()` currently walks the vault repeatedly and several write paths call it after a tiny mutation.  It is safe but can turn a normal summary edit into an O(N) operation; targeted index refreshes must leave startup/rebuild full-index behavior intact.
- The on-disk tree is derived from the append-only log, while a future placement journal adds placement intent.  Rebuild must avoid replaying its own journal writes and must distinguish an already-placed entry from one that needs moving.
- Privacy has both stored-node and inherited-path dimensions.  Every read surface must make the same effective-private decision before serializing data, including event payloads and dashboard views.

## WP1 and WP2 baseline

- The pre-existing WP1 implementation keeps the legacy line format while escaping backslashes and pipes, and allocates IDs from the highest successfully parsed line number.
- The pre-existing WP2 implementation validates all topic paths centrally, containment-checks store paths, and converts dashboard/MCP validation failures into clear client errors.

## WP3 decisions

- Effective privacy is inherited from every ancestor through `TreeManager.is_private()` and is applied consistently to recall, expand, guided descent, compress, search, and dashboard output.
- MCP reveal remains operator-gated. Direct Python callers retain their explicit `reveal=True` behavior for tests and local integrations.
- Private auto-compression is skipped unless the operator explicitly grants reveal. Search events persist a length and a short SHA-256 prefix instead of raw query text.
- Tests: `tests/test_fix_privacy_boundaries.py`.

## WP4 decisions

- Successful placements are persisted in append-only `.placements.jsonl`; rebuild uses the latest entry record, then falls back to the log hint.
- Rebuild is idempotent for facts already present and returns concrete per-entry errors instead of swallowing exceptions.
- Split preserves both ungrouped children and existing child teasers.
- Tests: `tests/test_fix_rebuild_split.py`.

## WP5 decisions

- Temp files now include process and random identifiers; startup only removes files older than 60 seconds. The previous crash-recovery test was updated to model a stale artefact rather than an in-flight write.
- Lock names use SHA-1 digests, eliminating the `a/b` versus `a__b` collision.
- `fcntl` is platform-guarded and fails clearly on unsupported systems.
- Tests: `tests/test_fix_store_safety.py`.

