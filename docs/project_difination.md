# Project definition: TreeMem (working title)

Hierarchical, agent-writable memory for LLM agents, exposed as an MCP server, stored as a plain folder of markdown, with a local web dashboard that visualizes every recall.

Status: pre-implementation. Owner: Akshat Rai. Last updated: 2026-10-22.

## 1. One-line pitch

An agent reads a concise parent node first and descends into child nodes only when the question needs more detail, so recall costs far fewer tokens at the same accuracy.

Analogy: a library. The catalog card is the parent, the shelf summary is a child, the book is a leaf. The agent only walks as far as the question requires.

## 2. Problem

- Flat memory (one notes file, or top-k vector hits) either dumps everything into context or misses relevant facts.
- Time-based compression (e.g. OptMem's binary merge tree over a chronological log) shrinks old entries, but the agent cannot choose per question how deep to look.
- Nothing lets a developer see which memory an agent actually read to give an answer.

## 3. Goals (v1)

1. Tree of topic nodes: parent = concise summary, children = more detail, leaves = raw facts.
2. Agent-driven descent: `recall` returns a parent plus child labels; the agent calls `expand` only if needed.
3. Append-only raw log as ground truth; the tree is a rebuildable cache of it.
4. Agent writes summaries (Option A): the server hands out a compression prompt, the agent returns text, the server validates and stores it. No model hosted by the server.
5. Staleness handling via a dirty flag propagated to ancestors.
6. Per-node sensitivity tag so a parent can say "has private details" without leaking them.
7. Plain-folder storage, Obsidian-compatible format (frontmatter, wikilinks, daily-note log).
8. Local read-only web dashboard: live graph, recall path highlighting, replay.
9. Measurable results: tokens per recall vs flat dump, answer accuracy on a long-term-memory benchmark subset, parent-stop rate.

## 4. Non-goals (v1)

- Learned descent gate (v2 research item).
- Multi-user, auth beyond a local token, cloud sync.
- Embedding or vector search (lexical fallback only).
- Editing nodes from the dashboard.
- Server-side LLM calls.
- Obsidian plugin (v2) and transclusion (v1.5).
- Canvas, Dataview-style queries.

## 5. Users and use

- Primary user: a developer running coding agents (Antigravity, Devin, others) who wants persistent memory that is cheap to read and inspectable.
- Secondary: a reviewer (recruiter, interviewer) watching a demo.
- Integration surface: MCP server, plus a fallback instruction-file mode (agent follows an AGENTS.md block and uses `ls`/`cat` on the folder if MCP is unavailable).

## 6. Locked decisions

| Decision | Choice | Reason |
|---|---|---|
| Style | Product-style (plug-in memory layer), not research-only | User choice |
| Summarizer | Agent writes summaries (Option A) | Harness-agnostic, no API key or model hosting |
| Storage | Folder of markdown, folder = tree | Inspectable, diffable, graceful fallback |
| UI | Local web dashboard served by the memory server, read-only v1 | Zero install, best demo surface |
| Ground truth | Append-only log (daily-note files) | Tree can always be rebuilt |

## 7. Open decisions

| Decision | Options | Lean |
|---|---|---|
| Implementation language | Python or TypeScript | Python (benchmark and eval harness live there) |
| Graph library | Cytoscape.js or D3 tree layout | Cytoscape.js |
| Token counting | tiktoken-style approximation or per-model tokenizer | One fixed tokenizer, documented, used consistently |
| Search fallback | Simple BM25 or regex | BM25 over the log |
| MCP support in Antigravity/Devin | Unverified | Verify in roadmap Phase 0 |

## 8. Success metrics (targets to measure, not claims)

- Tokens per recall vs flat dump at 100, 1k, 10k memories: tree curve stays near flat.
- Answer accuracy on a LongMemEval subset: report even if the tree only ties flat memory.
- Parent-stop rate and correctness of those stops.
- Recall latency (p50, p95).
- Staleness: fraction of recalls that hit a dirty node.

## 9. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Fact placed in the wrong node | Fact unreachable by descent | Raw log is truth; `search` fallback; server proposes candidate nodes |
| Agent stops at a lossy parent and answers confidently wrong | Wrong answers | Parent must list child labels; recall returns "not covered" hints |
| Stale parent after a child changes | Wrong answers | Dirty flag to all ancestors; recall reports staleness; re-summarize on next compress |
| Agent never compresses (lazy agent) | Tree permanently dirty | Server nags at session start; recall flags dirty nodes plainly |
| Branching explosion | Child label list defeats the purpose | Cap children per node; split on overflow |
| Sensitive facts leak into parents | Privacy breach | Per-node sensitivity tag; parents summarize as "has private details" |
| Concurrent sessions corrupt files | Data loss | Atomic temp-file-and-rename writes; lock file; log is append-only |
| Crash mid-write | Half-written summary | Atomic rename; rebuild from log |
| Dashboard exposes memory | Privacy breach | Bind 127.0.0.1 only; random token in URL |
| Wikilink cycles or dead links | Traversal loops | Links are secondary edges; depth-limited, visited-set traversal |
| Obsidian syntax is non-standard markdown | Parser bugs | Small dedicated parser; only support wikilink, embed (v1.5), frontmatter |
| Crowded space (many Obsidian-as-memory MCP servers likely exist; not verified) | Weak novelty | Differentiate on tree descent, staleness handling, and the x-ray dashboard; check prior art in Phase 0 |

## 10. Definition of done (v1)

- Five MCP tools working against a real folder, tested.
- Dashboard shows live recall paths and replay.
- Benchmark script produces the three metrics, with raw results committed.
- README with install in under five minutes, GIF demo, limitations.
- Works under at least one daily-use harness (Antigravity or Devin) or via the instruction-file fallback.
