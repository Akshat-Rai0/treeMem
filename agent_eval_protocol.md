# Agent-in-the-loop accuracy evaluation (Protocol v2)

**Question answered:** does a real agent answer more questions correctly with TreeMem as its memory than with plain
search or with grep over the raw log? **Only accuracy and grounding are measured.** Token use of the agent is not observable and is not claimed.

## What changed in v2 and why

Run 1 of the agent evaluation (size 1000: treemem 30/40, bm25 32/40, grep 20/40 on answerable questions) revealed three instrument problems:

1. **Taxonomy leakage in overview questions**: The v1 overview questions were phrased with the generator's internal path names (e.g. `"Tell me about collection > maps > south > tier 3"`). No fact contains those taxonomy words, so honest agents properly abstained (`"No information in memory."`). They tested knowledge of the vault's internal path names rather than memory. In v2, the 10 overview questions are replaced by **10 composite questions** combining 3 distinct facts from a leaf without any path labels or taxonomy leakage.
2. **Excessive false abstentions**: Almost every wrong answer across every arm was a false abstention (treemem 9/10, bm25 8/8, grep 20/20), including trivially greppable lookups such as `"Who taught his thermodynamics course?"`. The v1 prompt ("do not guess", one single abstention phrase) encouraged quitting prematurely. In v2, a **minimum-effort rule** requires trying at least three different lookups with distinctive words plus one broader attempt before answering `"No information in memory."`, accompanied by practical arm-specific lookup tips.
3. **No grounding verification**: In v1, answers could not be verified for grounding in actual memory facts. In v2, agents must output an **`evidence`** field containing the exact memory text lines relied upon, which is graded against the vault log fact corpus.

> **Important**: Run 1 results are **not directly comparable** to v2 overview/composite results. Run 1 remains preserved as an immutable historical record and as the baseline for `--compare-with`.

## Design (fixed before any result exists)

- Vault: `scaled_1000` (1,000 facts, 12 topics, depth 4), 50 questions: 30 lookup, 10 composite, 4 private, 6 unanswerable.
- Arms, each evaluated in separate fresh sessions:
  1. `treemem`: TreeMem MCP, read-only (recall, expand, search, status).
  2. `bm25`: the same server, but only the `search` tool (limit 5).
  3. `grep`: no MCP; the raw log as `memory_log.md` and shell tools on that one file.
- The agent sees only `{id, question}` in each batch. No keywords, no gold facts, no question types. Question orders are shuffled per arm.
- **Batches**:
  - Batches 01 to 04 contain the 40 answerable questions (shuffled with the `-A` seed stream).
  - Batch 05 contains the 10 safety questions (4 private + 6 unanswerable, shuffled with the `-B` seed stream).
- **Session plan**:
  - 12 sessions for batches 01 to 04 of each arm, conducted in the order `treemem`, `grep`, `bm25`.
  - Batch 05 is optional (3 additional sessions).
- Answers are JSON arrays with `id`, `answer`, and `evidence`. Saved unedited into `<arm>/answers_batch_XX.json` and graded offline by `bench/agent_eval/grade_agent_answers.py`.
- **Pre-registered decision rules (v2)**:
  - **PRIMARY metric**: accuracy on the 40 answerable questions (lookup + composite). Missing answers count as wrong.
  - **Pairwise comparisons**: exact McNemar test with Bonferroni correction for 3 comparisons ($p < 0.05 / 3 \approx 0.0167$). A difference is marked "detected" only if $p < 0.0167$; uncorrected $p$ is also reported. Wilson 95% confidence intervals are reported.
  - **Evidence grounding**: evaluated against normalized vault log entries. Reported as `grounded_correct`, `ungrounded_correct`, `missing_evidence`, and `fabricated_evidence`. Grounding never alters correctness.
  - **Safety batch**: if batch 05 is omitted for an arm, reported as `safety: not run` without counting toward answerable failures.

## Run it

```bash
# 1. Generate vault with v2 composite questions
python bench/make_scaled_vault.py --facts 1000 --seed 7 --out bench/vaults/scaled_1000 --questions-v2

# 2. Prepare v2 batches and prompts
python bench/agent_eval/make_batches.py --size 1000 --protocol v2

# 3. Grade offline and compare lookups against run 1 baseline
python bench/agent_eval/grade_agent_answers.py --size 1000 --root bench/agent_eval/runs_v2 --compare-with bench/agent_eval/runs

# 4. Inspect detailed failures
python bench/agent_eval/list_failures.py 1000 --root bench/agent_eval/runs_v2
```

This creates `bench/agent_eval/runs_v2/size_1000/{treemem,bm25,grep}/prompt_batch_01..05.txt`, a private vault copy per MCP arm (`vaults/treemem`, `vaults/bm25`), and `grep_workspace/memory_log.md`.

For each arm, configure the agent environment:

| Arm | Agent connections | Workspace folder |
|---|---|---|
| treemem | Register a stdio MCP server running `treemem serve <abs path>/bench/agent_eval/runs_v2/size_1000/vaults/treemem --mcp --no-dashboard` | an empty folder OUTSIDE the repo |
| bm25 | The same server pointed at `.../vaults/bm25` | an empty folder OUTSIDE the repo |
| grep | NO TreeMem MCP server (remove or disable it) | `.../grep_workspace` only |

Never set `TREEMEM_ALLOW_REVEAL` in the server environment.

For each batch: open a FRESH session, paste `prompt_batch_XX.txt`, copy the agent's JSON reply unchanged into `<arm>/answers_batch_XX.json`. If the reply is not valid JSON, rerun that batch in a new session and note it; never repair an answer by hand.

## Contamination checklist (tick before trusting any number)

- [ ] Sessions started in a folder that does not contain the repo, `bench/vaults`, or any questions file.
- [ ] The grep arm had no TreeMem MCP server enabled; the MCP arms had no `memory_log.md`.
- [ ] Each batch was a fresh session (no memory of earlier batches).
- [ ] Answers were pasted unedited; no re-runs other than invalid-JSON cases.
- [ ] `summary.md` shows no audit violations and no PROBLEM lines.

## What the result can and cannot say

It can say how often this agent, with this vault and these tools, answered correctly and whether evidence was grounded in memory.
It cannot say anything about tokens or latency, other models, real (non-synthetic) memories, or other vault sizes.
One run per arm: agent behaviour is not deterministic, so small differences are within noise by design.
