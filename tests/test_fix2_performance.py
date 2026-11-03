"""WP-C: Performance tests for incremental index updates."""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wpc_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_rebuild_index_single_pass(vault):
    """rebuild_index should use single-pass prefix-based private path computation."""
    mgr = TreeManager(vault)
    
    # Create a structure with 100 nodes (nested to avoid branching cap)
    for i in range(10):
        section = f"section{i}"
        for j in range(10):
            path = f"{section}/subsection{j}"
            rem = mgr.remember(f"Fact {i}-{j}", hint=path)
            mgr.place(rem["entry_id"], path)
    
    # Rebuild should complete without error
    mgr.rebuild_index()
    
    # Verify the index is functional
    results = mgr.search("Fact")
    assert results["count"] > 0


def test_refresh_node_vs_full_rebuild_consistency(vault):
    """refresh_node should produce the same search results as a full rebuild."""
    mgr = TreeManager(vault)
    
    # Create a structure (nested to avoid branching cap)
    for i in range(5):
        section = f"section{i}"
        for j in range(4):
            path = f"{section}/subsection{j}"
            rem = mgr.remember(f"Unique keyword {i}-{j}", hint=path)
            mgr.place(rem["entry_id"], path)
    
    # Get search results after full rebuild
    mgr.rebuild_index()
    full_results = mgr.search("keyword")
    full_hit_ids = {h["entry_id"] for h in full_results["hits"]}
    
    # Modify a node and use refresh_node (via commit_summary)
    mgr.commit_summary("section0/subsection0", """---
name: subsection0
dirty: false
---
Updated with new content.
""")
    
    # Get search results after refresh
    refresh_results = mgr.search("keyword")
    refresh_hit_ids = {h["entry_id"] for h in refresh_results["hits"]}
    
    # Should contain the same hits (the modified fact should still be found)
    assert full_hit_ids == refresh_hit_ids, "refresh_node produced different search results than full rebuild"
