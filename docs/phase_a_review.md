# Phase A — Architecture Review: Read-Modify-Write Hazards

Reviewed commit: HEAD (pre-phase-B)
Files analysed: `src/treemem/tree_manager.py`, `src/treemem/store.py`,
`src/treemem/index.py`, `src/treemem/embeddings.py`,
`src/treemem/dashboard/server.py`

---

## 1. Read-Modify-Write paths that read OUTSIDE the lock and write INSIDE or AFTER it

### 1.1 `commit_summary` — **CRITICAL lost-update bug**

**Location:** `tree_manager.py` lines 668–779

**Pattern:**
```
node = store.read_node(clean_path)          # line 669 — OUTSIDE lock
if expected_updated != node.updated: ...    # line 674 — conflict check on STALE read
# ... validations against stale node ...
node.summary  = ...                         # mutate stale object
node.dirty    = False
node.updated  = now
node.tokens   = ...
# node.facts, node.sensitivity, node.aliases etc. come from the STALE read
with store.lock_paths([clean_path], ...):   # line 767 — lock acquired TOO LATE
    store.write_node_atomic(clean_path, node)  # writes stale copy
```

**Consequence:** A concurrent writer (`place`, `put`, another `commit_summary`) that
runs between the `read_node` at line 669 and the `lock_paths` at line 767 will have
its changes silently overwritten, because the whole `NodeData` object (including
`facts`, `sensitivity`, `aliases`, `children_cap`) originates from the stale read.
The optimistic conflict check at line 674 is also performed on the stale read —
if the concurrent write committed and changed `node.updated` *after* line 669 but
*before* the `lock_paths`, the check passes incorrectly.

**Fix required (Phase B):** Move the `read_node` call *inside* the `lock_paths`
block; perform conflict check and all validations on the fresh node; write back
only the fields that `commit_summary` legitimately owns
(`summary`, `children`, `dirty`, `updated`, `tokens`).

---

### 1.2 `split` — **stale parent write**

**Location:** `tree_manager.py` lines 832–877

**Pattern:**
```
node = store.read_node(clean_path)          # line 839 — OUTSIDE lock
with store.lock_paths([clean_path], ...):   # line 846
    # ... renames child dirs, writes group nodes ...
    node.children = new_children            # mutates stale object
    node.dirty    = True
    store.write_node_atomic(clean_path, node) # line 874
```

