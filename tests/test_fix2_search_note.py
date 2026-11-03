"""WP-E: Fix misleading search note to separate private and unplaced withholding."""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wpe_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_unplaced_normal_fact_searchable(vault):
    """Unplaced facts with sensitivity 'normal' should be searchable."""
    mgr = TreeManager(vault)
    # Remember a normal fact without placing it
    entry = mgr.remember("normal unplaced fact", sensitivity="normal")
    result = mgr.search("unplaced")
    assert result["count"] >= 1
    assert "withheld_unplaced" not in result
    assert any(h["entry_id"] == entry["entry_id"] for h in result["hits"])


def test_unplaced_private_fact_withheld(vault):
    """Unplaced facts with sensitivity 'private' should be withheld without reveal."""
    mgr = TreeManager(vault)
    # Remember a private fact without placing it
    entry = mgr.remember("secret unplaced fact", sensitivity="private")
    result = mgr.search("unplaced")
    assert result["count"] == 0
    assert result["withheld_unplaced"] == 1
    assert "note_unplaced" in result
    assert "private" in result["note_unplaced"].lower()


def test_unplaced_private_fact_with_reveal(vault):
    """Unplaced private facts should be returned with reveal=True."""
    mgr = TreeManager(vault)
    entry = mgr.remember("secret unplaced fact", sensitivity="private")
    result = mgr.search("unplaced", reveal=True)
    assert result["count"] >= 1
    assert "withheld_unplaced" not in result
    assert any(h["entry_id"] == entry["entry_id"] for h in result["hits"])


def test_placed_private_fact_withheld(vault):
    """Placed facts under private nodes should be withheld without reveal."""
    mgr = TreeManager(vault)
    entry = mgr.remember("secret placed fact", hint="private/data", sensitivity="private")
    mgr.place(entry["entry_id"], "private/data")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()
    
    result = mgr.search("secret")
    assert result["count"] == 0
    assert result["withheld_private"] == 1
    assert "note_private" in result
    assert "private nodes" in result["note_private"].lower()


def test_placed_private_fact_with_reveal(vault):
    """Placed private facts should be returned with reveal=True."""
    mgr = TreeManager(vault)
    entry = mgr.remember("secret placed fact", hint="private/data", sensitivity="private")
    mgr.place(entry["entry_id"], "private/data")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()
    
    result = mgr.search("secret", reveal=True)
    assert result["count"] >= 1
    assert "withheld_private" not in result
    assert any(h["entry_id"] == entry["entry_id"] for h in result["hits"])


def test_separate_notes_for_private_and_unplaced(vault):
    """Both withheld_private and withheld_unplaced should be reported separately."""
    mgr = TreeManager(vault)
    # Create an unplaced private fact
    entry1 = mgr.remember("unplaced secret", sensitivity="private")
    # Create a placed private fact
    entry2 = mgr.remember("placed secret", hint="private/data", sensitivity="private")
    mgr.place(entry2["entry_id"], "private/data")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()
    
    result = mgr.search("secret")
    assert result["count"] == 0
    assert result["withheld_private"] == 1
    assert result["withheld_unplaced"] == 1
    assert "note_private" in result
    assert "note_unplaced" in result


def test_placed_normal_fact_always_searchable(vault):
    """Placed normal facts should always be searchable."""
    mgr = TreeManager(vault)
    entry = mgr.remember("normal placed fact", hint="public/data", sensitivity="normal")
    mgr.place(entry["entry_id"], "public/data")
    mgr.rebuild_index()
    
    result = mgr.search("normal")
    assert result["count"] >= 1
    assert "withheld_private" not in result
    assert "withheld_unplaced" not in result
