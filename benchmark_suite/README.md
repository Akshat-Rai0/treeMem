# TreeMem Comprehensive Benchmark Suite

This directory is a separate, reproducible benchmark harness for TreeMem. It measures **when, why, and by how much** TreeMem is better or worse than flat, lexical, dense, hybrid, reranked, and hierarchical baselines under identical memories, queries, budgets, models, and grading rules. It does **not** modify TreeMem retrieval semantics except for verified benchmark blockers (the dashboard compress endpoint fix).

## Layout

- `benchmark_suite/` — Python package: `schemas`, `dataset_tools`, `adapters`, `metrics`, `runners`, `reporting`, `cli`.
- `benchmark_suite/runners/full_suite.py` — staged orchestrator used for the full-scale run.
- `datasets/` — generated dataset manifests and JSONL. Large generated scale datasets are gitignored.
- `results/` — raw JSONL episodes, manifests, summaries, plots. `results/full_suite/` is gitignored because it is large (~173MB).
- `reports/` — audit and generated reports. `reports/full_suite/final_report.md` is committed.
- `tests/` — benchmark unit/smoke tests.
- `configs/` — arm and experiment configuration templates.

## Prerequisites

```bash
python3 -m pip install -e .
python3 -m pip install 'treemem[gate,embeddings,test]' matplotlib pandas scipy
```

Dense and reranked arms require local model weights (`all-MiniLM-L6-v2`, `ms-marco-MiniLM-L-6-v2`). They are optional and cached locally after first use; if unavailable the arm records `error` instead of substituting another model. No paid/API LLM calls are enabled by default.

## What is measured

- Retrieval: Recall/Precision/F1@K, MRR, MAP, nDCG, full-support rate, per-category breakdowns.
- Context efficiency: retrieved context tokens, token reduction vs flat corpus/top-k.
- Latency: per-arm retrieval latency plus component timings where available.
- Scaling: vault build time, disk bytes, RSS, retrieval trends at 100/1k/10k/50k.
- Lifecycle: duplicate insert, rebuild preservation, update/stale-retrieval behavior.
- Privacy: unauthorized disclosure, false denial, authorized reveal control.
- Reliability: crash-recovery scenarios, stray-temp detection, health violations.
- Ablation: guided default/shallow/deep, manual, fallback on/off.
- Offline E2E: extractive answer pipeline validation only — **not** LLM quality.

## Budget-constrained retrieval (equal-budget recall)

The `budget` experiment answers the "strawman baseline" critique directly: instead of comparing TreeMem's ~1.5k-token descent payload against a full-corpus dump, every arm's retrieved context is decomposed into ordered units and **greedily packed under a strict token budget**. Recall is then measured on the memory ids that actually fit — an equal-budget knapsack comparison.

- Units: flat arms contribute one unit per retrieved item in rank order; `treemem_guided`/`treemem_guided_no_fallback` additionally emit `budget_units` metadata (navigational preamble, leaf facts, bounded search hits) so the **full returned payload** is charged, not just mapped facts. `treemem_beam` emits fact units plus a bounded search fallback so parent-level false negatives are measured rather than hidden.
- Packer (`benchmark_suite/budgeting.py`, `budget_packer_v1`): id-bearing units pack first in emission order, zero-id units (preamble) fill leftover budget; oversized units are truncated to the remaining budget; `tokens_used` never exceeds the budget. Greedy first-fit — not optimal 0/1 knapsack.
- Aggregation reports `recall_budget_ci95` bootstrap intervals per arm/budget so small query counts are not oversold.
- Budgets default to `256 512 1024 1465 2048 4096` — 1,465 anchors the historical TreeMem descent-payload figure.
- `--answers` additionally grades an offline **extractive** answer per (arm, query, budget) — pipeline validation only, not an LLM quality measurement. Aggregation reports `answer_f1_ci95` / `answer_correct_ci95` per cell and answer tables in reports.
- `treemem_guided_plus_global` unions guided descent with a bounded global `search` (`plus_global_limit`, default 20 hits) — the parent-bypass safety-net arm.
- Accounting is **final-payload only**: cumulative traversal/wire tokens are not charged (disclosed limitation; wire tokens are reported separately in `docs/portfolio.md`).
- Retrieval runs once per query at `--candidate-k` (default 200); packing is post-hoc per budget, so budgets do not multiply retrieval cost.

