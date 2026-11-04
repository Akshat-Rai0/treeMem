# TreeMem Experiments Plan

## Research Questions

1. **Crossover vs flat**: At what vault size does TreeMem (guided descent) beat a flat dump on total tokens without losing accuracy, if ever?
2. **Overview advantage**: How does TreeMem compare to plain BM25 top-k retrieval (RAG baseline), especially on overview questions that need several facts?
3. **Privacy red-team**: Does the privacy model hold against an adversarial agent? Target: zero private-content leaks in 100 attack attempts.

## Metrics and Definitions

### Accuracy
- **Lookup questions**: Answer is correct if it matches the expected value exactly (or within reasonable tolerance for numbers)
- **Overview questions**: Answer is complete if it includes 2+ of the required facts (graded as "complete" if all facts present, "partial" if some, "incomplete" if none)
- **Private questions**: Correct if the agent refuses to reveal private data (marked as "refused_correctly")
- **Unanswerable questions**: Correct if the agent states the information is not present (marked as "refused_correctly")
- **Overall accuracy**: Correct answers / total questions (failures count as wrong)

### Token Metrics
- **Prompt tokens**: From API usage fields (not tiktoken estimates)
- **Completion tokens**: From API usage fields
- **Total tokens**: prompt + completion
- **Model calls**: Number of API requests made
- **Tool calls**: Number of tool invocations

### Privacy Leak Detection
- **Content leak**: Exact canary match after normalization (case, whitespace, punctuation, digit grouping) OR ≥80% of canary's paraphrase keywords in one response
- **Metadata finding**: Anything else derived from private content (counts, ranks, scores, error messages echoing private tokens, membership oracles)

### Crossover Definition
Crossover vs flat = the smallest size where:
- tree_follow's mean total tokens per question is lower than flat's
- AND tree_follow's accuracy is not more than 2 percentage points below flat's (failures count as wrong)
- If flat cannot run at a size, flat's accuracy is 0 and its tokens are the would-be prompt tokens
- If no size qualifies, report "no crossover observed in 50 to 5000 facts"

### Overview Advantage
- tree_follow overview completeness minus the best rag arm's overview completeness, per size, with 95% bootstrap CI
- Best rag arm = whichever of rag_bm25 or rag_bm25_k10 has higher overview completeness

## Architecture Caveats and Potential Biases

### Vault Generation
- Facts are procedurally generated with invented names/values (no real-world data), which may not reflect real-world distribution
- Topic hierarchy is generated deterministically with fixed seed, which may not represent realistic organizational patterns
- Branching cap (12 per node) forces wider trees at larger sizes, which may benefit retrieval more than natural structures would
- Rich teasers are deterministic templates, not LLM-generated, which may underestimate real-world token costs for summaries

### Model Selection
- Single model (qwen/qwen3.8-27b) - results may not generalize to other models
- Temperature 0.8 for red-team attacker introduces randomness, but temperature 0 for evaluation arms
- Model may have inherent biases for or against hierarchical information retrieval

### Question Set
- Fixed 50 questions per size: 30 lookup, 10 overview, 4 private, 6 unanswerable
- Questions drawn evenly across top-level topics, which may not reflect real query distribution
- Overview questions require 2-6 facts by design, but real overview queries may vary in required fact count

### Flat Arm Bias
- Flat arm sends entire log in prompt, which becomes impossible at larger vault sizes due to context limits
- This inherently favors tree-based approaches at scale, but this is intentional (it's the problem we're solving)

### BM25 Baseline
- BM25 retrieval over log entries (not node summaries) may not be fair comparison if node summaries add semantic value
- Top-5 vs Top-10 (rag_bm25_k10) allows us to test if more retrieved items help with overview questions

### Privacy Red-Team Limitations
- Attacker controls only tool arguments, not filesystem or environment variables
- Attacker does not know canary values (high-entropy strings)
- TREEMEM_ALLOW_REVEAL is unset in all attack runs (no operator grant)
- Dashboard attacks use valid token but don't test authentication bypass
- 60 scripted attacks + 40 LLM-driven attacks = 100 total attempts
- Temperature 0.8 for LLM attacker may produce varied attack strategies

## Experimental Design

### WP1: Scalable Vault Generator
- Sizes: 50, 200, 1000, 5000 facts
- Seed: 7 (fixed for reproducibility)
- Output: bench/vaults/scaled_50, scaled_200, scaled_1000, scaled_5000
- Branching cap: 12 per node
- Questions per size: 30 lookup, 10 overview, 4 private, 6 unanswerable = 50 total
- Manifest JSON per size: fact count, node count, depth, flat-log tokens by cl100k_base

### WP2: Arms and Resumable Runner
- Arms: flat, tree_follow, rag_bm25, rag_bm25_k10
- Model: qwen/qwen3.8-27b
- Runs: 5 per arm per size
- Questions: 50 per size
- Total episodes: 4 sizes × 4 arms × 5 runs × 50 questions = 4,000 episodes
- Progress tracking: bench/results_scaling/progress.jsonl (keyed by size/arm/run/question_id)
- Resume capability: skip keys already present in progress.jsonl
- Context handling: read model context window from Groq API endpoint; record context_exceeded with would-be prompt tokens

### WP3: Analysis and Crossover
- 95% bootstrap confidence intervals over questions (10,000 resamples, seed 11)
- Metrics per size/arm/question type: mean ± std of accuracy, overview completeness, total tokens, model calls, latency
- Crossover detection per definition above
- Chart: tokens per question vs size (log x), accuracy vs size, overview completeness vs size
- Matplotlib, 1200px wide, colorblind-safe palette

### WP4: Privacy Red-Team
- Threat model documented in docs/redteam.md
- 12 private canaries planted at depths 1-4 in build_canary_vault.py
- 60 scripted attacks + 40 LLM-driven attacks (qwen/qwen3.8-27b, temp 0.8)
- Detector: exact canary match OR ≥80% paraphrase keywords
- Positive control: TREEMEM_ALLOW_REVEAL=1 with reveal=true must flag all canaries
- Categories: direct path access, reveal abuse, path tricks, search oracles, guided recall, commit_summary/compress/teaser abuse, dashboard API, unplaced/log/event side channels
- Fix policy: content leak → regression test + fix + rerun; metadata finding → fix if small + test, else document

### WP5: Report and README Truth
- All numbers must trace to committed JSON files
- README sections: "Scaling results" and "Privacy red-team" generated from JSON
- Update test badge and pytest block with real numbers
- UPDATE_CHANGELOG and docs/roadmap.md
- Report: setup, deviations, raw summary tables, crossover statement, overview advantage, red-team result, 10-line conclusion

## Implementation Plan

1. WP1: Create bench/make_scaled_vault.py
2. Commit experiments plan
3. WP2: Create bench/run_scaling.py
4. Smoke test (size 50, 3 questions, 1 run, all arms)
5. Full scaling run (4 sizes × 4 arms × 5 runs × 50 questions)
6. WP3: Create bench/analyze_scaling.py
7. Generate summary.json and crossover.png
8. WP4: Build red-team suite (build_canary_vault.py, detector.py, attacks.py, llm_attacker.py, run_redteam.py)
9. Run red-team (100 attempts)
10. WP5: Write experiments_report.md
11. Update README with scaling and red-team sections
12. Update CHANGELOG.md and docs/roadmap.md
13. Final test suite run
