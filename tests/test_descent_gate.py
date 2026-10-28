"""Tests for Heuristic Descent Gate (Predictive Parent-Stop)."""

import pytest
from pathlib import Path
from treemem.descent_gate import DescentGate, _SKLEARN_AVAILABLE, _SYNONYM_MAP
from treemem.tree_manager import TreeManager


@pytest.fixture
def gate():
    return DescentGate(parent_stop_threshold=0.25, descend_delta=0.15)


def test_synonym_map_contains_no_sample_memory_tokens():
    """Verify that _SYNONYM_MAP contains no leaked tokens from examples/sample_memory."""
    banned_tokens = {"alex", "mercer", "apex", "metropolis", "treemem", "techcorp"}
    for key, synonyms in _SYNONYM_MAP.items():
        assert key not in banned_tokens, f"Banned key in _SYNONYM_MAP: {key}"
        for syn in synonyms:
            assert syn not in banned_tokens, f"Banned synonym '{syn}' under key '{key}' in _SYNONYM_MAP"


SAMPLE_CHILDREN = [
    {"label": "identity", "teaser": "Alex Mercer, software engineer in Metropolis"},
    {"label": "projects", "teaser": "TreeMem memory vault, open source Python development"},
    {"label": "hobbies", "teaser": "Cycling, Apex Fitness gym workouts, and photography"},
    {"label": "work", "teaser": "Backend infrastructure at TechCorp, distributed systems"},
]


# ---------------------------------------------------------------------------
# Core DescentGate Unit Tests
# ---------------------------------------------------------------------------

def test_parent_stop_decision(gate):
    """When parent summary directly answers query, gate returns action='stop'."""
    parent_summary = "Alex Mercer is a 29-year-old Software Engineer living in Metropolis."
    eval_res = gate.evaluate(
        query="What is the user's profession?",
        parent_path="/",
        parent_summary=parent_summary,
        children=SAMPLE_CHILDREN,
    )
    assert eval_res is not None
    assert eval_res["action"] == "stop"
    assert eval_res["parent_sufficient"] is True
    assert eval_res["confidence"] > 0.5
    assert eval_res["suggested_child"] is None


def test_descend_decision_when_child_is_more_specific(gate):
    """When parent lacks detail but child teaser has strong match, gate returns action='descend'."""
    parent_summary = "Root memory catalog for Alex Mercer."
    eval_res = gate.evaluate(
        query="Where does Alex do gym workouts and exercise?",
        parent_path="/",
        parent_summary=parent_summary,
        children=SAMPLE_CHILDREN,
    )
    assert eval_res is not None
    assert eval_res["action"] == "descend"
    assert eval_res["parent_sufficient"] is False
    assert eval_res["suggested_child"] == "hobbies"
    assert "hobbies" in eval_res["hint"]


def test_descend_to_projects(gate):
    """Query about open source TreeMem project suggests 'projects' child."""
    parent_summary = "Root memory catalog for Alex Mercer."
    eval_res = gate.evaluate(
        query="What is TreeMem open source repository?",
        parent_path="/",
        parent_summary=parent_summary,
        children=SAMPLE_CHILDREN,
    )
    assert eval_res is not None
    assert eval_res["action"] == "descend"
    assert eval_res["suggested_child"] == "projects"


def test_search_fallback_for_unknown_topic(gate):
    """When neither parent nor children mention the query, gate returns 'search_fallback'."""
    parent_summary = "General notes on Alex Mercer's daily life."
    eval_res = gate.evaluate(
        query="What is the AWS IAM secret key for DynamoDB?",
        parent_path="/",
        parent_summary=parent_summary,
        children=SAMPLE_CHILDREN,
    )
    assert eval_res is not None
    assert eval_res["action"] == "search_fallback"
    assert eval_res["parent_sufficient"] is False


def test_empty_query_returns_none(gate):
    """Empty or whitespace queries return None."""
    assert gate.evaluate("", "/", "summary", SAMPLE_CHILDREN) is None
    assert gate.evaluate("   ", "/", "summary", SAMPLE_CHILDREN) is None


def test_no_children_parent_eval(gate):
    """When node is a leaf (no children), evaluation operates solely on parent summary."""
    parent_summary = "User's favorite coffee is Ethiopian Yirgacheffe pour-over."
    eval_res = gate.evaluate(
        query="What kind of coffee does the user drink?",
        parent_path="preferences/coffee",
        parent_summary=parent_summary,
        children=[],
    )
    assert eval_res is not None
    assert eval_res["action"] == "stop"
    assert eval_res["parent_sufficient"] is True


# ---------------------------------------------------------------------------
# Integration with TreeManager.recall(query=...)
# ---------------------------------------------------------------------------

def test_recall_with_query_populates_gate_field(tmp_path):
    mgr = TreeManager(tmp_path)
    # Write a custom root summary
    mgr.commit_summary("", "Name: Alex Mercer. Software engineer who likes cycling.\n\n## Children\n- [[hobbies]]: Cycling and fitness")

    res = mgr.recall("/", query="What is the user's name?")
    assert "gate" in res
    assert res["gate"]["action"] == "stop"
    assert res["gate"]["parent_sufficient"] is True


def test_recall_without_query_omits_gate_field(tmp_path):
    mgr = TreeManager(tmp_path)
    res = mgr.recall("/")
    assert "gate" not in res


def test_leaf_stops_without_sklearn(monkeypatch):
    """Without scikit-learn the lexical-only score must still let a matching leaf stop."""
    import treemem.descent_gate as dg
    monkeypatch.setattr(dg, "_SKLEARN_AVAILABLE", False)
    local_gate = DescentGate(parent_stop_threshold=0.25, descend_delta=0.15)
    res = local_gate.evaluate(
        query="What kind of coffee does the user drink?",
        parent_path="preferences/coffee",
        parent_summary="User's favorite coffee is Ethiopian Yirgacheffe pour-over.",
        children=[],
    )
    assert res is not None
    assert res["action"] == "stop"
    assert res["parent_sufficient"] is True


def test_weights_lexical_only_when_sklearn_missing(monkeypatch):
    """Lexical-only mode uses 100% lexical weight, so a perfect lexical match scores 1.0."""
    import treemem.descent_gate as dg
    monkeypatch.setattr(dg, "_SKLEARN_AVAILABLE", False)
    local_gate = DescentGate()
    res = local_gate.evaluate(
        query="coffee",
        parent_path="coffee",
        parent_summary="coffee",
        children=[],
    )
    assert res["parent_score"] >= 0.99


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason="scikit-learn not installed")
def test_weights_hybrid_when_sklearn_present():
    """With scikit-learn the score is a 50/50 blend, so it must not exceed 1.0 and must be positive."""
    local_gate = DescentGate()
    res = local_gate.evaluate(
        query="coffee",
        parent_path="coffee",
        parent_summary="coffee",
        children=[],
    )
    assert 0.0 < res["parent_score"] <= 1.0
