# TreeMem Algorithm & Architecture Specification

This document specifies the retrieval algorithm, the predictive descent gate, the
storage write path, and the placement journal (WAL) precisely enough to reason
about correctness, complexity, and failure modes. It describes what the code
does today; measured results live in `benchmark_suite/reports/`.

---

## 1. Storage model

The vault is a directory of human-readable Markdown files:

- `log/YYYY-MM-DD.md` — append-only daily ledger. Each line is
  `- <id> | <time> | session=<s> | fact: <text> | hint: <path>` with optional
  `sens: private`, `supersedes: <entry_id>`, `retracts: <entry_id>`,
  `valid_from: <ISO>`, `valid_to: <ISO>` fields (all escaped so `|`/`\`
  round-trip). **The log is the ground truth**; every other structure is a
  rebuildable derivative.
- `<path>/summary.md` — one file per node: YAML frontmatter
  (`name, aliases, dirty, updated, tokens, sensitivity, children_cap`) plus a
  summary body, a `## Children` teaser list, and (for leaves) a `## Facts`
  list whose entries reference log ids (`log: YYYY-MM-DD#NNN`).
- `.placements.jsonl` — append-only placement journal (the WAL). One JSON
  record per `place` call: `{ts, entry_id, path, sensitivity, volatile, sha256}`.
- `.locks/` — lock files for write mutual exclusion.

Writes are atomic: serialize to a unique temp file (`.<name>.tmp.<pid>.<uuid>`),
`fsync`, then `os.rename` over the target, then fsync the directory. Stray
`.tmp` files older than 60 s are cleaned on open.

### Concurrency

`Store.lock_paths(paths)` acquires per-path lock files in sorted (root-to-leaf)
order with a 5 s timeout, preventing deadlock between writers holding ancestor
and descendant locks simultaneously. `place`, `commit_summary`, and `split`
all re-read the node fresh inside the lock before mutating, so last-writer-wins
is per-node and no committed write is torn. Readers (`recall`, `expand`,
`search`, `status`) take no locks.

### Crash consistency

- Log appends: single `write` + flush per line to an append-only file — a crash
  can at worst lose the in-flight line, never corrupt earlier lines.
- Node writes: temp+rename is atomic at the filesystem level; a crash leaves
  either the old or the new `summary.md`, never a partial one.
- Journal appends: `write` + `flush` + `fsync(file)` + best-effort directory
  fsync. Each record carries a `sha256` over its payload; `_placement_records()`
  verifies checksums on replay and reports malformed lines as `__error__` entries
  instead of silently misplacing facts.
- `rebuild()` replays the journal (last record per `entry_id` wins) as the
  primary placement source, falling back to the fact's `hint` when no journal
  record exists, and re-`place()`s every log entry not already placed. Journal
  replay is idempotent: already-placed entries are skipped via
  `_placed_entry_ids()`.

---

## 2. Write path

`remember(fact, hint, sensitivity)`:
1. Appends the fact to today's log, returns `entry_id = YYYY-MM-DD#NNN`.
2. Feeds the entry into `SearchIndex` (BM25 stats refit lazily).

`place(entry_id, path, sensitivity, volatile)`:
1. Validates the path (depth ≤ 8, segment rules, no `..`, reserved `log`).
2. Inside `lock_paths(ancestors + [path])`: creates missing ancestor nodes,
   appends the fact to the leaf's `## Facts`, marks the leaf and **every
   ancestor** `dirty: true` (skipping ancestors that transclude the target),
   appends the placement record to `.placements.jsonl`, emits a `write` event.

`commit_summary(path, text, expected_updated, force)` (agent-written summaries):
1. Validates text before locking: ≤ 150-token cap, `## Children` list must
   exactly match on-disk child dirs, private-teaser rules (see §5).
2. Inside `lock_paths([path])`: re-reads node, returns `409 Conflict` if
   `updated` moved since `expected_updated` (unless `force`), writes
   `{summary, children, dirty:false, updated, tokens}` atomically.
3. Heavy work (index refresh, transclusion, events) happens **outside** the lock.

`split(path, groups)` repartitions an over-full node's children into new child
nodes inside one lock; preserves ungrouped children and their teasers.

`compress(path)` returns a compression prompt + child text; `auto_compress`
runs the same validation loop with an external LLM caller, bottom-up over
`get_dirty_nodes()` (deepest first).

---

## 3. Read path: parent-first recall

`recall(path="/")` returns only the node's summary and one-line child teasers —
never child bodies. Cost is O(1) in vault size: one file read plus teaser
formatting (~40–150 tokens). `expand(path)` drills one level (child summaries
or leaf facts). `search(query, limit)` is BM25 over log entries + node docs.

### 3.1 Temporal semantics (supersede / retract / valid-time)

- `remember(..., supersedes=<entry_id>)` marks the target as replaced; the new
  fact is the successor. `retract(entry_id)` appends a tombstone line
  (`retracts: <entry_id>`, placeholder fact, **not indexed**) that deletes the
  fact semantically. `supersedes` and `retracts` are mutually exclusive.
- Both produce a *hidden* entry: filtered from `expand`, guided leaf payloads,
  `compress` inputs, and `search` hits unless `include_history=true`.
- `valid_from`/`valid_to` (optional ISO-8601) define a fact's valid-time
  interval `[from, to)`. Effective interval when fields are absent:
  `from` = the entry's append timestamp; `to` = the append timestamp of the
  entry that supersedes/retracts it (open if none).
- `at=<ISO-8601>` on `recall`/`expand`/`search`/`compress` filters leaf facts
  and search hits to those whose effective interval contains `at` —
  point-in-time queries over memory. `at` takes precedence over
  `include_history`.
- All temporal state derives from the log, so rebuild/restart preserves it.
  Health invariant 9 verifies every `supersedes`/`retracts` target exists.
- `remember` also emits a non-blocking `contradiction_warning` when a new fact
  has high lexical overlap with an existing fact but differing numbers or
  negation cues — a heuristic prompt to pass `supersedes=`, not a proof.

### 3.2 Token accounting

Token accounting is exact (`tiktoken` cl100k_base; a labeled 1.3× conservative
fallback when unavailable — `status()`/`/api/health` report which is active).

---

## 4. Predictive descent gate

`DescentGate.evaluate(query, parent_path, parent_summary, children,
eager_descent)` is invoked on every `recall` that carries a `query`. It scores
the parent text (`path + summary`) and each child text (`label + teaser`)
against the query and returns `{action, parent_sufficient, confidence,
suggested_child, hint, parent_score, child_score, parent_coverage}`.

### 4.1 Query preprocessing

- Tokenize `\b\w+\b`, lowercase.
- Drop stopwords: a fixed generic English/function-word list (`_STOPWORDS` ∪
  `_EXTRA_STOPWORDS` when `better_tokens=True`, the default).
- Light stemming (`stem()`): `-ing`, `-ies→y`, `-es` after s/x/z, plural `-s`.
- Synonym expansion via a small generic `_SYNONYM_MAP` (profession↔engineer↔
  career…, location↔city…, education↔university…). No domain vocabulary.

### 4.2 Hybrid scoring

For each candidate text `t` (parent first, then children in order):

```
lexical(t) = min(1, (2·|content_toks ∩ toks(t)| + 0.5·|expanded_toks ∩ toks(t)|)
                  / (2·|content_toks|))
```

Content tokens count double versus expanded/synonym tokens, so a literal
question word is stronger evidence than a synonym hit.

```
semantic(t) = cosine(tfidf_unigram_bigram(query_expanded), tfidf(t))   # sklearn only

score(t) = 0.5·semantic(t) + 0.5·lexical(t)     # sklearn installed
          = 1.0·lexical(t)                      # otherwise (semantic ≡ 0)
```

The TF-IDF vectorizer is fit per call over `[parent_text] + child_texts` +
the expanded query (`ngram_range=(1,2)`, `sublinear_tf`, `strip_accents`).
Fitting per call keeps the gate stateless and vault-size independent; cost is
O(children · text length) per node visit.

### 4.3 Coverage and tie-break signals

`query_word_groups` produces one `(stemmed_word, synonyms)` pair per content
word. For each text we compute `cover(t) = mean over groups of`:
`1.0` if the word appears, `0.5` if only a synonym appears, `0.0` otherwise.

- `parent_coverage = cover(parent_text)` — the fraction of the question's own
  words the parent literally covers.
- `child_extra_terms` = number of question words the best child covers
  literally that the parent covers only weakly or not at all.

### 4.4 Decision rule

```
parent_sufficient = (parent_score ≥ 0.25) ∧ (parent_coverage ≥ 0.5)
```

If `parent_sufficient`, stop **unless** any of:

| Rule | Condition | Rationale |
|---|---|---|
| clearly better | `child_score > parent_score + 0.15` | child is strictly more relevant |
| specific term | `child_extra_terms > 0 ∧ child_score ≥ parent_score − 0.05` | child has words the parent lacks |
| cheap descend | `eager_descent ∧ child_score ≥ 0.15 ∧ child_score ≥ 0.3·parent_score` | guided mode only: extra server-side step is ~free |

→ `descend` to `suggested_child` (highest-scoring child).

If not sufficient and `best_child_score ≥ 0.15` → `descend`.
Otherwise → `search_fallback` (confidence 0.40).

`DescentGate.legacy()` reproduces the pre-fix behavior (`better_tokens=False`,
`min_stop_coverage=0`, no tie-break, `descend_floor=0.25`, `descend_ratio=0`)
for offline A/B measurement (`bench/gate_offline_eval.py`).

Parameters were tuned on a plateau: `descend_ratio ∈ [0.2, 0.4]` yields
identical results on dev + held-out question sets, so the choice is not
sample-fitted.

---

## 5. Guided descent (`recall(follow=true)`)

`_guided_recall` loops the gate server-side, read-only:

```
current = start_path
loop:
    payload = recall(current, query, eager_descent=True)   # one node + gate eval
    if node has no children            → stop "leaf"       (facts returned)
    if gate.action == "stop"           → stop "stop"
    if gate.action == "search_fallback"→ run bounded search → stop "search_fallback"
    if gate.action == "descend":
        if steps ≥ max_depth           → stop "max_depth"
        child = current/suggested_child
        if child is private            → stop "private" (never enters)
        if child visited               → stop "stop"
        current = child; steps += 1
```

Guarantees:
- **Read-only**: no writes, no dirty-flag changes, no write locks. Each step
  emits a normal `recall` event (visible in the dashboard replay).
- **Privacy**: `is_private(path)` (node or any ancestor) halts descent before
  entering; private leaf facts are never returned without `reveal`.
- **Bounded**: `max_depth` (default 3) caps steps; the search fallback payload
  is token-bounded to 400 tokens.
- Returned `tokens` counts only the final payload (summary + teasers + facts +
  bounded search hits); intermediate node payloads are traversed but not
  returned.

`stopped_reason ∈ {stop, leaf, search_fallback, max_depth, private}` is
reported so callers (and the benchmark `diagnose` arm) can audit *why* a
descent ended — this is the instrumentation used to measure premature stops
and false-negative pruning.

---

## 6. Search

`SearchIndex` maintains two corpora:

- **Entries** (log facts + hints): score = `BM25Okapi` + `1.5·|query_words ∩
  doc_tokens|` + `3.0` exact-substring bonus + `2.5·dense_sim` (only when an
  embedding provider is explicitly configured; private/unplaced-private
  entries are never embedded or returned without reveal).
- **Nodes** (name + aliases + summary) for `candidate_nodes`, used by `place`
  to suggest topics: exact hint match scores 1.0 first, then
  `lexical = 0.5·norm_BM25 + 0.5·norm_word_overlap`, blended with optional
  dense (`0.50 dense + 0.30 tfidf + 0.20 lexical` when both embeddings and
  sklearn are active; weights degrade gracefully).

BM25 statistics are refit lazily from cached tokens on incremental updates so
`add_entry`/`refresh_node` produce identical scores to `rebuild_index()`.

---

## 7. Complexity analysis (argument, validated by measurement)

Let `N` = number of facts, `b` = effective branching factor (bounded by
`children_cap`, default 12), `D` = tree depth ≈ `log_b(N/leaf_size)`.

- **Flat dump**: Θ(N) tokens in context; retrieval is O(N) to serialize.
- **Parent-first recall**: O(1) per node visit — one `summary.md` read.
- **Guided descent**: visits O(D) nodes = **O(log_b N)** node reads, each
  O(children) gate work. Total gate cost O(D · b) = O(b·log_b N) token
  scoring, versus O(N) for scoring every fact. With `max_depth` the constant
  is hard-bounded regardless of N.
- **Search fallback**: O(N) BM25 scoring but returns ≤ `limit` hits.
- **Writes**: `place` is O(depth) file writes + O(1) journal append;
  `commit_summary` O(1) node write + O(children) validation.

The O(b·log_b N) figure is an *analysis of the algorithm*, not a proven bound:
it assumes balanced trees (enforced statistically by `children_cap` +
`split`, not guaranteed) and that the gate picks a relevant child at each
level (measured, not guaranteed — see `diagnose` false-negative metrics).
Empirical node-visit counts per query are recorded in benchmark `diagnose`
episodes (`guided_steps`, `expansions`) for validation at 100/1k/10k scale.

---

## 8. Privacy model (summary)

- `sensitivity: private` on a node hides its summary, facts, and teasers from
  all read paths unless `reveal=true` **and** the operator set
  `TREEMEM_ALLOW_REVEAL=1` (the model cannot grant itself access).
- Privacy is **inherited**: `is_private(path)` checks the node and all
  ancestors; descendants of private nodes are treated as private everywhere
  (recall, expand, search, index, embeddings, AutoCompressor).
- `commit_summary` overwrites agent-written teasers of effectively-private
  children with `"contains private details, expand to view"` and scans normal
  children's teasers for exact private facts/numbers before accepting.
- Unplaced private log entries are indexed but withheld from `search` results.

---

## 9. Known limitations (honest list)

- The descent gate is lexical + TF-IDF; queries whose vocabulary shares no
  stems/synonyms with summaries degrade to `search_fallback` (measurable via
  `stopped_reason` distribution).
- Parent summaries are only as good as the agent that writes them; benchmark
  vaults use deterministic rich teasers, which flatters routing vs. real
  agent-written summaries.
- A wrong `stop` looks like a confident wrong answer — premature-stop rate is
  the primary accuracy risk and is tracked explicitly in evaluation.
- Multi-hop/cross-branch questions may need facts from several subtrees; the
  single-path guided descent plus bounded search fallback is the current
  mitigation (a beam-search arm and a guided+global arm exist in the benchmark
  suite for measurement).
