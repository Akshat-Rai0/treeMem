# Agent-in-the-loop accuracy evaluation (e.g. Devin over MCP)

**Question answered:** does a real agent answer more questions correctly with TreeMem as its memory than with plain
search or with grep over the raw log? **Only accuracy is measured.** Token use of the agent is not observable and is not claimed.

## Design (fixed before any result exists)

- Vault: `scaled_1000` (1,000 facts, 12 topics, depth 4), 50 questions: 30 lookup, 10 overview, 4 private, 6 unanswerable.
- Arms, each in separate fresh sessions of 10 questions (5 sessions per arm, 15 in total):
  1. `treemem`: TreeMem MCP, read-only (recall, expand, search, status).
  2. `bm25`: the same server, but only the `search` tool (limit 5).
  3. `grep`: no MCP; the raw log as `memory_log.md` and shell tools on that one file.
- The agent sees only `{id, question}`. No keywords, no gold facts, no question type. The question order is shuffled per arm.
- Answers are the JSON array the agent prints. They are saved unedited and graded offline by `bench/agent_eval/grade_agent_answers.py`
  with the committed grader (`bench/eval/run_eval.py`). Nobody grades by hand.
- Primary metric: accuracy on the 40 answerable questions, missing answers count as wrong. Private questions are reported
  as leaks and are not part of the comparison (the grep arm has no privacy mechanism by construction).
- Arms are compared on the same questions with an exact McNemar test; "detected" means p < 0.05. With 40 questions,
  only differences of roughly 15 points or more can be detected. Anything smaller is reported as "not detected", not as a tie or a win.

## Run it

```
# 0. prerequisites: pass-4 patch applied, then
python bench/make_scaled_vault.py --facts 1000 --seed 7 --out bench/vaults/scaled_1000      # about 25 s
python bench/agent_eval/make_batches.py --size 1000
```

This creates `bench/agent_eval/runs/size_1000/{treemem,bm25,grep}/prompt_batch_01..05.txt`, a private vault copy per MCP
arm (`vaults/treemem`, `vaults/bm25`, so each has its own event log) and `grep_workspace/memory_log.md`.

For each arm, configure the agent environment:

| Arm | Agent connections | Workspace folder |
|---|---|---|
| treemem | Register a stdio MCP server running `treemem serve <abs path>/bench/agent_eval/runs/size_1000/vaults/treemem --mcp --no-dashboard` | an empty folder OUTSIDE the repo |
| bm25 | The same server pointed at `.../vaults/bm25` | an empty folder OUTSIDE the repo |
| grep | NO TreeMem MCP server (remove or disable it) | `.../grep_workspace` only |

Never set `TREEMEM_ALLOW_REVEAL` in the server environment.

For each batch: open a FRESH session, paste `prompt_batch_XX.txt`, copy the agent's JSON reply unchanged into
`<arm>/answers_batch_XX.json`. If the reply is not valid JSON, rerun that batch in a new session and note it; never repair an answer by hand.

When all arms are done, stop the servers and run:

```
python bench/agent_eval/grade_agent_answers.py --size 1000
```

It writes `summary.md` and `summary.json`, refuses to run if the questions file changed since the batches were prepared,
and audits the MCP arms (vault unchanged; bm25 arm used only `search`; treemem arm never wrote). An audit violation invalidates that arm.

## Contamination checklist (tick before trusting any number)

- [ ] Sessions started in a folder that does not contain the repo, `bench/vaults`, or any questions file.
- [ ] The grep arm had no TreeMem MCP server enabled; the MCP arms had no `memory_log.md`.
- [ ] Each batch was a fresh session (no memory of earlier batches).
- [ ] Answers were pasted unedited; no re-runs other than invalid-JSON cases.
- [ ] `summary.md` shows no audit violations and no PROBLEM lines.

## What the result can and cannot say

It can say how often this agent, with this vault and these tools, answered correctly, and whether arms differ detectably.
It cannot say anything about tokens or latency, other models, real (non-synthetic) memories, or other vault sizes.
One run per arm: agent behaviour is not deterministic, so small differences are within noise by design.
