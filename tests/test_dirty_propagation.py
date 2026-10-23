"""Tests for dirty flag propagation and bottom-up compression."""

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


def test_dirty_propagation_deep_hierarchy(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Deep nested fact", hint="a/b/c/d")
    mgr.place(rem["entry_id"], "a/b/c/d")

    # Invariant: a/b/c/d, a/b/c, a/b, a, and root are all dirty
    assert mgr.store.read_node("a/b/c/d").dirty is True
    assert mgr.store.read_node("a/b/c").dirty is True
    assert mgr.store.read_node("a/b").dirty is True
    assert mgr.store.read_node("a").dirty is True
    assert mgr.store.read_node("").dirty is True

    # Check dirty list order is deepest first
    dirty_nodes = mgr.get_dirty_nodes()
    assert dirty_nodes[0] == "a/b/c/d"
    assert dirty_nodes[-1] == ""

    # Clean bottom-up
    mgr.commit_summary("a/b/c/d", "---\nname: d\ndirty: false\n---\nSummary D.\n")
    assert mgr.store.read_node("a/b/c/d").dirty is False
    assert mgr.store.read_node("a/b/c").dirty is True
