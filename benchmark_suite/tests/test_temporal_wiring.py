"""Tests for temporal/supersede wiring in the benchmark TreeMem vault builder."""

import json
from pathlib import Path

import pytest

from benchmark_suite.adapters.treemem import TreeMemVault
from benchmark_suite.schemas import MemoryRecord


def _revision_memories():
    old = MemoryRecord(
        memory_id="mem_rev_00001_v1",
        content="User lives in Berlin",
        category="entities",
        timestamp="2024-01-01T00:00:00Z",
        path="identity/city",
        revision_group="rev_x",
        revision_version=1,
        superseded_by="mem_rev_00001_v2",
        temporal_valid_to="2025-06-01T00:00:00Z",
    )
    new = MemoryRecord(
        memory_id="mem_rev_00001_v2",
        content="User lives in Lisbon",
        category="entities",
        timestamp="2025-06-15T00:00:00Z",
        path="identity/city",
        revision_group="rev_x",
        revision_version=2,
        supersedes="mem_rev_00001_v1",
        temporal_valid_from="2025-06-01T00:00:00Z",
    )
    return [old, new]


def test_vault_builder_wires_supersedes(tmp_path):
    vault = TreeMemVault(_revision_memories(), tmp_path / "vault", rebuild=True)
    mgr = vault.manager
    out = mgr.expand("identity/city")
    texts = [f["fact"] for f in out["facts"]]
    assert any("Lisbon" in t for t in texts)
    assert not any("Berlin" in t for t in texts)

    out_all = mgr.expand("identity/city", include_history=True)
    texts_all = [f["fact"] for f in out_all["facts"]]
    assert any("Berlin" in t for t in texts_all)


def test_vault_builder_dependency_order_with_shuffle(tmp_path):
    # New revision listed BEFORE old — builder must reorder.
    memories = list(reversed(_revision_memories()))
    vault = TreeMemVault(memories, tmp_path / "vault", rebuild=True)
    out = vault.manager.expand("identity/city")
    texts = [f["fact"] for f in out["facts"]]
    assert any("Lisbon" in t for t in texts)
    assert not any("Berlin" in t for t in texts)


def test_vault_builder_valid_time_intervals(tmp_path):
    vault = TreeMemVault(_revision_memories(), tmp_path / "vault", rebuild=True)
    mgr = vault.manager
    # valid_from of v2 is 2025-06-01; at 2025-03 only v1 should be visible
    out_past = mgr.expand("identity/city", at="2025-03-01T00:00:00Z")
    texts_past = [f["fact"] for f in out_past["facts"]]
    assert any("Berlin" in t for t in texts_past)
    assert not any("Lisbon" in t for t in texts_past)

    out_now = mgr.expand("identity/city", at="2025-07-01T00:00:00Z")
    texts_now = [f["fact"] for f in out_now["facts"]]
    assert any("Lisbon" in t for t in texts_now)
    assert not any("Berlin" in t for t in texts_now)
