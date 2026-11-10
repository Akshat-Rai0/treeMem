"""Benchmark suite CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .common import ROOT, environment_manifest
from .schemas import json_dump
from .dataset_tools.generate import validate_dataset, write_dataset
from .runners.experiments import run_ablation, run_e2e, run_lifecycle, run_privacy, run_reliability, run_scaling
from .runners.retrieval import run_retrieval
from .reporting.report import aggregate_experiment, generate_report, make_plots, make_tables


def _default_results() -> Path:
    return ROOT / "benchmark_suite" / "results"


def _default_reports() -> Path:
    return ROOT / "benchmark_suite" / "reports"


def cmd_audit(args: argparse.Namespace) -> int:
    report = _default_reports() / "architecture_audit.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("""# TreeMem Architecture Audit

## Status legend
- **implemented**: present in `src/treemem` and exercised by tests or code paths.
- **optional**: requires explicit configuration/provider/credentials.
- **experimental**: present but not part of the default retrieval path.
- **unsupported**: requested benchmark behavior has no native TreeMem API.
- **benchmark-blocking**: would invalidate measurements if left unchanged.

## Capability matrix

| Capability | Status | Evidence / notes |
|---|---|---|
| Append-only log ingestion | implemented | `TreeManager.remember` -> `LogWriter.append`; daily Markdown logs. |
| Hierarchical node storage | implemented | `Store` reads/writes `summary.md` with YAML frontmatter; atomic temp+rename. |
| Placement and dirty propagation | implemented | `TreeManager.place`; `.placements.jsonl`; ancestor dirty flags. |
| Parent-first recall | implemented | `TreeManager.recall(path, query, follow=False)` returns summary+teasers only. |
| Guided traversal | implemented | `_guided_recall` + `DescentGate`; bounded by `max_depth`. |
| Parent-Stop | implemented | Gate `stop` action returns current parent payload. |
| Search fallback | implemented | Guided descent calls bounded `search` on `search_fallback`. |
| BM25 | implemented | `SearchIndex` uses `BM25Okapi` over entries and nodes. |
| TF-IDF candidate scoring | optional | Requires `scikit-learn`; used for placement/gate scoring. |
| Dense embeddings | optional | `EmbeddingProvider`; local sentence-transformers or explicit remote provider. |
| Cross-encoder reranking | unsupported natively | No TreeMem reranker; benchmark supplies `hybrid_rerank` baseline only. |
| RRF hybrid retrieval | unsupported natively | No TreeMem RRF; benchmark supplies `hybrid` baseline. |
| MCP tools | implemented | `remember/place/recall/expand/compress/commit_summary/auto_compress/search/split/rebuild/status`. |
| Compression/summarization | optional | `AutoCompressor` needs an LLM caller/Groq credentials. |
| Persistence/crash recovery | implemented | Atomic writes, append-only log, `.placements.jsonl`, `rebuild`, health checks. |
| Privacy/access control | implemented | Node sensitivity inheritance, withheld hits, reveal policy, private-aware embeddings. |
| Dashboard/observability | implemented with fix | Dashboard exists; compress endpoint had an `AutoCompressor(api_key=...)` blocker, fixed by passing `GroqSummarizerClient.generate` as `llm_caller`. |
| Update/delete lifecycle | partial | Append/replace via `place`, supersession is benchmark metadata; no general delete API. |
| Concurrency | implemented | File locks with root-to-leaf ordering; tests cover concurrent writers. |

## Retrieval pipeline traces

- **Manual TreeMem**: benchmark policy repeatedly calls `recall(follow=False)`, greedily chooses child by teaser overlap, then `expand` on the final node. No server-side gate.
- **Guided TreeMem**: `recall(follow=True)` -> `_guided_recall` -> `DescentGate` -> `descend|stop|search_fallback|leaf|private|max_depth`.
- **Search-only TreeMem**: `TreeManager.search` -> `SearchIndex.query` -> BM25 + overlap/exact bonuses + optional dense similarity. This is **not pure BM25**.
- **Pure BM25 baseline**: benchmark-owned `BM25Okapi` over canonical memory text.
- **Dense/hybrid/rerank baselines**: benchmark-owned adapters; TreeMem is not modified to add RRF or cross-encoder reranking.

## Result-affecting parameters

- `recall(..., follow, max_depth, reveal)`
- `DescentGate`: `parent_stop_threshold`, `min_stop_coverage`, `descend_delta`, `descend_floor`, `descend_ratio`, `specific_term_tiebreak`, `tiebreak_margin`, `eager_descent`
- `search(..., limit, reveal)`
- `EmbeddingProvider` model/dimension/cache/privacy masking
- `Store.lock_paths` timeout and ordering
- `commit_summary` 150-token cap, exact child parity, optimistic `expected_updated`, privacy leak scan
- `children_cap` (default 12), max path depth 8, tokenizer mode
- Benchmark-only: `k`, candidate pool, RRF `k`, reranker model, manual step budget, guided `max_depth`

