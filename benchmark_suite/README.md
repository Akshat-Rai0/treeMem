# TreeMem Comprehensive Benchmark Suite

This directory is a separate, reproducible benchmark harness for TreeMem. It does **not** modify TreeMem's retrieval semantics except for verified benchmark blockers (currently the dashboard compress endpoint fix).

## Layout

- `benchmark_suite/` — Python package (`schemas`, `dataset_tools`, `adapters`, `metrics`, `runners`, `reporting`, `cli`).
- `datasets/` — generated dataset manifests and JSONL (large generated vaults may be gitignored).
- `results/` — raw JSONL episodes, manifests, summaries, plots.
- `reports/` — audit, dataset, retrieval, privacy, reliability, and final reports.
- `tests/` — benchmark unit/smoke tests.
- `configs/` — arm and experiment configuration templates.

## Prerequisites

```bash
python3 -m pip install -e .
python3 -m pip install 'treemem[gate,embeddings,test]' matplotlib pandas scipy
```

Dense and reranked arms require local model downloads (`all-MiniLM-L6-v2`, `ms-marco-MiniLM-L-6-v2`). They are optional; if unavailable the arm records `error` instead of substituting another model.

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
python3 -m benchmark_suite.cli report
```

## Full staged commands

```bash
# Generate all scales (queries configurable; default CLI uses 200 for smoke)
for s in 100 1000 10000 50000; do
  python3 -m benchmark_suite.cli generate --scale $s --seed 7 --queries 2000 --out benchmark_suite/datasets/scale_$s --validate
done

# Retrieval per scale/arm set
python3 -m benchmark_suite.cli run retrieval --dataset benchmark_suite/datasets/scale_100 --out benchmark_suite/results/scale_100/retrieval --arms bm25 dense hybrid hybrid_rerank treemem_manual treemem_guided treemem_guided_no_fallback treemem_search --split test --k 10

# Scaling / lifecycle / privacy / reliability / ablation / offline E2E
python3 -m benchmark_suite.cli run scaling --dataset benchmark_suite/datasets/scale_1000 --out benchmark_suite/results/scale_1000/scaling --arms bm25 treemem_guided treemem_search --limit 100
python3 -m benchmark_suite.cli run lifecycle --dataset benchmark_suite/datasets/scale_100 --out benchmark_suite/results/lifecycle
python3 -m benchmark_suite.cli run privacy --dataset benchmark_suite/datasets/scale_100 --out benchmark_suite/results/privacy --limit 40
python3 -m benchmark_suite.cli run reliability --dataset benchmark_suite/datasets/scale_100 --out benchmark_suite/results/reliability --repetitions 5
python3 -m benchmark_suite.cli run ablation --dataset benchmark_suite/datasets/scale_100 --out benchmark_suite/results/ablation --limit 60
python3 -m benchmark_suite.cli run e2e --dataset benchmark_suite/datasets/scale_100 --out benchmark_suite/results/e2e --arms bm25 treemem_guided treemem_search --limit 100 --k 5
```

Resume is automatic for `retrieval`: completed `episode_key`s in `episodes.jsonl` are skipped. Use `python3 -m benchmark_suite.cli resume --run-dir <dir>` to inspect progress.

## Fairness notes

- `bm25` is a **pure** BM25 baseline; TreeMem `search` is its production hybrid/lexical path and is labeled `treemem_search`.
- `dense`, `hybrid`, and `hybrid_rerank` are benchmark-owned baselines, not native TreeMem features.
- `treemem_manual` is a deterministic benchmark policy using only `recall`/`expand`; it is not an LLM agent.
- Offline E2E uses an extractive answerer for pipeline validation only; it is **not** an LLM quality measurement.