**Consequence:** Any concurrent write to the parent node between the unlocked
`read_node` and the `lock_paths` block is silently lost (e.g. a concurrent
`place` that updates the parent's children list or dirty flag).

**Severity:** Medium — `split` is an infrequent operation, but the race exists.

**Fix required (Phase B):** Re-read the parent node fresh inside the lock before
mutating it.

---

### 1.3 `place` — reads and writes inside the lock (SAFE)

**Location:** `tree_manager.py` lines 180–272

All `read_node` / `write_node_atomic` calls for intermediate nodes and the leaf
are inside the `with store.lock_paths(all_lock_paths, ...)` block. The only
operations that occur after lock release are:
- `index.record_placement(entry_id, clean_path)` — in-process index update, no disk write.
- `event_bus.emit(...)` — in-process only.

No disk read-modify-write races. **SAFE.**

---

### 1.4 Dashboard `edit_summary` route — **duplicate unlocked conflict check**

**Location:** `dashboard/server.py` lines 287–302

```python
node = tree_manager.store.read_node(clean_path)   # unlocked read
...
if not body.force and body.expected_updated and node.updated != body.expected_updated:
    raise HTTPException(409, ...)                  # conflict check on stale value
...
res = tree_manager.commit_summary(...)             # second check inside commit_summary
```

**Consequence:** The dashboard performs its own conflict check on a stale `read_node`
result outside any lock. Between this check and the eventual `commit_summary` call,
another writer could change the node. The dashboard's early-return 409 is therefore
unreliable; it may either miss a conflict or raise a false positive.

Additionally, because the old `commit_summary` itself reads outside its lock,
there are two racy reads total. After Phase B fixes `commit_summary`, the dashboard
route must delegate conflict detection entirely to `commit_summary` (the HTTP layer
can keep the fast pre-flight only as a cheap early-reject that must not be the
*sole* authority).

---

### 1.5 `rebuild` — sequential `place` calls (ACCEPTABLE)

**Location:** `tree_manager.py` lines 879–908

`rebuild` calls `place` in a sequential loop. Each `place` call is individually
safe (reads and writes inside lock). No compound read-modify-write race across
multiple iterations. `rebuild` is a maintenance operation typically run with no
concurrent writers; documented as such. **No fix required.**

---

### 1.6 Dashboard `get_tree` / `get_node` / `get_metrics` — read-only (SAFE)

All dashboard GET endpoints call `store.read_node` without locks. Reads see the
most recently atomically-replaced `summary.md` at the OS level; no consistency
guarantee across multiple nodes, but no write is performed. This is the standard
read-without-lock pattern. **SAFE** for the intended read-only purpose.

---

## 2. `lock_paths` reentrancy

`store.lock_paths` uses POSIX `fcntl.flock` with `LOCK_EX | LOCK_NB`. On Linux,
`flock` is **not reentrant per file descriptor** — calling it a second time on the
same path from the **same thread** without releasing will either block (defeating
`LOCK_NB`) or succeed silently and then fail to release correctly. On macOS,
`flock` is per-open-file-description; a second `os.open` of the same lock file in
the same thread gets a **new fd** and the lock will succeed but both fds hold the
lock, so it appears reentrant but the accounting is wrong.

**Conclusion: `lock_paths` MUST NOT be called twice on the same path in one
thread/call stack without an intervening release.** The current code does not
reenter — `place` locks ancestors + leaf in one call, `commit_summary` locks only
the single node, `split` locks only the parent. There is no double-lock anywhere.
This is safe today, but callers must not nest `lock_paths` calls.

---

## 3. Blockers for Phase B fixes

**No blockers found.** All paths identified in section 1 can be refactored to
move the `read_node` call inside an existing or new `lock_paths` block without
changing the external API or adding any new locking hierarchy.

The `lock_paths` signature already accepts a list and sorts paths top-down, so
existing deadlock-avoidance is preserved. The only constraint is that
`rebuild_index()`, `transclusion_mgr.index_node()`, and `event_bus.emit()` must
remain outside the lock (they do network-equivalent or I/O-heavy work); this
matches the Phase B spec.

---

## 4. Summary table

| Path | Bug | Severity | Phase B fix |
|---|---|---|---|
| `commit_summary` | Reads outside lock; conflict check and validations on stale node; overwrites fields it should not own | **CRITICAL** | Move `read_node` + conflict check + validations inside lock; write only `summary/children/dirty/updated/tokens` |
| `split` | Reads parent outside lock, writes stale object inside lock | Medium | Re-read parent inside lock before mutating |
| `dashboard edit_summary` | Duplicate unlocked conflict check before delegating to `commit_summary` | Low | Remove as authority; keep only as fast-path; `commit_summary` is sole authority |
| `place` | All reads/writes inside lock | ✓ Safe | — |
| `rebuild` | Sequential safe `place` calls | ✓ Safe | — |
| Dashboard GETs | Read-only | ✓ Safe | — |

---

*Generated: Phase A review — no behaviour changes in this commit.*

---

## Phase A2 — Architecture Re-Check: Remote Embeddings Safety, Hints, and Harness Failure Reporting

Reviewed files: `src/treemem/embeddings.py`, `src/treemem/index.py`, `src/treemem/tree_manager.py`, `src/treemem/log_writer.py`, `bench/eval/run_eval.py`, `bench/eval/rebuild_aggregate.py`.

### 1. How a hint is stored for an entry
- **Daily log file (disk ground truth)**: Stored in `<vault>/log/YYYY-MM-DD.md` on the entry line as a pipe-delimited field: `| hint: <hint>`. Formatted by `LogWriter.append` and parsed by `LogWriter._parse_line` into dict key `entry["hint"]`.
- **Search index (memory)**: Stored in `SearchIndex.entry_docs` as `doc_obj["hint"]` (`{"entry_id": eid, "text": fact_text, "hint": hint_text, "path": ...}`). Also concatenated into `full_text = f"{fact_text} {hint_text}"` used for BM25 token corpus and embedding representations.

### 2. Every place text is sent to an embedding provider
1. **`SearchIndex._cached_embed_batch(texts)`**:
   - `SearchIndex.build()` at line 239: calls `_cached_embed_batch` on `public_node_texts` (node summaries of public nodes).
   - `SearchIndex.build()` at line 264: calls `_cached_embed_batch` on `public_entry_texts` (entry texts of entries whose placement path is public).
   - `SearchIndex.add_entry()` at line 298: calls `_cached_embed_batch([f"{fact} {hint}".strip()])` when a new entry is added via `remember()`.
2. **`SearchIndex.query(query_str, limit)`**:
   - Line 345: calls `self.embedding_provider.embed_text(query_str)` to embed the incoming search query.
3. **`SearchIndex.candidate_nodes(fact, hint, ...)`**:
   - Line 457: calls `self.embedding_provider.embed_text(query_text)` where `query_text = f"{fact} {hint}".strip()` to embed the fact + hint for dense placement ranking against node embeddings.
*(Note: Internal provider methods `DeterministicEmbeddingProvider.embed_batch` and `OpenAICompatibleEmbeddingProvider.embed_text` invoke each other internally).*

### 3. How GroqKeyPool reports an HTTP 413
- In `GroqKeyPool.execute_with_failover()`:
  When an HTTP status code 413 ("Request Entity Too Large") is returned by Groq, it falls into the catch-all `else:` branch:
  ```python
  last_error = f"HTTP {response.status_code}: {response.text[:120]}"
  time.sleep(1.5)
  ```
  It then sleeps and retries across the other keys in the pool up to `max_retries` (8 attempts). Since request length limits are identical across keys, all 8 retries fail. Finally, it raises:
  `RuntimeError(f"Groq request failed after {max_retries} retries across keys. Last error: HTTP 413: ...")`.
  It does not distinguish 413 from other fatal API errors, does not stop retrying immediately, and does not record the failure as an evaluation result.

### 4. Blockers
- **No blockers found.**
- `bench/results_gptoss` is missing; copy it back if you still have it.
- All Phase B, C, D, and E tasks can proceed cleanly without architectural conflicts or breaking changes to existing invariant suites.

