# Fix notes

## Architecture caveats observed before the fixes

- Mutating operations take per-path advisory locks, but some follow-up work (index and transclusion refreshes, events) happens after the lock.  The fixes must preserve the root-to-leaf locking order and avoid treating an unlocked snapshot as authoritative.
- The event bus persists events to disk but its live subscribers are asyncio queues.  A dashboard in another process cannot receive those in-memory notifications, and cross-thread delivery must be scheduled on the subscriber's event loop.
- `rebuild_index()` currently walks the vault repeatedly and several write paths call it after a tiny mutation.  It is safe but can turn a normal summary edit into an O(N) operation; targeted index refreshes must leave startup/rebuild full-index behavior intact.
- The on-disk tree is derived from the append-only log, while a future placement journal adds placement intent.  Rebuild must avoid replaying its own journal writes and must distinguish an already-placed entry from one that needs moving.
- Privacy has both stored-node and inherited-path dimensions.  Every read surface must make the same effective-private decision before serializing data, including event payloads and dashboard views.

