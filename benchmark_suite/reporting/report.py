"""Aggregation, tables, plots, and report generation."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..common import ROOT, environment_manifest, json_dump, jsonl_load
from ..metrics.latency import summarize_values
from ..metrics.ranking import aggregate_rankings, group_metrics


def _rows(path: Path) -> List[Dict[str, Any]]:
    return jsonl_load(Path(path))


def aggregate_retrieval(episodes_path: Path, out_dir: Path) -> Dict[str, Any]:
    rows = _rows(episodes_path)
    by_arm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_arm[r.get("arm", "unknown")].append(r)
    summary: Dict[str, Any] = {"count": len(rows), "arms": {}}
    for arm, rs in sorted(by_arm.items()):
        metrics_rows = []
        for r in rs:
            m = dict(r.get("metrics", {}))
            m["query_id"] = r.get("query_id")
            m["category"] = r.get("query_category") or r.get("category")
            m["context_tokens"] = r.get("context_tokens")
            m["latency_ms"] = r.get("latency_ms")
            metrics_rows.append(m)
        summary["arms"][arm] = {
            "overall": aggregate_rankings(metrics_rows),
            "by_category": group_metrics(metrics_rows, "category"),
            "context_tokens": summarize_values([r.get("context_tokens") for r in rs]),
            "latency_ms": summarize_values([r.get("latency_ms") for r in rs]),
            "errors": sum(1 for r in rs if r.get("error")),
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_dump(out_dir / "summary.json", summary)
    # CSV flat export
    flat_path = out_dir / "episodes_flat.csv"
    fields = ["arm", "query_id", "category", "recall@5", "precision@5", "mrr", "ndcg@10", "context_tokens", "latency_ms", "error"]
    with flat_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            m = r.get("metrics", {})
            w.writerow({
                "arm": r.get("arm"), "query_id": r.get("query_id"), "category": r.get("query_category") or r.get("category"),
                "recall@5": m.get("recall@5"), "precision@5": m.get("precision@5"), "mrr": m.get("mrr"), "ndcg@10": m.get("ndcg@10"),
                "context_tokens": r.get("context_tokens"), "latency_ms": r.get("latency_ms"), "error": r.get("error"),
            })
    return summary


def aggregate_experiment(out_dir: Path) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    episodes = out_dir / "episodes.jsonl"
    if episodes.exists():
        return aggregate_retrieval(episodes, out_dir)
    for name in ("cases.jsonl", "events.jsonl"):
        p = out_dir / name
        if p.exists():
            rows = _rows(p)
            summary = {"count": len(rows), "rows": rows[:1000]}
            json_dump(out_dir / "summary.json", summary)
            return summary
    return {}


def make_tables(summary: Dict[str, Any]) -> str:
    lines = ["# Benchmark Tables", ""]
    arms = summary.get("arms", {})
    if arms:
        lines.append("## Table A — Retrieval Quality")
        lines.append("| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for arm, data in arms.items():
            o = data.get("overall", {})
            lines.append(f"| {arm} | {o.get('precision@5', 0):.3f} | {o.get('recall@5', 0):.3f} | {o.get('f1@5', 0):.3f} | {o.get('mrr', 0):.3f} | {o.get('map', 0):.3f} | {o.get('ndcg@10', 0):.3f} |")
        lines.append("")
        lines.append("## Table B — Context Efficiency")
        lines.append("| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |")
        lines.append("|---|---:|---:|---:|---:|")
        for arm, data in arms.items():
            c = data.get("context_tokens", {})
            lines.append(f"| {arm} | {c.get('mean') or 0:.1f} | {c.get('median') or 0:.1f} | {c.get('p95') or 0:.1f} | {c.get('max') or 0:.1f} |")
        lines.append("")
        lines.append("## Table D — Latency")
        lines.append("| System | Retrieval P50 | Retrieval P95 | Mean | P99 |")
        lines.append("|---|---:|---:|---:|---:|")
        for arm, data in arms.items():
            l = data.get("latency_ms", {})
            lines.append(f"| {arm} | {l.get('median') or 0:.2f} | {l.get('p95') or 0:.2f} | {l.get('mean') or 0:.2f} | {l.get('p99') or 0:.2f} |")
        lines.append("")
    return "\n".join(lines)


def make_plots(summary: Dict[str, Any], out_dir: Path) -> List[str]:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []
    arms = summary.get("arms", {})
    if not arms:
        return []
    names = list(arms)
    metrics = ["recall@5", "precision@5", "mrr", "ndcg@10"]
    vals = [[arms[a].get("overall", {}).get(m, 0) for a in names] for m in metrics]
    x = range(len(names))
    width = 0.2
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, (m, v) in enumerate(zip(metrics, vals)):
        ax.bar([xi + i * width for xi in x], v, width, label=m)
    ax.set_xticks([xi + width * 1.5 for xi in x]); ax.set_xticklabels(names, rotation=20, ha="right")
    ax.set_ylabel("score"); ax.set_title("Retrieval quality by arm"); ax.legend()
    p1 = out_dir / "retrieval_quality.png"; fig.tight_layout(); fig.savefig(p1, dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    means = [arms[a].get("context_tokens", {}).get("mean") or 0 for a in names]
    ax.bar(names, means)
    ax.set_ylabel("context tokens"); ax.set_title("Mean retrieved context tokens"); plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    p2 = out_dir / "context_tokens.png"; fig.tight_layout(); fig.savefig(p2, dpi=150); plt.close(fig)
    return [str(p1), str(p2)]


def generate_report(results_root: Path, out_path: Path) -> str:
    results_root = Path(results_root)
    sections = ["# TreeMem Comprehensive Benchmark Report", ""]
    sections.append("## Executive Summary")
    sections.append("This report is generated only from measured benchmark outputs. Sections without completed experiments are marked **not run** rather than estimated.")
    sections.append("")
    experiment_dirs = sorted([p for p in results_root.iterdir() if p.is_dir()]) if results_root.exists() else []
    for exp in experiment_dirs:
        summary_path = exp / "summary.json"
        manifest_path = exp / "manifest.json"
        sections.append(f"## {exp.name}")
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            sections.append("```json")
            sections.append(json.dumps(summary, indent=2)[:8000])
            sections.append("```")
            table = make_tables(summary)
            if table.strip():
                sections.append(table)
        else:
            sections.append("**not run / no summary**")
        if manifest_path.exists():
            sections.append("Manifest: `" + str(manifest_path.relative_to(results_root)) + "`")
        sections.append("")
    sections.append("## Reproduction")
    sections.append("See `benchmark_suite/README.md` for exact commands. Raw episodes are under `benchmark_suite/results/`.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(sections), encoding="utf-8")
    return str(out_path)