```bash
python3 -m benchmark_suite.cli run budget \
  --dataset benchmark_suite/datasets/scale_1000 \
  --out benchmark_suite/results/budget/scale_1000 \
  --arms flat_all bm25 dense hybrid hybrid_rerank treemem_guided treemem_guided_no_fallback treemem_search treemem_manual \
  --split test

python3 -m benchmark_suite.cli analyze --experiment-dir benchmark_suite/results/budget/scale_1000
```

Aggregation produces `summary.json` with per-(arm, budget) `recall_budget`, `recall@5`, `mrr`, `tokens_used`, and `utilization`, plus `recall_vs_budget.png` / `budget_utilization.png` plots and arm × budget pivot tables.

## Retrieval diagnostics (`diagnose` experiment)

When an arm's recall is suspiciously low, `run diagnose` pinpoints *which stage* loses the relevant memories instead of guessing. Per query it records stage-level funnels:

- `treemem_search`: raw `index.query` hits → post-`is_private` visible hits → `memory_for_entry` mapped ids → recall of mapped ids vs `relevant_memory_ids`.
- `treemem_guided`/`treemem_guided_no_fallback`: `stopped_reason` distribution, steps, `final_path` vs `expected_path`, gate `parent_score`/`child_score`, facts/search-hit counts, payload tokens, recall.
- `treemem_manual`: `final_path` vs `expected_path`, tool calls, visited nodes, recall.
- Vault audit (once): entry_docs vs placement coverage, leaf/fact totals, private nodes, health-check violations, BM25 fitted.
- Teaser coverage: fraction of query content words present in root child teasers — quantifies whether summaries carry enough signal for the gate/manual policy.
- Contamination check: `treemem_search` hit counts on the shared vault manager vs a fresh `TreeManager` on the same vault — detects shared-state bugs between arms (this caught the `guided_no_fallback` search monkeypatch that emptied hits for `treemem_search` and guided fallback in earlier runs; **pre-fix `treemem_search`/guided-fallback numbers in `results/full_suite` and early `results/budget` runs are corrupted**).

```bash
python3 -m benchmark_suite.cli run diagnose \
  --dataset benchmark_suite/datasets/scale_1000 \
  --out benchmark_suite/results/diagnose/scale_1000 \
  --split test

python3 -m benchmark_suite.cli analyze --experiment-dir benchmark_suite/results/diagnose/scale_1000
```

## Quick start (smoke)

```bash
# Audit TreeMem capabilities
python3 -m benchmark_suite.cli audit

# Generate a small deterministic dataset
python3 -m benchmark_suite.cli generate --scale 100 --seed 7 --queries 120 --out benchmark_suite/datasets/smoke_100 --validate

# Run retrieval smoke across core arms
python3 -m benchmark_suite.cli run retrieval \
  --dataset benchmark_suite/datasets/smoke_100 \
  --out benchmark_suite/results/smoke/retrieval \
  --arms bm25 treemem_guided treemem_search treemem_manual \
  --split test --k 10 --limit 40 --repetitions 1

# Aggregate and report
python3 -m benchmark_suite.cli analyze --experiment-dir benchmark_suite/results/smoke/retrieval
python3 -m benchmark_suite.cli report --results-root benchmark_suite/results/smoke --reports-root benchmark_suite/reports/smoke
```

## Public benchmark import

LoCoMo and LongMemEval can be normalized into the same `memories.jsonl` / `queries.jsonl` contract, then evaluated with the existing budget/retrieval runners.

```bash
# LoCoMo (expects locomo10.json; see upstream repo for download/license)
python3 -m benchmark_suite.cli import-public --kind locomo \
  --input benchmark_suite/datasets/raw/locomo10.json \
  --out benchmark_suite/datasets/locomo --validate

# LongMemEval (expects longmemeval_s.json / _m / _oracle)
python3 -m benchmark_suite.cli import-public --kind longmemeval \
  --input benchmark_suite/datasets/raw/longmemeval_s.json \
  --out benchmark_suite/datasets/longmemeval_s --limit 100 --validate

# Equal-budget comparison on the imported dataset
python3 -m benchmark_suite.cli run budget \
  --dataset benchmark_suite/datasets/locomo \
  --out benchmark_suite/results/budget/locomo \
  --arms flat_all bm25 dense hybrid hybrid_rerank treemem_guided treemem_guided_no_fallback treemem_search treemem_beam treemem_manual \
  --budgets 256 512 1024 1465 2048 4096
```

`treemem_beam` is a beam-search TreeMem arm: it keeps the top-k child branches per depth and unions results with a bounded `search` fallback, so it measures whether broader traversal fixes parent-summary false negatives instead of assuming the single-path gate is sufficient.