## Known limitations

- Guided retrieval returns only the final payload plus traversal metadata; intermediate node payloads are timed but not exposed as context.
- Manual traversal is a deterministic benchmark policy, not an LLM agent; comparisons must disclose this asymmetry.
- TreeMem has no native update/delete lifecycle beyond append/replace/journal/rebuild semantics.
- Dense and reranked arms are optional and may be unavailable without model downloads; they are marked `error` rather than silently substituted.
- Synthetic datasets improve ground-truth control but may not represent real user memory distributions.

## Minimal core fixes made

- `src/treemem/dashboard/server.py`: `/api/node/compress` now constructs `GroqSummarizerClient(keys=[groq_key])` and passes `summarizer.generate` to `AutoCompressor(llm_caller=...)`, fixing an unsupported `api_key` argument.
""", encoding="utf-8")
    print(str(report))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    out = Path(args.out)
    manifest = write_dataset(out, args.scale, args.seed, args.queries)
    print(json.dumps(manifest, indent=2))
    if args.validate:
        print(json.dumps(validate_dataset(out), indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    print(json.dumps(validate_dataset(Path(args.dataset)), indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.experiment == "retrieval":
        res = run_retrieval(Path(args.dataset), Path(args.out), args.arms, args.split, args.k, args.limit, args.repetitions, config={}, rebuild_vault=args.rebuild_vault)
    elif args.experiment == "scaling":
        res = run_scaling(Path(args.dataset), Path(args.out), args.arms, args.limit or 50, args.k)
    elif args.experiment == "lifecycle":
        res = run_lifecycle(Path(args.out))
    elif args.experiment == "privacy":
        res = run_privacy(Path(args.dataset), Path(args.out), args.limit or 40)
    elif args.experiment == "reliability":
        res = run_reliability(Path(args.out), args.repetitions or 3)
    elif args.experiment == "ablation":
        res = run_ablation(Path(args.dataset), Path(args.out), args.limit or 40)
    elif args.experiment == "e2e":
        res = run_e2e(Path(args.dataset), Path(args.out), args.arms, args.split, args.limit or 50, args.k, model=args.model)
    else:
        raise SystemExit(f"unknown experiment {args.experiment}")
    print(json.dumps(res, indent=2, default=str)[:12000])
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    exp_dir = Path(args.experiment_dir)
    summary = aggregate_experiment(exp_dir)
    plots = make_plots(summary, exp_dir / "plots") if summary.get("arms") else []
    print(json.dumps({"summary": str(exp_dir / "summary.json"), "plots": plots}, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    results_root = Path(args.results_root) if args.results_root else _default_results()
    reports_root = Path(args.reports_root) if args.reports_root else _default_reports()
    # Aggregate each experiment dir first.
    for exp in results_root.iterdir() if results_root.exists() else []:
        if exp.is_dir():
            aggregate_experiment(exp)
            if (exp / "summary.json").exists():
                make_plots(json.loads((exp / "summary.json").read_text()), exp / "plots")
    out = generate_report(results_root, reports_root / "final_report.md")
    print(out)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    episodes = run_dir / "episodes.jsonl"
    done = sum(1 for _ in episodes.open()) if episodes.exists() else 0
    manifest = run_dir / "manifest.json"
    print(json.dumps({"run_dir": str(run_dir), "episodes_completed": done, "manifest_exists": manifest.exists()}, indent=2))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark_suite", description="TreeMem comprehensive benchmark suite")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audit"); p.set_defaults(func=cmd_audit)

    p = sub.add_parser("generate"); p.set_defaults(func=cmd_generate)
    p.add_argument("--scale", type=int, default=100)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--queries", type=int, default=200)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--validate", action="store_true")

    p = sub.add_parser("validate"); p.set_defaults(func=cmd_validate)
    p.add_argument("--dataset", type=Path, required=True)

    p = sub.add_parser("run"); p.set_defaults(func=cmd_run)
    p.add_argument("experiment", choices=["retrieval", "scaling", "lifecycle", "privacy", "reliability", "ablation", "e2e"])
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--arms", nargs="+", default=["bm25", "treemem_guided", "treemem_search"])
    p.add_argument("--split", default="test")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--rebuild-vault", action="store_true")
    p.add_argument("--model", default=None)

    p = sub.add_parser("analyze"); p.set_defaults(func=cmd_analyze)
    p.add_argument("--experiment-dir", type=Path, required=True)

    p = sub.add_parser("report"); p.set_defaults(func=cmd_report)
    p.add_argument("--results-root", type=Path, default=None)
    p.add_argument("--reports-root", type=Path, default=None)

    p = sub.add_parser("resume"); p.set_defaults(func=cmd_resume)
    p.add_argument("--run-dir", type=Path, required=True)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
