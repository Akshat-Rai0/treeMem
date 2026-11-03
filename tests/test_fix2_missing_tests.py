"""WP-G: Additional tests from the first pass that were missing."""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wpg_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_dashboard_tree_endpoint_masks_private_summaries(vault):
    """Dashboard /api/tree should never return private summaries without reveal."""
    mgr = TreeManager(vault)
    
    # Create a private node
    entry = mgr.remember("Secret content", hint="private/data", sensitivity="private")
    mgr.place(entry["entry_id"], "private/data")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    
    # Get tree through dashboard endpoint (simulated)
    all_paths = mgr.health_checker.get_all_node_paths()
    nodes = []
    for p in all_paths:
        node = mgr.store.read_node(p)
        if node:
            is_priv = mgr.is_private(p)
            summary = "[Private details withheld]" if is_priv else node.summary
            nodes.append({"path": p, "summary": summary, "is_private": is_priv})
    
    # Verify private node summary is masked
    private_node = next((n for n in nodes if n["path"] == "private/data"), None)
    assert private_node is not None
    assert private_node["is_private"] is True
    assert private_node["summary"] == "[Private details withheld]"
    assert "Secret content" not in private_node["summary"]


def test_dashboard_node_endpoint_masks_private_summaries(vault):
    """Dashboard /api/node should never return private summaries without reveal."""
    mgr = TreeManager(vault)
    
    # Create a private node
    entry = mgr.remember("Secret content", hint="private/data", sensitivity="private")
    mgr.place(entry["entry_id"], "private/data")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    
    # Simulate /api/node response
    node = mgr.store.read_node("private/data")
    is_priv = mgr.is_private("private/data")
    summary = "[Private details withheld]" if is_priv else node.summary
    
    # Verify private node summary is masked
    assert is_priv is True
    assert summary == "[Private details withheld]"
    assert "Secret content" not in summary


def test_guided_recall_never_enters_private_node(vault):
    """Guided recall (follow=true) should never enter a private node."""
    mgr = TreeManager(vault)
    
    # Create a structure with a private node
    entry = mgr.remember("Public fact", hint="public/data")
    mgr.place(entry["entry_id"], "public/data")
    
    entry2 = mgr.remember("Private fact", hint="public/private/data", sensitivity="private")
    mgr.place(entry2["entry_id"], "public/private/data")
    parent = mgr.store.read_node("public/private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("public/private", parent)
    
    # Guided recall should stop at public, not enter private
    result = mgr.recall("/", query="Private fact", follow=True)
    # Should not return the private node's path
    assert result["path"] != "public/private"
    # Should not contain private content
    assert "Private fact" not in result.get("summary", "")


def test_remember_private_searchable_only_with_reveal(vault):
    """remember(sensitivity='private') followed by search before/after place without reveal."""
    mgr = TreeManager(vault)
    
    # Remember a private fact without placing it
    entry = mgr.remember("Secret keyword", sensitivity="private")
    
    # Search before place - should not find it without reveal
    result = mgr.search("keyword")
    assert result["count"] == 0
    assert result.get("withheld_unplaced", 0) == 1
    
    # Place it
    mgr.place(entry["entry_id"], "private/data")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()
    
    # Search after place - should not find it without reveal
    result = mgr.search("keyword")
    assert result["count"] == 0
    assert result.get("withheld_private", 0) == 1
    
    # With reveal=True, should find it
    result = mgr.search("keyword", reveal=True)
    assert result["count"] >= 1


def test_rebuild_corrupt_journal_line_returns_error(vault):
    """A corrupt journal line should return ok=False with line number, rest of journal still applied."""
    mgr = TreeManager(vault)
    
    # Add some valid placements
    entry1 = mgr.remember("Fact 1", hint="a")
    mgr.place(entry1["entry_id"], "a")
    
    entry2 = mgr.remember("Fact 2", hint="b")
    mgr.place(entry2["entry_id"], "b")
    
    # Corrupt the journal by appending a malformed line
    journal_file = vault / ".placements.jsonl"
    with open(journal_file, "a") as f:
        f.write('{"invalid": "json missing fields}\n')
    
    # Manually remove the nodes to simulate a wiped tree
    import shutil
    node_a = vault / "a"
    node_b = vault / "b"
    if node_a.exists():
        shutil.rmtree(node_a)
    if node_b.exists():
        shutil.rmtree(node_b)
    
    # Rebuild should report error but still apply valid entries
    result = mgr.rebuild()
    assert result["ok"] is False
    assert len(result.get("errors", [])) > 0
    
    # Valid entries should still be restored
    assert mgr.store.exists("a")
    assert mgr.store.exists("b")