### LoCoMo smoke result (300 test queries, budgets 512/1465/4096)

`recall_budget` mean (95% bootstrap CI) at budget 1465, after content-rich leaf teasers and `treemem_beam` (`beam_width=6`, beam-prior + search union):

| arm | recall@budget | mean tokens |
|---|---:|---:|
| bm25 | 0.377 (0.323–0.423) | 1422.1 |
| treemem_beam | 0.375 (0.324–0.423) | 1432.2 |
| treemem_search | 0.367 (0.315–0.416) | 1428.2 |
| treemem_guided | 0.246 (0.199–0.292) | 186.7 |
| flat_all | 0.000 | 1425.0 |

At budget 4096, `treemem_beam` reaches **0.446** vs BM25 **0.431** and `treemem_search` **0.427**. Interpretation: richer leaf teasers plus wider beam traversal moved TreeMem from near-zero to matching BM25 at 1465 and beating it at 4096 on this slice. Single-path `guided` remains far more token-frugal but lower recall; it needs better stop/descend calibration before it can compete.

## Full staged run

The full run is driven by `benchmark_suite/runners/full_suite.py`, which is resumable through `benchmark_suite/results/full_suite/status.json`. Completed steps are skipped; failed/timed-out steps are retried on the next invocation.

```bash
# Full attempt: 100 / 1k / 10k / 50k, neural arms enabled
python3 -m benchmark_suite.runners.full_suite

# Skip neural arms (dense/hybrid/rerank)
python3 -m benchmark_suite.runners.full_suite --no-neural

# Skip the 50k scale entirely
python3 -m benchmark_suite.runners.full_suite --no-50k

# Smoke-scale check: scale=100 only, 200 queries
python3 -m benchmark_suite.runners.full_suite --quick
```

Per-step CLI equivalents are also available, e.g.:

```bash
python3 -m benchmark_suite.cli generate --scale 1000 --seed 7 --queries 2000 --out benchmark_suite/datasets/scale_1000 --validate
python3 -m benchmark_suite.cli run retrieval --dataset benchmark_suite/datasets/scale_1000 --out benchmark_suite/results/full_suite/scale_1000/retrieval_core --arms bm25 treemem_manual treemem_guided treemem_guided_no_fallback treemem_search --split test --k 10 --repetitions 1
python3 -m benchmark_suite.cli run privacy --dataset benchmark_suite/datasets/scale_1000 --out benchmark_suite/results/full_suite/scale_1000/privacy --limit 200
python3 -m benchmark_suite.cli report --results-root benchmark_suite/results/full_suite --reports-root benchmark_suite/reports/full_suite
```

## Current full-suite status

The last full attempt completed all non-50k work and was then stopped during the 50k core retrieval step. 50k is therefore **attempted but incomplete**, not failed silently.

- Completed: dataset generation/validation for 100/1k/10k/50k; retrieval core+neural+context for 100/1k/10k; scaling and privacy for 100/1k/10k; scale-100 lifecycle/reliability/ablation/E2E.
- Incomplete: 50k retrieval core was killed mid-run; 50k neural previously failed `-9` (likely OOM); 50k scaling/privacy were not completed.
- Report committed: `benchmark_suite/reports/full_suite/final_report.md`.
- Raw artifacts: `benchmark_suite/results/full_suite/` (local only, gitignored).

### Measured retrieval snapshot (test split, k=10)

