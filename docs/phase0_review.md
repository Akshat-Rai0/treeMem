# Phase 0: Architecture Review & Invariant Analysis

This document provides the formal Phase 0 architectural safety analysis for planned TreeMem enhancements:
- Phase 1: Packaging & Leakage Prevention
- Phase 2: Drift-Proof Benchmarking Tables
- Phase 3: Single-Call Guided Descent

---

## 1. Invariant & Structural Safety Analysis

TreeMem enforces strict local-first memory invariants. Below is the impact assessment of planned changes against each invariant and mechanism:

| Mechanism / Invariant | Status | Architectural Verification |
|:---|:---:|:---|
| **Invariant 1** (Every directory has `summary.md`) | **Safe** | Read-only operations (`recall`, `search`, `descent_gate`) do not create or remove directories or delete `summary.md`. |
| **Invariant 2** (Leaf facts reference valid log entries) | **Safe** | Guided descent only traverses existing cache nodes and references. No facts are created or modified. |
| **Invariant 3** (`## Children` matches child directories) | **Safe** | Read-only traversals do not modify node frontmatter or filesystem directories. |
| **Invariant 4** (Rebuild from log preserves facts) | **Safe** | Cache rebuild logic in `tree_manager.py` remains untouched. |
| **Invariant 5** (No private child text in ancestor summaries) | **Critical** | Guided descent must **never** concatenate or aggregate private child summaries into parent response payloads during auto-traversal. |
| **Invariant 6** (Dirty propagation consistency) | **Safe** | Guided descent is strictly a read operation; it does not set `dirty: true` or clear dirty flags. |
| **Invariant 7** (Atomic writes & no stray `.tmp` files) | **Safe** | No file writes occur during recall or guided descent. |
| **Invariant 8** (Append-only daily ledger integrity) | **Safe** | No writes to `log/*.md`. |
| **Locking Order** (Root-to-leaf atomic locks) | **Safe** | Guided descent operations are read-only and operate lock-free via atomic reads. |
| **Dirty Propagation** | **Safe** | Descent does not alter node state; ancestor-descendant dirty relationships are preserved. |

---

## 2. Privacy & Sensitivity Enforcement in Guided Descent

The primary risk in automatic descent (`follow=True`) is accidentally exposing private nodes without explicit user authorization (`reveal=true`).

### Strict Enforcement Rules:
1. **Never Auto-Follow into a Private Node**:
   - If the heuristic descent gate returns `action: "descend"` with `suggested_child: "X"`, the traversal engine must inspect `child_node.sensitivity` before stepping into `X`.
   - If `child_node.sensitivity == "private"`:
     - The guided descent loop **must stop immediately** at the parent node.
     - The response payload must set:
       ```json
       {
         "stopped_at_private": true,
         "suggested_child": "X",
         "message": "Suggested topic 'X' has sensitivity: private. Auto-descent halted. Explicit recall or expand with reveal=true is required."
       }
       ```
     - The private node's raw summary, facts, and unmasked teasers must **never** be exposed in the traversal path or response.
2. **Masked Teasers during Gate Evaluation**:
   - In `TreeManager.recall()`, child teasers for private nodes are already masked to `"contains private details, expand to view"`.
   - The heuristic gate evaluates only the child's label and this masked teaser, preventing leakages during gate scoring.
3. **No Transclusion Leaks**:
   - When resolving `![[path#ref]]` transclusions during auto-descent, any transclusion pointing to a private node continues to be masked unless `reveal=true` was explicitly passed.

---

## 3. Additional Architectural Caveats & Mitigations

1. **Dashboard & Event Bus Observability**:
   - When `recall(follow=True)` traverses multiple nodes (e.g., `/` $\rightarrow$ `identity` $\rightarrow$ `identity/bio`), it must emit a discrete `recall` event on `self.event_bus` for **each step** of the traversal.
   - This ensures the Cytoscape.js X-Ray dashboard and SSE event stream accurately visualize the active traversal path in real time.
2. **Cycle Prevention & Depth Caps**:
   - Although TreeMem vaults are strictly hierarchical directory structures, guided descent must guard against cycles or deep recursions by maintaining a `visited_paths: Set[str]` and strictly enforcing `max_depth` (default: 3).
3. **Search Fallback Bounding**:
   - If the gate triggers `action: "search_fallback"`, the runner invokes `self.search(query, limit=5)`. The search result tokens must be counted and bounded to avoid context explosion.
4. **Graceful Sklearn Degradation (`[gate]` extra)**:
   - When `scikit-learn` is absent, `descent_gate.py` and `index.py` must log a one-time warning (using standard `logging.getLogger("treemem")`) and fall back to pure lexical token overlap without raising an `ImportError`.
   - Tests requiring scikit-learn must be cleanly decorated with `@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason=...)` so base environments run with 0 test failures.
5. **Benchmark Leakage Elimination**:
   - Persona-specific tokens (`"alex"`, `"mercer"`, `"apex"`, `"metropolis"`, `"treemem"`) currently present in `_SYNONYM_MAP` in `descent_gate.py` must be purged. Only generic domain synonyms (e.g., `profession` $\rightarrow$ `job, career, work, role`) may remain.
   - A dedicated unit test must assert that no tokens in `descent_gate.py` are derived from `examples/sample_memory/`.

---

## Conclusion & Gate Status

- **Blockers**: None.
- **Proceed to Phase 1**: Yes.


---

## Phase 3 caveats (addendum, found during implementation)

1. **Pre-existing leak, fixed**: `TreeManager.search` returned facts stored under private nodes (for example a routing number) with no filtering. Guided descent's `search_fallback` would have exposed them. `search` now withholds hits under private nodes (node or any ancestor) unless `reveal=true`. Covered by tests.
2. **"No writes" clarified**: follow mode makes no vault content writes, no dirty-flag changes and takes no write locks. It does append `recall`/`search` events to `.events/` (observability, same as plain `recall`). The read-only test excludes `.events/` and `.locks/`.
3. **Starting node**: if the starting path is itself private, existing `recall` behavior applies; follow mode never steps into a private child.
4. **Gate quality bound**: the descent is only as good as the heuristic gate (lexical + TF-IDF over summaries). Queries whose words do not appear in summaries fall to `search_fallback`, which is correct but costs a search.


## Addendum 2: reveal and evaluation

1. **`reveal` was not a permission.** The eval showed the model setting `reveal=true` itself, including on the private banking node. Reveal is now an operator grant (`TREEMEM_ALLOW_REVEAL=1`), enforced in the MCP layer and in the eval harness. `TreeManager` methods keep their `reveal` argument for trusted direct callers.
2. **Grading fixes.** The private question is now graded as protected when it is not leaked, and accuracy is computed over the non-private questions. The negative control no longer accepts a bare "not" as a correct answer.
3. **Latency honesty.** The old latency numbers included the harness's pacing sleeps. They are now API time plus local tool time only.
4. **Not yet measured.** The guided-descent arm has never been run against a real LLM in this repo. The repeated-runs table in the README stays "Not measured yet" until `run_eval.py --runs N` is run with Groq keys.
