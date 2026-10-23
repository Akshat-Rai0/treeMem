"""Tests for MCP tools: branching cap, split, recall, expand, and compress."""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp()
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_branching_cap_and_split(vault):
    mgr = TreeManager(vault)
    # Set root children_cap to 3
    root_node = mgr.store.read_node("")
    root_node.children_cap = 3
    mgr.store.write_node_atomic("", root_node)

    # Place 3 children: c1, c2, c3
    for i in range(1, 4):
        r = mgr.remember(f"Fact {i}", hint=f"child_{i}")
        mgr.place(r["entry_id"], f"child_{i}")

    # Placing 4th should trigger branching cap error
    r4 = mgr.remember("Fact 4", hint="child_4")
    with pytest.raises(RuntimeError) as exc_info:
        mgr.place(r4["entry_id"], "child_4")
    assert "Branching cap exceeded" in str(exc_info.value)

    # Now split child_1 and child_2 into group_alpha
    split_res = mgr.split("", [{"name": "group_alpha", "children": ["child_1", "child_2"]}])
    assert split_res["ok"] is True

    # Now root has fewer children (group_alpha, child_3), so child_4 can be placed!
    mgr.place(r4["entry_id"], "child_4")
    assert mgr.store.exists("child_4")


def test_recall_never_returns_child_bodies(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Very detailed secret story about childhood", hint="life/childhood")
    mgr.place(rem["entry_id"], "life/childhood")

    # Recall parent 'life'
    res = mgr.recall("life")
    assert "summary" in res
    assert "children" in res
    # Ensure children in recall are only {label, teaser}, no body or facts
    for ch in res["children"]:
        assert "summary" not in ch
        assert "facts" not in ch
        assert "label" in ch
        assert "teaser" in ch


def test_search_fallback(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("My favorite dessert is tiramisu", hint="preferences/food")
    mgr.place(rem["entry_id"], "preferences/food")

    res = mgr.search("tiramisu")
    assert res["count"] >= 1
    hit = res["hits"][0]
    assert "tiramisu" in hit["text"].lower()
    assert hit["path"] == "preferences/food"
