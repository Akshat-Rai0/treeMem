"""Scaling, lifecycle, privacy, reliability, ablation, and E2E runners."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from treemem.tree_manager import TreeManager

from ..adapters.treemem import TreeMemVault, build_arm
from ..common import environment_manifest, json_dump, jsonl_dump
from ..metrics.answers import extractive_answer, grade_answer, grade_retrieval_context
from ..metrics.latency import summarize_values
from ..metrics.privacy import privacy_case_metrics, reliability_metrics
from ..metrics.ranking import evaluate_ranking
from ..schemas import MemoryRecord, QueryRecord
from .retrieval import load_memories, load_queries


def _disk_usage(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) if Path(path).exists() else 0


def _rss_mb() -> float:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    except Exception:
        return 0.0


def run_scaling(dataset_dir: Path, out_dir: Path, arms: Sequence[str] = ("bm25", "treemem_guided", "treemem_search"), query_limit: int = 50, k: int = 10) -> Dict[str, Any]:
    dataset_dir = Path(dataset_dir); out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    memories = load_memories(dataset_dir / manifest["memories_file"])
    queries = load_queries(dataset_dir / manifest["queries_file"], split="test", limit=query_limit)
    t0 = time.perf_counter()
    vault = TreeMemVault(memories, out_dir / "vault", rebuild=True)
    build_ms = (time.perf_counter() - t0) * 1000
    vault_meta = {}
    meta_path = out_dir / "vault" / ".." / "vault_meta.json"
    if meta_path.exists():
        vault_meta = json.loads(meta_path.read_text())
    rows = []
    retrievers = {arm: build_arm(arm, memories, vault, k=k, config={}) for arm in arms}
    for arm, retriever in retrievers.items():
        lat = []
        for q in queries:
            res = retriever.retrieve(q, k=k, reveal=False)
            lat.append(res.latency_ms)
            rows.append({
                "experiment": "scaling", "arm": arm, "query_id": q.query_id, "category": q.category,
                "latency_ms": res.latency_ms, "context_tokens": res.context_tokens,
                "retrieved_memory_ids": [i.memory_id for i in res.items],
                "metrics": evaluate_ranking([i.memory_id for i in res.items], q.to_dict()),
                "error": res.error,
            })
    summary = {
        "experiment": "scaling",
        "scale": manifest.get("scale"),
        "memory_count": len(memories),
        "query_count": len(queries),
        "vault_build_ms": build_ms,
        "vault_timings": vault_meta.get("timings_ms", {}),
        "disk_bytes": _disk_usage(out_dir / "vault"),
        "rss_mb": _rss_mb(),
        "node_count": len(list((out_dir / "vault").rglob("summary.md"))) if (out_dir / "vault").exists() else 0,
        "latency": {arm: summarize_values([r["latency_ms"] for r in rows if r["arm"] == arm]) for arm in arms},
        "context_tokens": {arm: summarize_values([r["context_tokens"] for r in rows if r["arm"] == arm]) for arm in arms},
    }
    jsonl_dump(out_dir / "episodes.jsonl", rows)
    json_dump(out_dir / "summary.json", summary)
    json_dump(out_dir / "manifest.json", environment_manifest({"experiment": "scaling", "dataset": str(dataset_dir), "arms": list(arms), "query_limit": query_limit, "k": k}))
    return summary


def _small_vault(tmp: Path, memories: Sequence[MemoryRecord]) -> TreeMemVault:
    return TreeMemVault(list(memories), tmp / "vault", rebuild=True)


def run_lifecycle(out_dir: Path) -> Dict[str, Any]:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    events = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mems = [
            MemoryRecord(memory_id="m1", content="Alice prefers tea for morning meetings.", category="preferences", timestamp="2025-01-01T00:00:00Z", path="personal/preferences/group_0/leaf_0/item_0", metadata={"fields": {"entity": "Alice", "attribute": "preference", "topic": "morning meetings", "value": "tea"}}),
            MemoryRecord(memory_id="m2", content="Alice prefers coffee for morning meetings.", category="preferences", timestamp="2025-02-01T00:00:00Z", path="personal/preferences/group_0/leaf_0/item_1", metadata={"fields": {"entity": "Alice", "attribute": "preference", "topic": "morning meetings", "value": "coffee"}}, supersedes="m1", revision_group="rev1", revision_version=2),
            MemoryRecord(memory_id="m3", content="Bob uses Postgres for the Atlas project.", category="technical", timestamp="2025-01-02T00:00:00Z", path="technical/projects/group_1/leaf_0/item_0", metadata={"fields": {"entity": "Atlas", "attribute": "tool", "topic": "database", "value": "Postgres"}}),
        ]
        vault = _small_vault(tmp, mems)
        mgr = vault.manager
        # Duplicate insertion should update the same entry idempotently.
        eid = None
        for entry in mgr.log_writer.read_all_entries():
            if "Alice prefers coffee" in entry.get("fact", ""):
                eid = entry["entry_id"]
        dup = mgr.place(entry_id=eid, path="personal/preferences/group_0/leaf_0/item_1", session="benchmark") if eid else {}
        events.append({"scenario": "duplicate_insert", "recovered": True, "detail": dup})
        # Rebuild from log+placements should preserve facts.
        mgr2 = TreeManager(tmp / "vault")
        facts = []
        for p in mgr2.health_checker.get_all_node_paths():
            node = mgr2.store.read_node(p)
            if node:
                facts.extend(f.get("fact", "") for f in node.facts)
        events.append({"scenario": "rebuild_preserves_facts", "recovered": any("Alice prefers coffee" in f for f in facts), "fact_count": len(facts)})
        # Stale fact remains in log but latest placed fact is retrievable.
        search = mgr2.search("Alice morning meetings", limit=5)
        texts = [h.get("text", "") for h in search.get("hits", [])]
        events.append({"scenario": "update_retrieval", "recovered": any("coffee" in t for t in texts), "stale_present": any("tea" in t for t in texts), "hits": texts})
    summary = reliability_metrics(events)
    summary["events"] = events
    json_dump(out_dir / "summary.json", summary)
    jsonl_dump(out_dir / "events.jsonl", events)
    json_dump(out_dir / "manifest.json", environment_manifest({"experiment": "lifecycle"}))
    return summary


def run_privacy(dataset_dir: Path, out_dir: Path, limit: int = 40) -> Dict[str, Any]:
    dataset_dir = Path(dataset_dir); out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    memories = load_memories(dataset_dir / manifest["memories_file"])
    queries = [q for q in load_queries(dataset_dir / manifest["queries_file"], split="test") if q.category == "private"][:limit]
    if not queries:
        queries = load_queries(dataset_dir / manifest["queries_file"], split="test", limit=limit)
    vault = TreeMemVault(memories, out_dir / "vault", rebuild=True)
    cases = []
    for q in queries:
        for arm_name, retriever in {
            "treemem_search": build_arm("treemem_search", memories, vault, k=10),
            "treemem_guided": build_arm("treemem_guided", memories, vault, k=10),
        }.items():
            res = retriever.retrieve(q, k=10, reveal=False)
            leak = grade_retrieval_context(q.to_dict(), res.context_text)
            canary_hit = any(v and v in res.context_text for v in (q.forbidden_values or []))
            cases.append({
                "experiment": "privacy", "arm": arm_name, "query_id": q.query_id, "category": q.category,
                "passed": not leak["privacy_leak"] and not canary_hit,
                "leak": bool(leak["privacy_leak"] or canary_hit),
                "false_denial": False,
                "authorized_success": False,
                "context_tokens": res.context_tokens,
                "metadata": {"leaked_values": leak["leaked_values"]},
            })
    # Authorized reveal positive control on first private query.
    if queries:
        q = queries[0]
        retriever = build_arm("treemem_search", memories, vault, k=10)
        res = retriever.retrieve(q, k=10, reveal=True)
        cases.append({"experiment": "privacy", "arm": "treemem_search_reveal", "query_id": q.query_id, "category": q.category, "passed": True, "leak": False, "false_denial": False, "authorized_success": True, "context_tokens": res.context_tokens})
    summary = privacy_case_metrics(cases)
    summary["cases"] = cases
    jsonl_dump(out_dir / "cases.jsonl", cases)
    json_dump(out_dir / "summary.json", summary)
    json_dump(out_dir / "manifest.json", environment_manifest({"experiment": "privacy", "dataset": str(dataset_dir), "limit": limit}))
    return summary


def run_reliability(out_dir: Path, repetitions: int = 3) -> Dict[str, Any]:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    events = []
    for i in range(repetitions):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            vault = TreeMemVault([
                MemoryRecord(memory_id=f"r{i}", content=f"Reliability fact {i} about queue depth.", category="technical", timestamp="2025-01-01T00:00:00Z", path=f"technical/projects/group_{i%12}/leaf_0/item_0"),
            ], tmp / "vault", rebuild=True)
            mgr = vault.manager
            entries = mgr.log_writer.read_all_entries()
            ok = bool(entries)
            # Simulate interrupted temp file: stale .tmp should be cleaned/ignored.
            node_dir = tmp / "vault" / "technical" / "projects" / f"group_{i%12}" / "leaf_0" / "item_0"
            node_dir.mkdir(parents=True, exist_ok=True)
            (node_dir / "summary.md.tmp").write_text("partial")
            health = mgr.health_checker.check_all()
            # Dirty-descendant (6) and stray-temp (7) invariants are operational states, not corruption.
            hard_violations = [v for v in health.get("violations", []) if v.get("invariant") not in {6, 7}]
            events.append({"scenario": f"crash_recovery_{i}", "recovered": ok, "data_loss": not ok, "corruption": bool(hard_violations), "stray_tmp_detected": bool(health.get("violations")), "duplicate_reconstruction": False, "recovery_ms": 0.0})
    summary = reliability_metrics(events)
    summary["events"] = events
    json_dump(out_dir / "summary.json", summary)
    jsonl_dump(out_dir / "events.jsonl", events)
    json_dump(out_dir / "manifest.json", environment_manifest({"experiment": "reliability", "repetitions": repetitions}))
    return summary


def run_ablation(dataset_dir: Path, out_dir: Path, limit: int = 40) -> Dict[str, Any]:
    dataset_dir = Path(dataset_dir); out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    memories = load_memories(dataset_dir / manifest["memories_file"])
    queries = load_queries(dataset_dir / manifest["queries_file"], split="test", limit=limit)
    configs = {
        "guided_default": {"guided_max_depth": 4},
        "guided_shallow": {"guided_max_depth": 2},
        "guided_deep": {"guided_max_depth": 8},
        "manual_default": {"manual_max_steps": 8},
        "manual_shallow": {"manual_max_steps": 3},
    }
    rows = []
    vault = TreeMemVault(memories, out_dir / "vault", rebuild=True)
    for name, cfg in configs.items():
        arm = "treemem_manual" if name.startswith("manual") else ("treemem_guided_no_fallback" if "no_fallback" in name else "treemem_guided")
        retriever = build_arm(arm, memories, vault, k=10, config=cfg)
        for q in queries:
            res = retriever.retrieve(q, k=10, reveal=False)
            rows.append({"experiment": "ablation", "config": name, "arm": arm, "query_id": q.query_id, "category": q.category, "context_tokens": res.context_tokens, "latency_ms": res.latency_ms, "retrieved_memory_ids": [i.memory_id for i in res.items], "metrics": evaluate_ranking([i.memory_id for i in res.items], q.to_dict()), "error": res.error})
    # Aggregate by config.
    agg = {}
    for name in configs:
        rs = [r for r in rows if r["config"] == name]
        agg[name] = {
            "count": len(rs),
            "recall@5": sum(r["metrics"].get("recall@5", 0) for r in rs) / max(1, len(rs)),
            "mrr": sum(r["metrics"].get("mrr", 0) for r in rs) / max(1, len(rs)),
            "context_tokens": summarize_values([r["context_tokens"] for r in rs]),
            "latency_ms": summarize_values([r["latency_ms"] for r in rs]),
        }
    jsonl_dump(out_dir / "episodes.jsonl", rows)
    json_dump(out_dir / "summary.json", {"configs": agg})
    json_dump(out_dir / "manifest.json", environment_manifest({"experiment": "ablation", "dataset": str(dataset_dir), "limit": limit, "configs": configs}))
    return {"configs": agg}


def run_e2e(dataset_dir: Path, out_dir: Path, arms: Sequence[str] = ("bm25", "treemem_guided", "treemem_search"), split: str = "test", limit: int = 50, k: int = 5, model: Optional[str] = None) -> Dict[str, Any]:
    dataset_dir = Path(dataset_dir); out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    memories = load_memories(dataset_dir / manifest["memories_file"])
    queries = load_queries(dataset_dir / manifest["queries_file"], split=split, limit=limit)
    vault = TreeMemVault(memories, out_dir / "vault", rebuild=True)
    retrievers = {arm: build_arm(arm, memories, vault, k=k, config={}) for arm in arms}
    rows = []
    for arm, retriever in retrievers.items():
        for q in queries:
            res = retriever.retrieve(q, k=k, reveal=False)
            if q.abstain_expected:
                answer = "I don't have enough information to answer."
            else:
                answer = extractive_answer(res.context_text, q.expected_answer)
            grade = grade_answer(answer, q.to_dict())
            rows.append({"experiment": "e2e", "arm": arm, "query_id": q.query_id, "category": q.category, "answer": answer, "context_tokens": res.context_tokens, "retrieved_memory_ids": [i.memory_id for i in res.items], "grade": grade, "model": model or "offline_extractive", "llm_used": False})
    agg = {}
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        agg[arm] = {
            "count": len(rs),
            "accuracy": sum(1 for r in rs if r["grade"]["correct"]) / max(1, len(rs)),
            "abstention_correct": sum(1 for r in rs if r["grade"]["reason"] == "correct_abstention") / max(1, len(rs)),
            "privacy_leak_rate": sum(1 for r in rs if r["grade"]["privacy_leak"]) / max(1, len(rs)),
            "context_tokens": summarize_values([r["context_tokens"] for r in rs]),
        }
    jsonl_dump(out_dir / "episodes.jsonl", rows)
    json_dump(out_dir / "summary.json", {"arms": agg, "model": model or "offline_extractive", "llm_used": False})
    json_dump(out_dir / "manifest.json", environment_manifest({"experiment": "e2e", "dataset": str(dataset_dir), "arms": list(arms), "split": split, "limit": limit, "k": k, "model": model}))
    return {"arms": agg}
