"""Tests asserting all 8 core system invariants from how_it_should_work.md."""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.health import HealthChecker
from treemem.log_writer import LogWriter
from treemem.store import NodeData, Store
from treemem.tree_manager import TreeManager


@pytest.fixture
def tmp_vault():
    temp_dir = tempfile.mkdtemp(prefix="treemem_test_")
    vault_path = Path(temp_dir)
    yield vault_path
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_invariant_1_every_node_has_summary_md(tmp_vault):
    """Invariant 1: Every node directory in the vault MUST have summary.md."""
    mgr = TreeManager(tmp_vault)
    rem = mgr.remember("User is studying at Metro University", hint="college")
    mgr.place(rem["entry_id"], "college/undergrad")

    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Invariant 1 failed: {health['violations']}"
    assert (tmp_vault / "summary.md").exists()
    assert (tmp_vault / "college" / "summary.md").exists()
    assert (tmp_vault / "college" / "undergrad" / "summary.md").exists()


def test_invariant_2_every_fact_references_existing_log(tmp_vault):
    """Invariant 2: Every fact in a leaf references an existing log entry."""
    mgr = TreeManager(tmp_vault)
    rem = mgr.remember("User likes classical music", hint="interests/music")
    mgr.place(rem["entry_id"], "interests/music")

    health = mgr.health_checker.check_all()
    assert health["ok"] is True

    # Manually inject an invalid fact referencing a fake log entry
    node = mgr.store.read_node("interests/music")
    node.facts.append({"fact": "Fake fact", "entry_id": "2026-01-01#9999"})
    mgr.store.write_node_atomic("interests/music", node)

    health_bad = mgr.health_checker.check_all()
    assert health_bad["ok"] is False
    assert any(v["invariant"] == 2 for v in health_bad["violations"])


def test_invariant_3_children_list_equals_directories(tmp_vault):
    """Invariant 3: ## Children in summary equals the set of child directories."""
    mgr = TreeManager(tmp_vault)
    rem1 = mgr.remember("Fact A", hint="work/proj1")
    mgr.place(rem1["entry_id"], "work/proj1")

    rem2 = mgr.remember("Fact B", hint="work/proj2")
    mgr.place(rem2["entry_id"], "work/proj2")

    health = mgr.health_checker.check_all()
    assert health["ok"] is True

    work_node = mgr.store.read_node("work")
    assert {c["label"] for c in work_node.children} == {"proj1", "proj2"}


def test_invariant_4_rebuild_from_log_preserves_facts(tmp_vault):
    """Invariant 4: Deleting the whole tree and rebuilding from the log yields all facts reachable."""
    mgr = TreeManager(tmp_vault)
    rem1 = mgr.remember("User age is 21", hint="identity/age")
    mgr.place(rem1["entry_id"], "identity/age")

    rem2 = mgr.remember("Favorite language is Python", hint="skills/coding")
    mgr.place(rem2["entry_id"], "skills/coding")

    # Verify search finds them before wipe
    s1 = mgr.search("Python")
    assert len(s1["hits"]) >= 1

    # Delete tree directories (keep log/)
    for item in tmp_vault.iterdir():
        if item.name != "log" and not item.name.startswith("."):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    assert not (tmp_vault / "identity").exists()

    # Rebuild from log
    mgr2 = TreeManager(tmp_vault)
    res = mgr2.rebuild()
    assert res["rebuilt_facts"] == 2

    # Verify reachable via search and nodes exist
    s2 = mgr2.search("Python")
    assert len(s2["hits"]) >= 1
    assert (tmp_vault / "skills" / "coding" / "summary.md").exists()
    assert (tmp_vault / "identity" / "age" / "summary.md").exists()


def test_invariant_5_no_private_child_text_in_ancestors(tmp_vault):
    """Invariant 5: No private child's text appears in any ancestor summary."""
    mgr = TreeManager(tmp_vault)
    rem = mgr.remember("User secret passport number is AB987654321", hint="personal/secret")
    mgr.place(rem["entry_id"], "personal/secret", sensitivity="private")

    # Attempt to commit a summary at 'personal' leaking secret passport number
    leaky_summary = """---
name: personal
dirty: false
---
Personal records with secret passport number AB987654321.

## Children
- [[secret]] - private details
"""
    commit_res = mgr.commit_summary("personal", leaky_summary)
    assert commit_res["ok"] is False
    assert "leaks" in commit_res["error"]


def test_invariant_6_dirty_propagation(tmp_vault):
    """Invariant 6: A write under node N sets dirty on N and all its ancestors; nothing else."""
    mgr = TreeManager(tmp_vault)
    # Clean tree setup
    r1 = mgr.remember("Root fact", hint="general")
    mgr.place(r1["entry_id"], "general")

    r2 = mgr.remember("Topic A fact", hint="topic_a/sub_a")
    mgr.place(r2["entry_id"], "topic_a/sub_a")

    r3 = mgr.remember("Topic B fact", hint="topic_b/sub_b")
    mgr.place(r3["entry_id"], "topic_b/sub_b")

    # Clean summaries
    mgr.commit_summary("topic_b/sub_b", "---\nname: sub_b\ndirty: false\n---\nClean sub B summary.\n")
    mgr.commit_summary("topic_b", "---\nname: topic_b\ndirty: false\n---\nClean topic B summary.\n\n## Children\n- [[sub_b]] - details\n")

    assert mgr.store.read_node("topic_b").dirty is False
    assert mgr.store.read_node("topic_b/sub_b").dirty is False

    # Now write to topic_a/sub_a
    r4 = mgr.remember("New fact in sub A", hint="topic_a/sub_a")
    mgr.place(r4["entry_id"], "topic_a/sub_a")

    # Invariant: topic_a/sub_a, topic_a, and root ('') MUST be dirty; topic_b MUST remain clean
    assert mgr.store.read_node("topic_a/sub_a").dirty is True
    assert mgr.store.read_node("topic_a").dirty is True
    assert mgr.store.read_node("").dirty is True
    assert mgr.store.read_node("topic_b").dirty is False
    assert mgr.store.read_node("topic_b/sub_b").dirty is False


def test_invariant_7_atomic_writes_no_stray_tmp(tmp_vault):
    """Invariant 7: Writes are atomic; a killed process never leaves half-written summaries."""
    mgr = TreeManager(tmp_vault)
    node = NodeData(name="test_node", summary="Initial valid summary.")
    mgr.store.write_node_atomic("test_node", node)

    # Check summary exists and no .tmp files exist
    assert mgr.store.exists("test_node")
    assert len(list(tmp_vault.rglob("*.tmp"))) == 0

    # Simulate stray tmp file from an interrupted write
    stray_tmp = tmp_vault / "test_node" / "summary.md.tmp"
    with open(stray_tmp, "w") as f:
        f.write("half written corrupted garbage")

    health_dirty = mgr.health_checker.check_all()
    assert health_dirty["ok"] is False
    assert any(v["invariant"] == 7 for v in health_dirty["violations"])

    # Startup cleanup clears stray .tmp files
    mgr.store.cleanup_temp_files()
    assert not stray_tmp.exists()


def test_invariant_8_log_is_append_only(tmp_vault):
    """Invariant 8: Log files are never modified, only appended."""
    lw = LogWriter(tmp_vault)
    eid1 = lw.append("First fact")
    eid2 = lw.append("Second fact")
    eid3 = lw.append("Third fact")

    assert eid1.endswith("#1")
    assert eid2.endswith("#2")
    assert eid3.endswith("#3")

    entries = lw.read_all_entries()
    assert len(entries) == 3
    assert [e["line"] for e in entries] == [1, 2, 3]
