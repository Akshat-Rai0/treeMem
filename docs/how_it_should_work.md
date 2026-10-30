# How it should work

Behavioral spec for TreeMem v1. Wording: MUST / SHOULD are binding for implementation.

## 1. Core model

- Memory root is a directory. Every directory under it is a node. A node MUST contain `summary.md`.
- Hierarchy = directory nesting. Parent summary is a concise view of its children.
- Leaves hold raw facts (one fact per bullet, each referencing a log entry id).
- `log/YYYY-MM-DD.md` is append-only ground truth. The tree is a cache and MUST be rebuildable from the log.
- Secondary edges: `[[wikilinks]]` between nodes. Hierarchy is primary; links are optional lateral hints.

## 2. File formats

### Node: `<path>/summary.md`

```markdown
---
name: identity
aliases: [about me, personal]
dirty: false
updated: 2026-10-22T10:15:00Z
tokens: 74
sensitivity: normal        # normal | private
children_cap: 12
---
Short summary of this topic (target 40-120 tokens).

## Children
- [[age]] - one-line teaser
- [[location]] - one-line teaser
- [[college]] - one-line teaser
```

Rules:
- `## Children` MUST list every child label with a one-line teaser. This is how the agent knows detail exists below.
- `sensitivity: private` nodes: parent teaser says "contains private details" and nothing else.
- Leaf nodes hold facts as bullets: `- fact text (log: 2026-10-22#14)`.

### Log entry: `log/2026-10-22.md`

```markdown
- 14 | 10:12:03Z | session=abc | fact: User is 21 | hint: identity/age
```

- Entries are only ever appended. Entry id = `date#line`.

## 3. Tools (MCP)

All tools return structured JSON plus a `tokens` field (cost of the returned text).

### `remember(fact, hint?)`
1. Append to today's log. Get entry id.
2. Propose up to 3 candidate nodes by alias/keyword match against node names, aliases, and summaries.
3. If `hint` names an existing path, use it as the first candidate.
4. Return `{entry_id, candidates:[{path, score}], create_option:{suggested_path}}`.
5. Agent confirms via `place(entry_id, path)` (or the server auto-places on a score threshold).
6. Placing appends the fact to the leaf (creating it if needed) and marks the leaf and ALL ancestors `dirty: true`.

### `place(entry_id, path)`
Writes the fact into the leaf at `path`. Creates intermediate nodes (with placeholder summaries, dirty) if missing. Enforces the branching cap (see 6).

### `recall(path = "/", query?, follow?, max_depth?)`
Returns `{summary, children:[{label, teaser}], dirty, sensitivity, tokens, stale_note?}`.
- MUST NOT return child bodies.
- If `dirty`, include `stale_note` stating when it was last summarized and that children changed since.
- Emits a `recall` event (see system-wiring).

### `expand(path)`
Returns child summaries (or raw facts if `path` is a leaf). Private children return teaser only unless `reveal=true` is passed explicitly.

### `compress(path)`
Returns `{prompt, inputs:[child summaries or facts], length_cap, required_sections}` for the agent to write a new summary. Does not modify anything.

### `commit_summary(path, text)`
Validates then writes atomically:
- length <= cap
- contains a `## Children` list matching actual children (no missing, no invented)
- no content from `sensitivity: private` children
On success: `dirty=false`, `updated=now`. On failure: returns the exact violation so the agent can retry.

### `search(query, limit=10)`
Lexical (BM25) search over the log and leaves. Fallback when descent fails. Returns entry ids, text, and the leaf path where each is placed (or "unplaced").

## 4. Recall flow (the descent decision)

```
agent needs info about X
  recall("/")                          -> root summary + child labels
  if root summary + labels answer it:  STOP   (parent-stop)
  else pick the best child label
  recall(child) / expand(child)        -> repeat
  if nothing matches after depth limit -> search(query)
```

- The server never decides to stop for the agent in v1; the agent decides. (A learned gate is a v2 research item.)
- Server logs `{query_id, nodes_read, stopped_at, tokens_total}` per recall chain for the dashboard and benchmark. A chain is the set of calls sharing a `query_id` (agent-supplied optional parameter) or, if absent, calls within 10 s of each other from the same session.

## 5. Staleness and compression

- Any write under a node marks that node and all ancestors `dirty`.
- Dirty is cleared only by a successful `commit_summary`.
- Compression order: deepest dirty node first, then upward, so parents summarize fresh children.
- Session start: server reports the count and paths of dirty nodes so the agent can compress them.
- A dirty node is still readable. It is flagged, not hidden.

## 6. Branching cap and splitting

- `children_cap` default 12 per node.
- When a `place` would exceed the cap, the server returns `needs_split` with the current children and a proposed grouping prompt. Agent calls `split(path, groups)` to create intermediate nodes. No data is lost; the log still holds every fact.

## 7. Privacy rules

- `sensitivity: private` is set per node (by the agent at `place` time via flag, or by the user editing frontmatter).
- A parent's summary MUST NOT contain text derived from private children. `commit_summary` rejects violations by checking against private children's fact text (substring and token-overlap check).
- Private nodes appear in child lists as `label - private details, expand to view`.

## 8. Worked example: "What is my age?"

