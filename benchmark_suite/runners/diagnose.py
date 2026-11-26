"""Diagnostic experiment: per-stage retrieval funnel audit for TreeMem arms.

For every query and arm this records where relevant memories are lost:
index hits -> privacy withholding -> entry->memory mapping -> gate/traversal
-> packed context. A vault audit and an arm-contamination check quantify
shared-state bugs (e.g. the guided_no_fallback search monkeypatch).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from treemem.descent_gate import query_word_groups
from treemem.tree_manager import TreeManager

from ..adapters.treemem import TreeMemGuidedRetriever, TreeMemSearchRetriever, TreeMemVault, build_arm
from ..common import environment_manifest, json_dump, jsonl_load
from ..metrics.ranking import evaluate_ranking
from .retrieval import load_memories, load_queries

DIAGNOSE_ARMS = (
    "flat_all", "bm25", "dense", "hybrid", "hybrid_rerank",
    "treemem_manual", "treemem_guided", "treemem_guided_no_fallback", "treemem_search",
)


def _recall(ids: Sequence[str], query: Any) -> float:
    rel = query.relevant_memory_ids or []
    if not rel:
        return 1.0 if not ids else 0.0
    top = set(ids)
    return sum(1 for rid in rel if rid in top) / len(rel)


def _search_audit(mgr: TreeManager, vault: TreeMemVault, query: Any, limit: int = 200) -> Dict[str, Any]:
    """Stage funnel for treemem_search: raw index hits -> visible -> mapped -> recall."""
    raw = mgr.index.query(query.question, limit=limit)
    visible = []
    withheld_private = 0
    withheld_unplaced = 0
    for hit in raw:
        path = hit.get("path", "") if isinstance(hit, dict) else ""
        sens = hit.get("sensitivity", "normal") if isinstance(hit, dict) else "normal"
        if mgr.is_private(path):
            withheld_private += 1
            continue
        if (not path or path == "unplaced") and sens == "private":
            withheld_unplaced += 1
            continue
        visible.append(hit)
    mapped_ids = []
    unmapped = 0
    for hit in visible:
        mid = vault.memory_for_entry(hit.get("entry_id"), hit.get("text"))
        if mid:
            mapped_ids.append(mid)
        else:
            unmapped += 1
    return {
        "search_raw_hits": len(raw),
        "search_visible_hits": len(visible),
        "search_withheld_private": withheld_private,
        "search_withheld_unplaced": withheld_unplaced,
        "search_mapped_hits": len(mapped_ids),
        "search_unmapped_hits": unmapped,
        "search_recall": _recall(mapped_ids, query),
        "search_top_entry_ids": [h.get("entry_id") for h in raw[:10]],
    }


def _guided_audit(result_meta: Dict[str, Any], query: Any) -> Dict[str, Any]:
    traversal = result_meta.get("traversal") or []
    root_scores = traversal[0] if traversal else {}
    final_path = result_meta.get("final_path") or ""
    expected = query.expected_path or ""
    return {
        "guided_stopped_reason": result_meta.get("stopped_reason"),
        "guided_steps": result_meta.get("steps"),
        "guided_final_path": final_path,
        "guided_path_match": (final_path == expected) if expected else None,
        "guided_parent_score": root_scores.get("parent_score"),
        "guided_child_score": root_scores.get("child_score"),
        "guided_facts": result_meta.get("facts_returned"),
        "guided_search_hits": result_meta.get("search_hits_returned"),
        "guided_payload_tokens": result_meta.get("payload_tokens_final"),
        "guided_fallback_suppressed": result_meta.get("fallback_hits_suppressed"),
    }


def _teaser_coverage(mgr: TreeManager, query_text: str, path: str = "/") -> Optional[float]:
    """Fraction of query content-word groups literally present in child teasers at `path`."""
    try:
        payload = mgr.recall(path=path, query=None, follow=False)
    except Exception:
        return None
    children = payload.get("children") or []
    if not children:
        return None
    teaser_text = " ".join(f"{c.get('label', '')} {c.get('teaser', '')}" for c in children).lower()
    groups = query_word_groups(query_text, normalize=True)
    if not groups:
        return None
    hits = 0
    for word, _syns in groups:
        if word and word in teaser_text:
            hits += 1
    return hits / len(groups)


def _vault_audit(vault: TreeMemVault) -> Dict[str, Any]:
    mgr = vault.manager
    if mgr is None:
        return {"error": "no manager"}
    entry_docs = len(mgr.index.entry_docs or [])
    placement_coverage = (len(mgr.index.placement_table) / entry_docs) if entry_docs else 0.0
    all_paths = mgr.health_checker.get_all_node_paths()
    leaf_nodes = 0
    total_facts = 0
    private_nodes = 0
    for p in all_paths:
        node = mgr.store.read_node(p)
        if node is None:
            continue
        if node.sensitivity == "private":
            private_nodes += 1
        if mgr.store.is_leaf(p):
            leaf_nodes += 1
            total_facts += len(node.facts or [])
    try:
        health = mgr.health_checker.check_all()
        violations = len(health.get("violations", []))
    except Exception as exc:
        violations = -1
    return {
        "entry_docs": entry_docs,
        "placement_table_size": len(mgr.index.placement_table),
        "placement_coverage": placement_coverage,
        "node_count": len(all_paths),
        "leaf_nodes": leaf_nodes,
        "total_leaf_facts": total_facts,
        "private_nodes": private_nodes,
        "health_violations": violations,
        "bm25_fitted": mgr.index.bm25_entries is not None,
    }


def contamination_check(vault: TreeMemVault, memories: Sequence[Any], queries: Sequence[Any], sample_k: int = 25) -> Dict[str, Any]:
    """Compare treemem_search hit counts on the shared manager vs a fresh manager.

    A fresh TreeMemVault on the same vault_root cache-loads an independent
    TreeManager, so any count difference isolates shared-state contamination
    (e.g. the old guided_no_fallback search monkeypatch).
    """
    sample = list(queries)[:sample_k]
    if not sample or vault.manager is None:
        return {"skipped": True}
    # Force construction of the no-fallback retriever on the shared manager,
    # replicating arm-build order poisoning.
    TreeMemGuidedRetriever(vault, disable_fallback=True)
    shared_search = TreeMemSearchRetriever(vault)
    shared_counts = []
    for q in sample:
        try:
            shared_counts.append(shared_search.retrieve(q, k=10).metadata.get("count", 0))
        except Exception:
            shared_counts.append(-1)
    try:
        vault_fresh = TreeMemVault(list(memories), vault.vault_root, rebuild=False)
    except Exception as exc:
        return {"skipped": True, "error": str(exc)}
    if vault_fresh.manager is None:
        return {"skipped": True, "error": "fresh vault has no manager"}
    fresh_search = TreeMemSearchRetriever(vault_fresh)
    fresh_counts = []
    for q in sample:
        try:
            fresh_counts.append(fresh_search.retrieve(q, k=10).metadata.get("count", 0))
        except Exception:
            fresh_counts.append(-1)
    diffs = sum(1 for a, b in zip(shared_counts, fresh_counts) if a != b)
    zero_shared = sum(1 for c in shared_counts if c == 0)
    return {
        "sample_k": len(sample),
        "shared_counts": shared_counts,
        "fresh_counts": fresh_counts,
        "count_mismatches": diffs,
        "shared_zero_rate": zero_shared / max(1, len(sample)),
        "fresh_zero_rate": sum(1 for c in fresh_counts if c == 0) / max(1, len(sample)),
        "contaminated": diffs > 0,
    }


def run_diagnose(
    dataset_dir: Path,
    out_dir: Path,
    arms: Sequence[str] = DIAGNOSE_ARMS,
    split: str = "test",
    limit: Optional[int] = None,
    candidate_k: int = 200,
    check_contamination: bool = True,
    rebuild_vault: bool = False,
) -> Dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dataset_dir / "manifest.json"
    dataset_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    memories = load_memories(dataset_dir / dataset_manifest.get("memories_file", "memories.jsonl"))
    queries = load_queries(dataset_dir / dataset_manifest.get("queries_file", "queries.jsonl"), split=split, limit=limit)

    vault = None
    if any(a.startswith("treemem_") for a in arms) or check_contamination:
        t0 = time.perf_counter()
        vault = TreeMemVault(memories, out_dir / "vault", rebuild=rebuild_vault)
        vault_build_ms = (time.perf_counter() - t0) * 1000
    else:
        vault_build_ms = 0.0

    contamination = contamination_check(vault, memories, queries) if (check_contamination and vault is not None) else {"skipped": True}
    vault_audit = _vault_audit(vault) if vault is not None else {"skipped": True}

    retrievers = {arm: build_arm(arm, memories, vault, k=candidate_k, config={}) for arm in arms}

    manifest = environment_manifest({
        "experiment": "diagnose",
        "dataset_dir": str(dataset_dir),
        "arms": list(arms),
        "split": split,
        "limit": limit,
        "candidate_k": candidate_k,
        "vault_build_ms": vault_build_ms,
        "contamination": {k: v for k, v in contamination.items() if not isinstance(v, list)},
        "vault_audit": vault_audit,
    })
    json_dump(out_dir / "manifest.json", manifest)

    episodes_path = out_dir / "episodes.jsonl"
    done = {row.get("episode_key") for row in jsonl_load(episodes_path)}
    new_rows: List[Dict[str, Any]] = []
    total = len(arms) * len(queries)
    completed = len(done)
    episodes_file = episodes_path.open("a", encoding="utf-8")
    try:
        for arm in arms:
            retriever = retrievers[arm]
            is_search = arm == "treemem_search"
            is_guided = arm in ("treemem_guided", "treemem_guided_no_fallback")
            is_manual = arm == "treemem_manual"
            for query in queries:
                key = f"{arm}|{query.query_id}|diag=1"
                if key in done:
                    continue
                row: Dict[str, Any] = {
                    "episode_key": key,
                    "experiment": "diagnose",
                    "arm": arm,
                    "query_id": query.query_id,
                    "query_category": query.category,
                    "split": query.split,
                    "expected_path": query.expected_path,
                    "relevant_memory_ids": query.relevant_memory_ids,
                }
                t0 = time.perf_counter()
                try:
                    result = retriever.retrieve(query, k=candidate_k, reveal=False)
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    row["latency_ms"] = (time.perf_counter() - t0) * 1000
                    episodes_file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    completed += 1
                    continue
                row["latency_ms"] = (time.perf_counter() - t0) * 1000
                row["context_tokens"] = result.context_tokens
                row["retrieved_memory_ids"] = [i.memory_id for i in result.items]
                row["retrieval_recall"] = _recall(row["retrieved_memory_ids"], query)
                row["metrics"] = evaluate_ranking(row["retrieved_memory_ids"], query.to_dict(), ks=(1, 3, 5, 10))
                row["error"] = result.error

                meta = result.metadata or {}
                if is_search and vault is not None and vault.manager is not None:
                    row.update(_search_audit(vault.manager, vault, query))
                    row["search_arm_count"] = meta.get("count")
                if is_guided:
                    g = _guided_audit(meta, query)
                    # count facts/search hits actually returned in payload units
                    units = meta.get("budget_units") or []
                    g["guided_facts"] = sum(1 for u in units if u.get("kind") == "fact")
                    g["guided_search_hits"] = sum(1 for u in units if u.get("kind") == "search_hit")
                    row.update(g)
                    row["guided_recall"] = _recall(row["retrieved_memory_ids"], query)
                if is_manual:
                    final_path = meta.get("final_path") or ""
                    expected = query.expected_path or ""
                    row["manual_final_path"] = final_path
                    row["manual_path_match"] = (final_path == expected) if expected else None
                    row["manual_tool_calls"] = meta.get("tool_calls")
                    row["manual_visited"] = meta.get("visited")
                # Teaser coverage at root (once per query per treemem arm is wasteful;
                # compute only for guided arms to limit cost).
                if is_guided and vault is not None and vault.manager is not None:
                    row["teaser_coverage_root"] = _teaser_coverage(vault.manager, query.question, "/")
                episodes_file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                completed += 1
                if completed % 200 == 0:
                    episodes_file.flush()
                    print(f"progress {completed}/{total}", flush=True)
    finally:
        episodes_file.close()

    summary = _aggregate_diagnose(out_dir, vault_audit, contamination)
    json_dump(out_dir / "summary.json", summary)
    return {"episodes": str(episodes_path), "completed": completed, "total": total, "manifest": str(out_dir / "manifest.json"), "summary": str(out_dir / "summary.json")}


def _rate(rows: List[Dict[str, Any]], field: str) -> Optional[float]:
    vals = [r[field] for r in rows if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]
    vals += [1.0 if r.get(field) is True else 0.0 for r in rows if isinstance(r.get(field), bool)]
    return (sum(vals) / len(vals)) if vals else None


def _dist(rows: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        v = r.get(field)
        key = str(v) if v is not None else "null"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _aggregate_diagnose(out_dir: Path, vault_audit: Dict[str, Any], contamination: Dict[str, Any]) -> Dict[str, Any]:
    rows = [r for r in jsonl_load(Path(out_dir) / "episodes.jsonl")]
    by_arm: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_arm.setdefault(r.get("arm", "unknown"), []).append(r)
    arms: Dict[str, Any] = {}
    for arm, rs in sorted(by_arm.items()):
        entry: Dict[str, Any] = {
            "count": len(rs),
            "errors": sum(1 for r in rs if r.get("error")),
            "retrieval_recall": _rate(rs, "retrieval_recall"),
        }
        for field in (
            "search_raw_hits", "search_visible_hits", "search_mapped_hits", "search_recall",
            "guided_steps", "guided_parent_score", "guided_child_score", "guided_facts",
            "guided_search_hits", "guided_payload_tokens", "guided_recall",
            "manual_tool_calls", "manual_recall", "teaser_coverage_root",
        ):
            if any(field in r for r in rs):
                entry[field] = _rate(rs, field)
        for field in ("guided_stopped_reason", "guided_path_match", "manual_path_match", "search_arm_count"):
            if any(field in r for r in rs):
                entry[f"dist_{field}"] = _dist(rs, field)
        arms[arm] = entry
    # False-negative prune analysis: for each hierarchical arm, count queries
    # where the global search arm fully recalled the relevant ids but the
    # hierarchical arm did not — evidence the parent gate/pruning lost them.
    search_by_q = {
        r.get("query_id"): r.get("retrieval_recall")
        for r in rows if r.get("arm") == "treemem_search"
    }
    for arm in ("treemem_guided", "treemem_guided_no_fallback", "treemem_manual", "treemem_beam"):
        rs = by_arm.get(arm)
        if not rs:
            continue
        compared = [
            r for r in rs
            if r.get("query_id") in search_by_q
            and r.get("retrieval_recall") is not None
            and search_by_q[r["query_id"]] is not None
        ]
        if not compared:
            continue
        prune_errors = sum(
            1 for r in compared
            if search_by_q[r["query_id"]] >= 1.0 and r["retrieval_recall"] < 1.0
        )
        worse_than_search = sum(
            1 for r in compared
            if r["retrieval_recall"] < search_by_q[r["query_id"]]
        )
        arms[arm]["prune_error_rate_vs_search"] = prune_errors / len(compared)
        arms[arm]["prune_error_count_vs_search"] = prune_errors
        arms[arm]["compared_with_search_n"] = len(compared)
        arms[arm]["worse_than_search_rate"] = worse_than_search / len(compared)
    return {
        "experiment": "diagnose",
        "count": len(rows),
        "vault_audit": vault_audit,
        "contamination": contamination,
        "arms": arms,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run retrieval diagnostics")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--arms", nargs="+", default=list(DIAGNOSE_ARMS))
    ap.add_argument("--split", default="test")
    ap.add_argument("--candidate-k", type=int, default=200)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-contamination-check", action="store_true")
    ap.add_argument("--rebuild-vault", action="store_true")
    args = ap.parse_args(argv)
    print(json.dumps(run_diagnose(
        args.dataset, args.out, args.arms, args.split, args.limit,
        candidate_k=args.candidate_k, check_contamination=not args.no_contamination_check,
        rebuild_vault=args.rebuild_vault,
    ), indent=2, default=str)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
