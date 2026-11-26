"""Aggregation, tables, plots, and report generation."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..common import ROOT, environment_manifest, json_dump, json_load, jsonl_load
from ..metrics.latency import summarize_values
from ..metrics.ranking import aggregate_rankings, bootstrap_mean_ci, group_metrics


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


def _metrics_rows(rs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    metrics_rows = []
    for r in rs:
        m = dict(r.get("metrics", {}))
        m["query_id"] = r.get("query_id")
        m["category"] = r.get("query_category") or r.get("category")
        m["tokens_used"] = r.get("tokens_used", r.get("context_tokens"))
        m["latency_ms"] = r.get("latency_ms")
        metrics_rows.append(m)
    return metrics_rows


def _cell(rs: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics_rows = _metrics_rows(rs)
    recall_budget_values = [m.get("recall_budget") for m in metrics_rows if m.get("recall_budget") is not None]
    answer_f1_values = [r.get("answer_f1") for r in rs if r.get("answer_f1") is not None]
    answer_correct_values = [
        1.0 if (r.get("answer_grade") or {}).get("correct") else 0.0
        for r in rs if r.get("answer_grade") is not None
    ]
    cell = {
        "overall": aggregate_rankings(metrics_rows),
        "by_category": group_metrics(metrics_rows, "category"),
        "recall_budget_ci95": bootstrap_mean_ci(recall_budget_values),
        "tokens_used": summarize_values([r.get("tokens_used", r.get("context_tokens")) for r in rs]),
        "utilization": summarize_values([r.get("utilization") for r in rs]),
        "errors": sum(1 for r in rs if r.get("error")),
    }
    if answer_f1_values:
        cell["answer_f1_ci95"] = bootstrap_mean_ci(answer_f1_values)
        cell["answer_correct_ci95"] = bootstrap_mean_ci(answer_correct_values)
    return cell


def aggregate_budget(episodes_path: Path, out_dir: Path) -> Dict[str, Any]:
    rows = _rows(episodes_path)
    cells: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    arm_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    budgets = set()
    for r in rows:
        arm = r.get("arm", "unknown")
        budget = r.get("budget")
        budgets.add(budget)
        cells[(arm, budget)].append(r)
        arm_rows[arm].append(r)
    arms: Dict[str, Any] = {}
    for arm, rs in sorted(arm_rows.items()):
        by_budget = {
            str(b): _cell(cells[(arm, b)])
            for (a, b) in sorted(cells, key=lambda kv: (str(kv[0]), kv[1] if kv[1] is not None else -1))
            if a == arm
        }
        arms[arm] = {"by_budget": by_budget, "overall": _cell(rs)["overall"]}
    summary = {
        "experiment": "budget",
        "count": len(rows),
        "budgets": sorted(b for b in budgets if b is not None),
        "arms": arms,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_dump(out_dir / "summary.json", summary)
    return summary


def aggregate_experiment(out_dir: Path) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    episodes = out_dir / "episodes.jsonl"
    if episodes.exists():
        first = None
        with episodes.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    first = json.loads(line)
                    break
        if first and first.get("experiment") == "budget":
            return aggregate_budget(episodes, out_dir)
        if first and first.get("experiment") == "diagnose":
            from ..runners.diagnose import _aggregate_diagnose
            manifest = json_load(out_dir / "manifest.json", {}) or {}
            return _aggregate_diagnose(out_dir, manifest.get("vault_audit", {}), manifest.get("contamination", {}))
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
    if summary.get("experiment") == "diagnose" or any("search_raw_hits" in a for a in arms.values()):
        rate_fields = [
            "retrieval_recall", "search_recall", "guided_recall",
            "search_raw_hits", "search_visible_hits", "search_mapped_hits",
            "guided_steps", "guided_parent_score", "guided_child_score",
            "guided_facts", "guided_search_hits", "guided_payload_tokens",
            "manual_tool_calls", "teaser_coverage_root",
        ]
        present = [f for f in rate_fields if any(f in a for a in arms.values())]
        lines.append("## Table — Diagnose Stage Metrics")
        lines.append("| Arm | n | errors | " + " | ".join(present) + " |")
        lines.append("|---|---:|---:|" + "---:|" * len(present))
        for arm, data in arms.items():
            cells = []
            for f in present:
                v = data.get(f)
                cells.append(f"{v:.3f}" if isinstance(v, (int, float)) else "-")
            lines.append(f"| {arm} | {data.get('count', 0)} | {data.get('errors', 0)} | " + " | ".join(cells) + " |")
        lines.append("")
        for dist_field in ("dist_guided_stopped_reason", "dist_guided_path_match", "dist_manual_path_match"):
            if any(dist_field in a for a in arms.values()):
                lines.append(f"## Table — {dist_field.replace('dist_', '')}")
                lines.append("| Arm | " + " | ".join(sorted({k for a in arms.values() for k in a.get(dist_field, {})})) + " |")
                lines.append("|---|" + "---:|" * len({k for a in arms.values() for k in a.get(dist_field, {})}))
                for arm, data in arms.items():
                    dist = data.get(dist_field, {})
                    lines.append(f"| {arm} | " + " | ".join(str(dist.get(k, 0)) for k in sorted(dist)) + " |")
                lines.append("")
        va = summary.get("vault_audit") or {}
        if va:
            lines.append("## Table — Vault Audit")
            lines.append("| Metric | Value |")
            lines.append("|---|---:|")
            for k, v in va.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")
        cc = summary.get("contamination") or {}
        if cc and not cc.get("skipped"):
            lines.append("## Table — Arm Contamination Check")
            lines.append(f"- sample_k: {cc.get('sample_k')}, count_mismatches: {cc.get('count_mismatches')}, contaminated: {cc.get('contaminated')}")
            lines.append(f"- shared_zero_rate: {cc.get('shared_zero_rate')}, fresh_zero_rate: {cc.get('fresh_zero_rate')}")
            lines.append("")
        return "\n".join(lines)
    if arms and any("by_budget" in a for a in arms.values()):
        budgets = summary.get("budgets") or sorted(
            {int(b) for a in arms.values() for b in a.get("by_budget", {})},
        )
        budgets = [str(b) for b in budgets]
        for metric, label in [("recall_budget", "Recall@Budget"), ("recall@5", "Recall@5"), ("mrr", "MRR")]:
            lines.append(f"## Table — {label} by Token Budget")
            lines.append("| System | " + " | ".join(f"B={b}" for b in budgets) + " |")
            lines.append("|---|" + "---:|" * len(budgets))
            for arm in arms:
                cells = []
                for b in budgets:
                    cell = arms[arm].get("by_budget", {}).get(b, {}).get("overall", {})
                    cells.append(f"{cell.get(metric, 0):.3f}")
                lines.append(f"| {arm} | " + " | ".join(cells) + " |")
            lines.append("")
        lines.append("## Table — Mean Tokens Used by Token Budget")
        lines.append("| System | " + " | ".join(f"B={b}" for b in budgets) + " |")
        lines.append("|---|" + "---:|" * len(budgets))
        for arm in arms:
            cells = []
            for b in budgets:
                cell = arms[arm].get("by_budget", {}).get(b, {}).get("tokens_used", {})
                cells.append(f"{cell.get('mean') or 0:.0f}")
            lines.append(f"| {arm} | " + " | ".join(cells) + " |")
        lines.append("")
        if any("answer_f1_ci95" in arms[a].get("by_budget", {}).get(b, {})
               for a in arms for b in arms[a].get("by_budget", {})):
            for metric, key, label in [
                ("answer_f1", "answer_f1_ci95", "Extractive Answer F1 by Token Budget"),
                ("answer_correct", "answer_correct_ci95", "Extractive Answer Accuracy by Token Budget"),
            ]:
                lines.append(f"## Table — {label}")
                lines.append("| System | " + " | ".join(f"B={b}" for b in budgets) + " |")
                lines.append("|---|" + "---:|" * len(budgets))
                for arm in arms:
                    cells = []
                    for b in budgets:
                        ci = arms[arm].get("by_budget", {}).get(b, {}).get(key) or {}
                        cells.append(f"{ci.get('mean', 0.0):.3f}" if ci else "-")
                    lines.append(f"| {arm} | " + " | ".join(cells) + " |")
                lines.append("")
            lines.append("> Extractive answers are produced by a deterministic offline answerer over the packed context — pipeline validation only, **not** an LLM quality measurement.")
            lines.append("")
        return "\n".join(lines)
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
    if summary.get("experiment") == "diagnose" or any("search_raw_hits" in a for a in arms.values()):
        names = list(arms)
        metric = "guided_recall" if any("guided_recall" in a for a in arms.values()) else "retrieval_recall"
        fig, ax = plt.subplots(figsize=(9, 5))
        vals = [arms[n].get(metric) or 0.0 for n in names]
        ax.bar(names, vals)
        ax.set_ylabel(metric)
        ax.set_title("Diagnose recall by arm")
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
        p1 = out_dir / "diagnose_recall.png"
        fig.tight_layout(); fig.savefig(p1, dpi=150); plt.close(fig)
        # Stopped-reason distribution for guided arms.
        dist_field = "dist_guided_stopped_reason"
        if any(dist_field in a for a in arms.values()):
            reasons = sorted({k for a in arms.values() for k in a.get(dist_field, {})})
            fig, ax = plt.subplots(figsize=(9, 5))
            width = 0.8 / max(1, len(names))
            x = range(len(reasons))
            for i, name in enumerate(names):
                dist = arms[name].get(dist_field, {})
                total = sum(dist.values()) or 1
                ax.bar([xi + i * width for xi in x], [dist.get(r, 0) / total for r in reasons], width, label=name)
            ax.set_xticks([xi + width * len(names) / 2 for xi in x]); ax.set_xticklabels(reasons, rotation=20, ha="right")
            ax.set_ylabel("fraction of queries"); ax.set_title("Guided stopped_reason distribution"); ax.legend(fontsize=8)
            p2 = out_dir / "diagnose_stopped_reasons.png"
            fig.tight_layout(); fig.savefig(p2, dpi=150); plt.close(fig)
            return [str(p1), str(p2)]
        return [str(p1)]
    if any("by_budget" in a for a in arms.values()):
        budgets = sorted({int(b) for a in arms.values() for b in a.get("by_budget", {})})
        names = list(arms)
        fig, ax = plt.subplots(figsize=(9, 5))
        for name in names:
            ys = [arms[name].get("by_budget", {}).get(str(b), {}).get("overall", {}).get("recall_budget", 0.0) for b in budgets]
            ax.plot(budgets, ys, marker="o", label=name)
        ax.set_xscale("log")
        ax.set_xlabel("context token budget")
        ax.set_ylabel("recall@budget")
        ax.set_title("Recall vs context budget")
        ax.legend(fontsize=8)
        p1 = out_dir / "recall_vs_budget.png"
        fig.tight_layout(); fig.savefig(p1, dpi=150); plt.close(fig)

        fig, ax = plt.subplots(figsize=(8, 5))
        for name in names:
            ys = [arms[name].get("by_budget", {}).get(str(b), {}).get("utilization", {}).get("mean") or 0.0 for b in budgets]
            ax.plot(budgets, ys, marker="o", label=name)
        ax.set_xscale("log")
        ax.set_xlabel("context token budget")
        ax.set_ylabel("mean budget utilization")
        ax.set_title("Budget utilization vs context budget")
        ax.legend(fontsize=8)
        p2 = out_dir / "budget_utilization.png"
        fig.tight_layout(); fig.savefig(p2, dpi=150); plt.close(fig)
        return [str(p1), str(p2)]
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