1. `recall("/")` -> summary: "Alex, software engineer, ..."; children: identity, college, projects. Does not answer age.
2. `recall("identity")` -> summary mentions age category; children: age, location. Teaser for `age`: "current age".
3. `expand("age")` -> leaf fact: "28 (log: 2026-10-22#14)". Answer found.
4. Dashboard shows path root -> identity -> age; stop depth 2; tokens summed.

Contrast: "What's my name?" -> root summary alone answers it, so parent-stop at depth 0.

## 9. Invariants (tests MUST assert these)

1. Every node has `summary.md`.
2. Every fact in a leaf references an existing log entry.
3. `## Children` in a summary equals the set of child directories.
4. Deleting the whole tree and rebuilding from the log yields all facts reachable (via `search` at minimum).
5. No private child's text appears in any ancestor summary.
6. A write under node N sets dirty on N and all its ancestors; nothing else.
7. Writes are atomic: a killed process never leaves a half-written `summary.md`.
8. Log files are never modified, only appended.

## 10. Failure behaviors

| Situation | Behavior |
|---|---|
| Fact has no good candidate node | `create_option` suggested; if agent ignores, fact stays "unplaced" but searchable |
| Agent submits summary too long | Rejected with exact token overage |
| Agent submits summary missing a child | Rejected, lists missing labels |
| Tool called on non-existent path | Error plus closest existing path suggestions |
| Two sessions write the same node | Second waits on lock (timeout 5 s), then retries; if still blocked, returns busy error |
| Corrupt or missing `summary.md` | Reported in health panel; `rebuild(path)` regenerates a placeholder from children and marks dirty |

## 11. Out of scope for v1 behavior (documented so nobody assumes it)

- Transclusion of volatile facts into parents (v1.5).
- Server choosing when to stop descending (v2).
- Editing from the dashboard.


## Guided descent (`follow=true`)

`recall(path, query, follow=true, max_depth=3)` collapses the manual root -> branch -> leaf walk into one call:

1. Read the node and ask the descent gate: `stop`, `descend` (with a suggested child), or `search_fallback`.
2. `stop`: return this node. `descend`: step into the suggested child and repeat. `search_fallback`: run a bounded search (at most 400 tokens) and return it.
3. Stop early at a leaf (facts are returned), at `max_depth`, on a revisited path, or **before any child with `sensitivity: private`** (the response then carries `stopped_at_private`, `suggested_child` and a message; the private node is never read into the response).
4. The response carries `final_path`, `traversal` (per-step action and scores), `steps`, `stopped_reason`, and `tokens` (only what is returned to the agent).

It is read-only: no vault file changes, no dirty-flag changes, no write locks. It emits one `recall` event per step so the dashboard shows the whole path. `search` withholds hits under private nodes unless `reveal=true`.


## Reveal policy (who may unlock private nodes)

A tool argument is controlled by the model, so `reveal=true` cannot be the permission. `treemem.reveal_policy.resolve_reveal(requested)` returns `(effective, denied)`: reveal is effective only when the operator started the server with `TREEMEM_ALLOW_REVEAL=1`. The MCP `expand` and `search` tools apply it and add `reveal_denied` and a note to the result when it refuses. The evaluation harness applies the same policy, so a private question counts as correct when the agent does **not** leak the secret.

## Evaluation harness

`python bench/eval/run_eval.py [--arms flat,tree,tree_follow] [--runs N] [--limit K] [--no-pacing]` runs three arms on the same questions: flat dump, manual tree descent, and guided descent. It writes one file per run (`bench/results/llm_eval_runs/run_k.json`), an aggregate with mean and standard deviation (`llm_eval_aggregate.json`), and the single-run `llm_eval_results.json` (flat vs tree, last run) that the README generator reads. Accuracy is scored on the non-private questions; the private question is reported as leaks. Latency excludes pacing sleeps. Each run uses a fresh copy of the vault.

If a run is cut short (rate limit, Ctrl+C), the finished runs are already saved and the aggregate is current up to the last finished run. `python bench/eval/rebuild_aggregate.py` rebuilds the summary files from the saved run files with no API calls. Because the model runs at temperature 0 on fixed questions, repeated runs reproduce the same tokens and answers; extra runs mainly measure latency noise, so prefer more or paraphrased questions over more repeats.


## Descent gate rules (after the premature-stop fix)

For each node the gate scores the question against the node summary and each child teaser, then:
1. **Stop** only if the node scores at least 0.25 AND its text covers at least half of the question's own words (a literal match counts 1.0, a synonym match 0.5).
2. Even then, **descend** if a child scores clearly higher, or contains a question word the parent lacks and scores about the same, or scores at least 30% of the parent (an extra server-side step is nearly free; a wrong stop costs correctness).
3. If the node is not sufficient, **descend** into the best child when it scores at least 0.15, otherwise **search_fallback**.
`python bench/gate_offline_eval.py --set all --compare` shows the effect without any API calls.


## Writing parent summaries so the gate can route

The gate can only route on words that appear in a node summary or a child teaser. A teaser such as "Fiction speculative" hides the genres inside; "Fiction speculative: space opera, cyberpunk, dystopian, fantasy" lets a question about cyberpunk reach the right leaf. When committing a summary, list the key entities of each child in its teaser (cities, genres, tools, names), within the 150-token cap. `bench/large_vault_offline.py` shows the difference between minimal and rich teasers without any API calls.