| Scale | Arm | n | Recall@5 | MRR | Mean ctx tokens | Mean latency ms | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| 100 | bm25 | 245 | 0.814 | 0.767 | 312.1 | 0.11 | 0 |
| 100 | dense | 245 | 0.678 | 0.541 | 318.9 | 100.27 | 0 |
| 100 | hybrid | 245 | 0.771 | 0.675 | 317.3 | 98.39 | 0 |
| 100 | hybrid_rerank | 245 | 0.800 | 0.671 | 322.7 | 472.81 | 0 |
| 100 | treemem_manual | 245 | 0.073 | 0.024 | 14.5 | 10.14 | 0 |
| 100 | treemem_guided | 245 | 0.061 | 0.016 | 6.1 | 10.26 | 0 |
| 100 | treemem_guided_no_fallback | 245 | 0.061 | 0.016 | 6.1 | 10.23 | 0 |
| 100 | treemem_search | 245 | 0.049 | 0.000 | 0.0 | 6.42 | 0 |
| 1000 | bm25 | 701 | 0.696 | 0.706 | 311.4 | 0.70 | 0 |
| 1000 | dense | 701 | 0.460 | 0.388 | 317.2 | 42.65 | 0 |
| 1000 | hybrid | 701 | 0.578 | 0.548 | 314.7 | 49.34 | 0 |
| 1000 | hybrid_rerank | 701 | 0.614 | 0.566 | 316.9 | 252.94 | 0 |
| 1000 | treemem_manual | 701 | 0.037 | 0.036 | 14.4 | 13.27 | 0 |
| 1000 | treemem_guided | 701 | 0.019 | 0.004 | 3.2 | 15.46 | 0 |
| 1000 | treemem_guided_no_fallback | 701 | 0.019 | 0.004 | 3.2 | 15.59 | 0 |
| 1000 | treemem_search | 701 | 0.017 | 0.000 | 0.0 | 10.89 | 0 |
| 10000 | bm25 | 2264 | 0.596 | 0.610 | 311.1 | 10.05 | 0 |
| 10000 | treemem_manual | 2064 | 0.022 | 0.027 | 24.2 | 21.98 | 0 |
| 10000 | treemem_guided | 1768 | 0.008 | 0.002 | 4.9 | 52.05 | 0 |
| 10000 | treemem_guided_no_fallback | 1032 | 0.013 | 0.003 | 5.1 | 42.86 | 0 |
| 10000 | treemem_search | 1032 | 0.012 | 0.000 | 0.0 | 44.12 | 0 |
| 10000 | dense | 2064 | 0.116 | 0.092 | 159.3 | 30.50 | 1032 |
| 10000 | hybrid | 2064 | 0.482 | 0.493 | 312.4 | 45.82 | 0 |
| 10000 | hybrid_rerank | 2064 | 0.505 | 0.495 | 312.0 | 165.28 | 1032 |

Important caveat: scale-10000 `retrieval_core` episode counts are uneven across arms (BM25 n=2264 vs TreeMem arms n=1032–2064), so the 10k TreeMem core numbers should be treated as **partial/suspect** until rerun cleanly. Neural 10k also has ~half episodes with errors on `dense`/`hybrid_rerank`.

## Interpretation notes

- Conventional retrieval dominates this synthetic benchmark: BM25 is strongest overall; hybrid/rerank is close and sometimes better at small scale.
- Dense alone degrades sharply at 10k; hybrid remains more stable.
- TreeMem arms are extremely context-frugal but have very low retrieval recall in this harness. This likely reflects deterministic synthetic summaries/teasers, strict memory-ID mapping, and adapter policy more than a production claim.
- `treemem_search` returning ~0 context on many queries is suspicious and should be failure-analyzed before drawing conclusions; it may be an adapter/mapping issue rather than pure retrieval failure.
- Privacy experiments completed cleanly where run (100/1000 spot checks showed 0 leaks/0 failures); do not claim leak-proof status from the sample.

## Resume / continue

```bash
# Continue the staged full suite (skips completed steps)
python3 -m benchmark_suite.runners.full_suite

# If you want to avoid another long 50k attempt
python3 -m benchmark_suite.runners.full_suite --no-50k

# Inspect status
python3 - <<'PY'
import json,pathlib
s=json.loads(pathlib.Path('benchmark_suite/results/full_suite/status.json').read_text())
for k,v in s.get('steps',{}).items():
    if v.get('status')!='completed': print(k,v.get('status'),v.get('elapsed_s'),v.get('returncode'))
print('updated',s.get('updated_at'))
PY
```

Note: `status.json` can contain stale `running` entries after a killed process; the orchestrator overwrites them when it reaches that step.

## Parallelization note

The current orchestrator is sequential and the hot path is mostly single-core. Safe parallelism would require:

- keeping TreeMem vault construction/index rebuild single-process;
- sharding queries across workers **after** the vault/index exists;
- writing per-shard `episodes.jsonl` files and merging before aggregation;
- limiting concurrent workers to avoid the earlier `-9` OOM failures.

## Fairness notes

- `bm25` is a **pure** BM25 baseline; TreeMem `search` is its production hybrid/lexical path and is labeled `treemem_search`.
- `dense`, `hybrid`, and `hybrid_rerank` are benchmark-owned baselines, not native TreeMem features.
- `treemem_manual` is a deterministic benchmark policy using only `recall`/`expand`; it is not an LLM agent.
- Offline E2E uses an extractive answerer for pipeline validation only; it is **not** an LLM quality measurement.
