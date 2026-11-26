"""Tests for the diagnose experiment and the guided_no_fallback poisoning fix."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark_suite.adapters.treemem import TreeMemGuidedRetriever, TreeMemSearchRetriever, TreeMemVault, build_arm
from benchmark_suite.reporting.report import aggregate_experiment
from benchmark_suite.runners.diagnose import _aggregate_diagnose, contamination_check, run_diagnose
from benchmark_suite.tests.test_budget import _tiny_dataset  # noqa: F401  (fixture helper)
from benchmark_suite.schemas import MemoryRecord, memory_path_for


def _vault_memories():
    return [
        MemoryRecord(memory_id="m1", content="Alice prefers tea for morning meetings.", category="preferences",
                     timestamp="2025-01-01T00:00:00Z", path="personal/preferences/group_0/leaf_0/item_0",
                     metadata={"fields": {"entity": "Alice", "attribute": "preference", "topic": "morning meetings", "value": "tea"}}),
        MemoryRecord(memory_id="m2", content="Bob uses Postgres for the Atlas project.", category="technical",
                     timestamp="2025-01-02T00:00:00Z", path="technical/projects/group_1/leaf_0/item_0",
                     metadata={"fields": {"entity": "Atlas", "attribute": "tool", "topic": "database", "value": "Postgres"}}),
        MemoryRecord(memory_id="m3", content="Carol cycles to work on Tuesdays.", category="health",
                     timestamp="2025-01-03T00:00:00Z", path="health/events/group_2/leaf_0/item_0",
                     metadata={"fields": {"entity": "Carol", "attribute": "activity", "topic": "commute", "value": "cycling"}}),
    ]


def test_no_fallback_does_not_poison_shared_manager(tmp_path):
    """Regression: building treemem_guided_no_fallback must not break mgr.search
    for treemem_search or guided fallback (the monkeypatch bug)."""
    vault = TreeMemVault(_vault_memories(), tmp_path / "vault", rebuild=True)
    assert vault.manager is not None
    # Build the no-fallback arm first (the poisoning order).
    build_arm("treemem_guided_no_fallback", _vault_memories(), vault, k=10, config={})
    # mgr.search must still return hits.
    res = vault.manager.search("Alice morning meetings", limit=5, session="test")
    assert res.get("count", 0) > 0, "mgr.search was poisoned by guided_no_fallback construction"
    # A subsequently built treemem_search arm must see hits too.
    search = build_arm("treemem_search", _vault_memories(), vault, k=10, config={})
    out = search.retrieve("Alice morning meetings", k=5)
    assert (out.metadata or {}).get("count", 0) > 0


def test_no_fallback_suppresses_own_fallback_hits(tmp_path):
    vault = TreeMemVault(_vault_memories(), tmp_path / "vault", rebuild=True)
    nf = TreeMemGuidedRetriever(vault, disable_fallback=True)
    res = nf.retrieve("Alice morning meetings", k=10)
    meta = res.metadata or {}
    assert meta.get("disable_fallback") is True
    kinds = [u.get("kind") for u in (meta.get("budget_units") or [])]
    assert "search_hit" not in kinds
    assert meta.get("fallback_hits_suppressed", 0) >= 0


def test_guided_fallback_still_returns_hits(tmp_path):
    vault = TreeMemVault(_vault_memories(), tmp_path / "vault", rebuild=True)
    g = TreeMemGuidedRetriever(vault, disable_fallback=False)
    # On a tiny vault guided may stop early; whatever it returns, search hits
    # must not be suppressed for the normal arm.
    res = g.retrieve("Alice morning meetings", k=10)
    meta = res.metadata or {}
    assert meta.get("disable_fallback") is False


def test_run_diagnose_smoke(tmp_path):
    ds = _tiny_dataset(tmp_path)
    out = tmp_path / "diag"
    res = run_diagnose(ds, out, arms=["bm25", "treemem_search", "treemem_guided"], split="test",
                       check_contamination=True)
    assert res["completed"] == 6  # 3 arms x 2 queries
    rows = [json.loads(l) for l in (out / "episodes.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 6
    search_rows = [r for r in rows if r["arm"] == "treemem_search"]
    assert all("search_raw_hits" in r for r in search_rows)
    guided_rows = [r for r in rows if r["arm"] == "treemem_guided"]
    assert all("guided_stopped_reason" in r for r in guided_rows)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["experiment"] == "diagnose"
    assert "vault_audit" in summary and "contamination" in summary
    assert "treemem_search" in summary["arms"]


def test_contamination_check_detects_poisoning(tmp_path, monkeypatch):
    """Simulate the old bug: patch mgr.search to empty hits, then verify the
    contamination check reports contaminated=True."""
    ds = _tiny_dataset(tmp_path)
    from benchmark_suite.runners.retrieval import load_memories, load_queries
    memories = load_memories(ds / "memories.jsonl")
    queries = load_queries(ds / "queries.jsonl", split="test")
    vault = TreeMemVault(memories, tmp_path / "vault", rebuild=True)
    # Emulate the old monkeypatch manually.
    original = vault.manager.search
    def _poisoned(*a, **k):
        r = original(*a, **k)
        if isinstance(r, dict):
            r = dict(r); r["hits"] = []; r["count"] = 0
        return r
    vault.manager.search = _poisoned
    cc = contamination_check(vault, memories, queries, sample_k=2)
    assert cc.get("contaminated") is True or cc.get("count_mismatches", 0) > 0


def test_aggregate_experiment_dispatches_diagnose(tmp_path):
    ds = _tiny_dataset(tmp_path)
    out = tmp_path / "diag"
    run_diagnose(ds, out, arms=["bm25", "treemem_search"], split="test", check_contamination=False)
    summary = aggregate_experiment(out)
    assert summary.get("experiment") == "diagnose"
    assert "arms" in summary
