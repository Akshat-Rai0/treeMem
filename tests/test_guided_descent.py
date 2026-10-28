"""Tests for read-only guided descent: recall(path, query, follow=True)."""

import shutil
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager

SAMPLE_VAULT = Path(__file__).resolve().parent.parent / "examples" / "sample_memory"


def _copy_vault(tmp_path: Path) -> Path:
    target = tmp_path / "vault"
    shutil.copytree(
        SAMPLE_VAULT,
        target,
        ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"),
    )
    return target


@pytest.fixture
def mgr(tmp_path):
    vault = _copy_vault(tmp_path)
    return TreeManager(vault)


def _scripted_gate(actions):
    """Build a fake gate.evaluate that returns the given gate dicts in order."""
    calls = {"i": 0}

    def fake_evaluate(query, parent_path, parent_summary, children=None):
        idx = min(calls["i"], len(actions) - 1)
        calls["i"] += 1
        return dict(actions[idx])

    return fake_evaluate


def _snapshot(vault_dir: Path):
    """Map of relative path -> bytes for every file except observability dirs."""
    snap = {}
    for f in sorted(vault_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(vault_dir)
        if rel.parts and rel.parts[0] in (".events", ".locks"):
            continue
        snap[str(rel)] = f.read_bytes()
    return snap


def test_default_follow_false_is_unchanged(mgr):
    res = mgr.recall("/", query="What is my name?")
    assert "traversal" not in res
    assert "stopped_reason" not in res
    assert "gate" in res


def test_follow_without_query_behaves_like_plain_recall(mgr):
    res = mgr.recall("/", follow=True)
    assert "traversal" not in res
    assert res["path"] == "/"


def test_stops_at_root_when_sufficient(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "stop", "parent_score": 0.9, "child_score": 0.1},
    ])
    res = mgr.recall("/", query="who is the user", follow=True)
    assert res["final_path"] == "/"
    assert res["steps"] == 0
    assert res["stopped_reason"] == "stop"
    assert len(res["traversal"]) == 1


def test_follows_root_to_branch_to_leaf(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "descend", "suggested_child": "identity", "parent_score": 0.1, "child_score": 0.8},
        {"action": "descend", "suggested_child": "age", "parent_score": 0.1, "child_score": 0.9},
        {"action": "stop", "parent_score": 0.9, "child_score": 0.0},
    ])
    res = mgr.recall("/", query="how old am I", follow=True)
    assert res["final_path"] == "identity/age"
    assert res["steps"] == 2
    assert res["stopped_reason"] == "leaf"
    assert [t["path"] for t in res["traversal"]] == ["/", "identity", "identity/age"]
    facts_text = " ".join(f["fact"] for f in res["facts"])
    assert "28" in facts_text


def test_stops_before_private_child(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "descend", "suggested_child": "finance", "parent_score": 0.1, "child_score": 0.8},
        {"action": "descend", "suggested_child": "banking", "parent_score": 0.1, "child_score": 0.9},
    ])
    # finance itself is normal, banking is private.
    res = mgr.recall("/", query="what is my bank balance", follow=True)
    assert res["stopped_reason"] == "private"
    assert res["stopped_at_private"] is True
    assert res["suggested_child"] == "banking"
    assert res["final_path"] == "finance"
    assert "reveal=true" in res["message"]
    # Private content must not appear anywhere in the response.
    private_node = mgr.store.read_node("finance/banking")
    assert private_node is not None
    private_text = private_node.summary.strip()
    assert private_text not in str(res)
    for fact in private_node.facts:
        assert fact["fact"] not in str(res)


def test_respects_max_depth(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "descend", "suggested_child": "identity", "parent_score": 0.1, "child_score": 0.8},
        {"action": "descend", "suggested_child": "age", "parent_score": 0.1, "child_score": 0.9},
    ])
    res = mgr.recall("/", query="how old am I", follow=True, max_depth=1)
    assert res["steps"] == 1
    assert res["stopped_reason"] == "max_depth"
    assert res["final_path"] == "identity"


def test_search_fallback_is_bounded(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "search_fallback", "parent_score": 0.0, "child_score": 0.0},
    ])
    res = mgr.recall("/", query="gym", follow=True)
    assert res["stopped_reason"] == "search_fallback"
    assert "search" in res
    assert res["search"]["tokens"] <= 400
    assert res["final_path"] == "/"


def test_missing_suggested_child_does_not_crash(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "descend", "suggested_child": "does_not_exist", "parent_score": 0.1, "child_score": 0.8},
    ])
    res = mgr.recall("/", query="anything", follow=True)
    assert res["stopped_reason"] == "stop"
    assert res["final_path"] == "/"


def test_emits_one_recall_event_per_step(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "descend", "suggested_child": "identity", "parent_score": 0.1, "child_score": 0.8},
        {"action": "descend", "suggested_child": "age", "parent_score": 0.1, "child_score": 0.9},
        {"action": "stop", "parent_score": 0.9, "child_score": 0.0},
    ])
    before = [e for e in mgr.event_bus.get_events(limit=10000) if e.get("type") == "recall" or e.get("event_type") == "recall"]
    mgr.recall("/", query="how old am I", follow=True, session="guided-test")
    after = [e for e in mgr.event_bus.get_events(limit=10000) if e.get("type") == "recall" or e.get("event_type") == "recall"]
    assert len(after) - len(before) == 3


def test_follow_is_read_only(mgr):
    vault = mgr.root_dir
    before = _snapshot(vault)
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "descend", "suggested_child": "identity", "parent_score": 0.1, "child_score": 0.8},
        {"action": "descend", "suggested_child": "age", "parent_score": 0.1, "child_score": 0.9},
        {"action": "stop", "parent_score": 0.9, "child_score": 0.0},
    ])
    mgr.recall("/", query="how old am I", follow=True)
    after = _snapshot(vault)
    assert before == after


def test_real_gate_without_sklearn(mgr, monkeypatch):
    """End-to-end with the real lexical-only gate: must not crash and must return a path."""
    import treemem.descent_gate as dg
    monkeypatch.setattr(dg, "_SKLEARN_AVAILABLE", False)
    res = mgr.recall("/", query="how old am I age", follow=True)
    assert "final_path" in res
    assert res["stopped_reason"] in ("stop", "leaf", "max_depth", "search_fallback", "private")


def test_search_withholds_private_hits(mgr):
    res = mgr.search("bank account routing number", limit=5)
    assert "987654321" not in str(res)
    assert res.get("withheld_private", 0) >= 1


def test_search_reveal_includes_private_hits(mgr):
    res = mgr.search("bank account routing number", limit=5, reveal=True)
    assert "987654321" in str(res)


def test_search_fallback_in_follow_mode_never_leaks_private(mgr):
    mgr.descent_gate.evaluate = _scripted_gate([
        {"action": "search_fallback", "parent_score": 0.0, "child_score": 0.0},
    ])
    res = mgr.recall("/", query="bank account routing number", follow=True)
    assert res["stopped_reason"] == "search_fallback"
    assert "987654321" not in str(res)
