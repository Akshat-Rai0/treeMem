# TreeMem Experiments Plan

> **Update (2026-11-11):** A separate reproducible `benchmark_suite/` harness now exists for comprehensive
> retrieval/context/scaling/lifecycle/privacy/reliability/ablation/offline-E2E evaluation at 100/1k/10k/50k.
> This file remains the plan for the older `bench/` LLM scaling/red-team experiments; see
> `benchmark_suite/README.md` and `docs/experiments_report.md` for the new suite's status and commands.

## Research Questions

### Q1: Crossover Point for TreeMem vs Flat Dump
**Question:** At what vault size does TreeMem (guided descent) beat a flat dump on total tokens without losing accuracy, if ever?

**Metrics:**
- Total tokens per question (API-reported: prompt_tokens + completion_tokens)
- Accuracy (correct / total questions, counting failures as wrong)
- Context-exceeded failures (flat arms that cannot be sent)

**Definition of Crossover:**
The smallest vault size where:
- `tree_follow` mean total tokens per question < `flat` mean total tokens per question
- AND `tree_follow` accuracy is not more than 2 percentage points below `flat` accuracy
- If flat cannot run at a size (context exceeded), flat's accuracy is 0 and its tokens are the would-be prompt token count (measured offline with cl100k_base)

**Vault Sizes:** 50, 200, 1000, 5000 facts

**Arms:**
- flat: whole log in the prompt
- tree_follow: guided descent via recall(follow=true)
- rag_bm25: BM25 top-5 over log entries
- rag_bm25_k10: BM25 top-10 over log entries

**Model:** qwen/qwen3.8-27b (via Groq)

**Runs:** 5 repeated runs per size/arm combination
**Questions per run:** 50 (30 lookup, 10 overview, 4 private, 6 unanswerable)

---

### Q2: TreeMem vs BM25 RAG on Overview Questions
**Question:** How does TreeMem compare to plain BM25 top-k retrieval (RAG baseline), especially on overview questions that need several facts?

**Metrics:**
- Overview completeness (answers containing all required facts)
- Accuracy on lookup questions
- Total tokens per question

**Definition of Overview Advantage:**
`tree_follow` overview completeness minus the best RAG arm's overview completeness, per size, with 95% bootstrap confidence intervals (10,000 resamples, seed 11).

**Question Types:**
- Lookup: single-fact lookup questions (30 per vault)
- Overview: multi-fact questions requiring 2-6 facts (10 per vault)
- Private: sensitivity="private" facts (4 per vault, graded as "refused correctly" if not leaked)
- Unanswerable: facts not in vault (6 per vault, graded as correct if refused)

---

### Q3: Privacy Model Red-Team
**Question:** Does the privacy model hold against an adversarial agent?

**Target:** Zero private-content leaks in 100 attack attempts.

**Threat Model:**
The attacker controls:
- The arguments of the 11 MCP tools (remember, place, recall, expand, compress, commit_summary, search, split, rebuild, status, auto_compress)
- In dashboard scenarios, a valid dashboard token

The attacker does NOT have:
- Filesystem access
- Control over environment variables
- Knowledge of canary values

**TREEMEM_ALLOW_REVEAL** must be unset in all attack runs.

**Attack Categories (100 total):**
1. Direct path access (8): Try to access private paths directly
2. Reveal abuse (8): reveal="true", 1, "yes" on every tool that accepts it
3. Path tricks (10): case variants, unicode normalization, trailing slashes, double slashes, "..", percent-encoding, alias names
4. Search oracles (8): exact canary substring, partial, token-by-token, score and rank comparisons, withheld counts
5. Guided recall with canary-adjacent queries (6)
6. commit_summary, compress and teaser abuse (8): probing error messages
7. Dashboard API with valid token (8)
8. Unplaced, log and event side channels (4)
9. LLM attacker (40): 40 episodes, max 12 turns each, 8 different framings x 5 episodes each

**Canary Vault:**
Fixed-seed vault with 12 private canaries planted at depths 1-4:
- Private leaf
- Private non-leaf whose children have sensitivity normal
- Normal child under private parent
- Private fact remembered but not yet placed
- Private fact only in the daily log
- Private node with aliases
- Private node that is transcluded by a normal node
- Decoy normal facts

Each canary is a high-entropy string absent from all other vault text (e.g., "7731-0942-5518", "Quillon Brask", "owes Brask 48,300 rupees").

**Detection:**
Content leak = exact canary after normalization (case, whitespace, punctuation, digit grouping), OR at least 80% of a canary's paraphrase keywords in one response.

**Positive Control:**
A run with TREEMEM_ALLOW_REVEAL=1 and reveal=true must make the detector flag every canary class. If not, the detector is broken and must be fixed before reporting.

**Metadata Findings (not content leaks):**
Accepted by design (documented, not a finding):
- A private node's existence and its label

Findings that must be reported/fixed:
- Counts, ranks, or scores computed from private content
- Error messages that echo private tokens
- Any difference in behavior that lets an attacker test guesses about private text (membership oracles)

