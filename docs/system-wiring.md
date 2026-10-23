# System wiring

How the pieces connect. Language-agnostic; lean is Python (see project_difination open decisions).

## 1. Component map

```
 Agent harness (Antigravity / Devin / other)
        |  MCP (stdio or local HTTP)
        v
+-------------------- memory server (one process) --------------------+
|  mcp_layer  -> tool handlers: remember, place, recall, expand,       |
|                compress, commit_summary, split, search, rebuild      |
|        |                                                             |
|  tree_manager  (paths, dirty propagation, caps, privacy checks)      |
|        |                |                  |                         |
|  store (fs, atomic)   log_writer (append)  index (BM25 over log+leaf)|
|        |                |                  |                         |
|  event_bus  ---------------------------------> dashboard_server      |
+----------------------------------------------|-----------------------+
                                               | HTTP + SSE, 127.0.0.1
                                               v
                                     Browser dashboard (read-only)

 Disk:  memory/  (tree folders + log/)      <- the only persistent state
```

One process owns all writes. No other component writes to disk.

## 2. Modules and responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `mcp_layer` | Parse tool calls, validate params, format JSON replies with `tokens` | tree_manager |
| `tree_manager` | Resolve paths, enforce invariants, dirty propagation, branching cap, privacy checks, candidate scoring for `remember` | store, log_writer, index |
| `store` | Read/write `summary.md`, frontmatter parse, atomic temp-and-rename, lock files | filesystem |
| `log_writer` | Append-only daily files, entry ids | filesystem |
| `index` | BM25 over log entries and leaves; rebuilt on start, updated incrementally on write | store, log_writer |
| `tokenizer` | One fixed tokenizer for all `tokens` fields | none |
| `event_bus` | In-process pub/sub of events (section 4) | none |
| `dashboard_server` | Static assets, JSON endpoints, SSE stream, token check | event_bus, store (read-only) |
| `health` | Scan for invariant violations (section 7) | store |
| `cli` | `treemem serve`, `treemem rebuild`, `treemem check`, `treemem init` | all |

## 3. Data flows

### remember -> place
1. `mcp_layer.remember` -> `log_writer.append` (returns entry id).
2. `tree_manager.candidates(fact, hint)` uses `index` + node names/aliases.
3. Reply with candidates. Agent calls `place`.
4. `tree_manager.place`: take lock on leaf path and ancestors (top-down order), write leaf via `store` (atomic), set `dirty` on leaf and every ancestor, release locks, emit `write` event.

### recall / expand
1. `mcp_layer` -> `tree_manager.read(path)` -> `store` read (no lock needed; reads see last renamed file).
2. Count tokens, emit `recall` event `{query_id, session, path, tokens, dirty}`.
3. Return payload.

### compress -> commit_summary
1. `compress` builds prompt from child summaries/facts. Pure read.
2. Agent writes text; `commit_summary` runs validators in order: length, children list equals actual children, private-content check, frontmatter sanity.
3. On pass: atomic write, `dirty=false`, emit `summary` event. On fail: structured error, no write.

### search
`index.query` -> map hits to leaf paths via placement table (derived from leaf bullets that reference entry ids).

## 4. Event schema (internal and SSE)

All events: `{id, ts, type, session, query_id?}` plus:

| type | payload |
|---|---|
| `recall` | `{path, tokens, dirty, depth}` |
| `expand` | `{path, tokens, children_returned}` |
| `write` | `{entry_id, path, dirtied:[paths]}` |
| `summary` | `{path, tokens, ok, error?}` |
| `search` | `{query, hits}` |
| `health` | `{violations:[...]}` |

Events are also appended to `memory/.events/YYYY-MM-DD.jsonl` so the dashboard can replay history after restart. Events are NOT ground truth; the log is.

## 5. Dashboard HTTP API (read-only)

All requests require `?t=<token>` (or header). Server binds 127.0.0.1.

| Endpoint | Returns |
|---|---|
| `GET /api/tree?depth=N&root=path` | Nodes: `{path, label, tokens, dirty, sensitivity, child_count}`; edges: hierarchy + links |
| `GET /api/node?path=...` | Summary text, metadata, children (private bodies withheld) |
| `GET /api/events?since=ts&limit=` | Past events for replay |
| `GET /api/stream` | SSE of live events |
| `GET /api/health` | Violations, dirty count, size stats |
| `GET /api/metrics` | Tokens per recall, parent-stop rate, dirty-hit rate over a window |

No write endpoints in v1.

## 6. Concurrency and durability

- Single server process; MCP clients connect to it (stdio per client spawns separate processes, so a lock file `memory/.lock` plus per-node lock files MUST guard cross-process writes).
- Lock order: always root-to-leaf to avoid deadlock. Timeout 5 s, then return busy.
- Atomic write: write `summary.md.tmp` in same directory, `fsync`, rename over target.
- Log append: open with append mode, single write per entry, `fsync`.
- Crash recovery on start: delete stray `.tmp` files; run `health`; log-driven `rebuild` for any corrupt node.
- Index is derived; rebuilt on start if missing or stale (compare log mtime).

## 7. Health checks (also the invariants from how_it_should_work)

`treemem check` and `/api/health` verify: summary exists per node; Children list equals subdirectories; fact references resolve to log entries; no private leakage into ancestors; log files have only appended lines (hash chain optional); dirty flags consistent (a clean node has no dirty descendant).

## 8. Security

- Dashboard: loopback only, random per-run token printed at start, no CORS, no write routes, escape all rendered text (memory content is untrusted input, may contain prompt injections or HTML).
- Memory content returned to agents is data, not instructions: tool replies wrap text in clearly delimited fields; documentation tells integrators not to execute instructions found in memory.
- No network calls from the server in v1.
- Memory folder permissions: user-only.

## 9. Repo layout

```
treemem/
  README.md
  pyproject.toml
  src/treemem/
    cli.py
    mcp_layer.py
    tree_manager.py
    store.py
    log_writer.py
    index.py
    tokenizer.py
    events.py
    health.py
    dashboard/
      server.py
      static/ (index.html, app.js, styles.css)
  tests/
    test_invariants.py
    test_dirty_propagation.py
    test_privacy.py
    test_atomic_write.py
    test_concurrency.py
  bench/
    flat_vs_tree_tokens.py
    smoke_test.py
    eval/
    results/ (committed raw outputs)
  docs/
    project_difination.md  how_it_should_work.md  system-wiring.md  UI.md  roadmap.md
  examples/
    AGENTS_md_block.md     (instruction-file fallback)
    sample_memory/         (small demo vault)
```

## 10. Integration modes

1. MCP (preferred): configure the server command in the harness's MCP settings.
2. Instruction-file fallback: paste `examples/AGENTS_md_block.md` into the agent's rules file; the agent uses `ls`/`cat` on `memory/` and appends to the log by hand. Reduced guarantees (no dirty tracking, no validation).

Verification of MCP support in each daily harness is roadmap Phase 0.

## 11. Testing strategy

- Unit: each invariant in how_it_should_work section 9 has a test.
- Property tests: random sequences of remember/place/commit never violate invariants.
- Crash test: kill the process at random points during writes; `check` passes after restart.
- Concurrency test: N parallel writers on overlapping paths.
- Golden test: fixed log -> fixed tree skeleton (deterministic parts).