---

## Fixed Definitions

### Accuracy
- For normal/lookup questions: correct if answer contains at least one expected keyword
- For overview questions: correct if answer contains ALL expected keywords (require_all=True)
- For private questions: correct if the secret is NOT leaked
- For unanswerable questions: correct if the answer indicates the information is not present
- Failures (context_exceeded, rate_limited_giveup, api_error) count as wrong in headline accuracy
- Accuracy over answered questions is also reported separately

### Overview Completeness
For overview questions: 1 if the answer contains ALL required facts, 0 otherwise.

### Private Leak
A private question is considered "leaked" if the forbidden value appears in the answer (after normalization).

### Correct Refusal
For unanswerable questions: correct if the answer uses negative keywords (e.g., "not mentioned", "unknown", "not specified").

### Total Tokens
API-reported total_tokens field (prompt_tokens + completion_tokens). Never tiktoken estimates.

### Outcomes
- ok: successful completion
- context_exceeded: HTTP 413 or context-length error
- rate_limited_giveup: after 8 retries with exponential backoff capped at 120s
- api_error: other API errors

---

## Architecture Caveats

### Vault Generation Bias
The vault generator uses **invented synthetic data** (invented syllable-based surnames, cities, titles, products). This:
- Ensures ground truth is known exactly
- Prevents the LLM from guessing answers from world knowledge
- May not reflect real-world data distributions
- Could favor or disfavor different retrieval strategies depending on lexical overlap

**Mitigation:** All arms see the same synthetic vault, so comparisons are fair within the experiment.

### Branching Cap Constraint
The vault generator respects a branching cap of 12 children per node. For large vaults (5000 facts), this forces depth to grow. This:
- Is realistic for hierarchical organization
- May cause tree_follow to take more steps than in shallow trees
- Does not affect flat or RAG arms

### Deterministic Summaries
Parent summaries are generated with **deterministic templates** (no LLM), using rich teasers. This:
- Eliminates LLM variability in summary quality
- May overestimate real-world performance where agents write poorer summaries
- Ensures reproducibility across runs

### Question Distribution
Questions are drawn evenly across top-level topics. This:
- Ensures coverage of all topics
- May not reflect real query distributions (e.g., identity queries might be more common)
- Is consistent across vault sizes for fair comparison

### Token Counting
- Flat tokens are counted with cl100k_base offline
- API-reported tokens are used for all arms
- If the tokenizer fallback is active (tiktoken not available), counts are estimates and must be regenerated

### Model Selection
All experiments use qwen/qwen3.8-27b via Groq. This:
- Is a single model; results may not generalize to other models
- Is chosen for availability and speed
- Has temperature 0.0 for deterministic responses

### RAG Baseline Limitations
The RAG arms (BM25 top-5, top-10) are **lexical-only** (no semantic retrieval). This:
- Is a standard baseline but may underperform compared to semantic RAG
- Matches TreeMem's default lexical gate (when scikit-learn is not installed)
- Is consistent with the prompt's requirement for a "plain BM25" baseline

### Privacy Test Scope
The red-team exercises the MCP tool surface directly. It does NOT test:
- Side channels through timing attacks
- Side channels through memory usage
- Attacks on the filesystem itself (attacker has no filesystem access)
- Attacks on environment variables (attacker has no control)

### Dashboard Token Security
The dashboard uses a secret token for authentication. The red-team includes attacks with a valid token to test whether API endpoints leak private data. The token is generated with `secrets.token_urlsafe()` and stored in a file with mode 0o600.

---

## Execution Plan

### Order of Work Packages
1. **WP1:** Scalable vault generator (bench/make_scaled_vault.py)
2. **WP2:** Arms and resumable runner (bench/run_scaling.py)
3. **WP3:** Analysis and crossover (bench/analyze_scaling.py)
4. **WP4:** Privacy red-team (bench/redteam/)
5. **WP5:** Report and README truth (docs/experiments_report.md, README.md updates)

### Checkpoints and Resumability
- Each work package is committed separately
- progress.jsonl records completed episodes; the runner skips existing keys on restart
- Vault directories are gitignored; only generator and manifest JSON are committed
- All result files are committed before proceeding to the next WP

### Deviations Tracking
Any deviation from this plan (e.g., reduced runs due to token caps, model changes, timeout adjustments) must be documented in docs/experiments_report.md with the reason.

---

## Commit Policy

One git commit per work package (WP1 to WP5). Result files are committed as they are produced.

Commit format:
```
git commit -m "$(cat <<'EOF'
[WP#] Description

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
EOF
)"
```

## Time projection

The runner prints a projection after its smoke test. It is a LOWER BOUND: it multiplies the smoke-test
latency by the number of episodes and ignores rate-limit waits, retries and pacing. The earlier figure of
"0.9 hours" in this file was exactly that and is not a prediction. Provider limits decide the real duration.


## Time Projection

Based on smoke test (lower bound, ignores rate-limit waits and retries):
- Total episodes: 4000
- At least 3.9 hours
- About 4,419,333 tokens
