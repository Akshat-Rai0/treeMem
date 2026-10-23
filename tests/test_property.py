"""Property-based randomized sequence tests ensuring invariants are never violated."""

import random
import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager, parent_path


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_property_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_randomized_operations_sequence(vault):
    random.seed(1337)
    mgr = TreeManager(vault)

    topics = ["alpha", "beta", "gamma", "delta"]
    subtopics = ["one", "two", "three"]
    all_target_paths = [f"{t}/{s}" for t in topics for s in subtopics]

    unplaced_entries = []

    for step in range(50):
        action = random.choice(["remember", "place", "recall", "search"])

        if action == "remember" or not unplaced_entries:
            path_hint = random.choice(all_target_paths)
            rem = mgr.remember(f"Property fact {step} at {path_hint}", hint=path_hint)
            unplaced_entries.append((rem["entry_id"], path_hint))
        elif action == "place" and unplaced_entries:
            eid, target = unplaced_entries.pop(0)
            sens = "private" if random.random() < 0.2 else "normal"
            try:
                mgr.place(eid, target, sensitivity=sens)
            except RuntimeError as e:
                # If branching cap exceeded, split or ignore
                if "Branching cap" in str(e):
                    pass
        elif action == "recall":
            existing = mgr.health_checker.get_all_node_paths()
            p = random.choice(existing)
            mgr.recall(p)
        elif action == "search":
            mgr.search("Property")

        # Invariant checks that MUST hold continuously during all operations
        # 1. No stray tmp files
        assert len(list(vault.rglob("*.tmp"))) == 0

        # 2. Every directory in tree has summary.md
        for d in vault.rglob("*"):
            if d.is_dir() and not d.name.startswith(".") and d.name != "log":
                assert (d / "summary.md").exists(), f"Missing summary.md in {d}"

    # Compress all dirty nodes bottom-up
    dirty_nodes = mgr.get_dirty_nodes()
    for p in dirty_nodes:
        node = mgr.store.read_node(p)
        if not node:
            continue
        child_dirs = mgr.store.list_child_dirs(p)
        child_lines = [f"- [[{c}]] - details" for c in child_dirs]
        body = f"Summary for {node.name}.\n\n"
        if child_lines:
            body += "## Children\n" + "\n".join(child_lines) + "\n"

        # Safe commit
        node.summary = f"Valid summary for {node.name}."
        node.children = [{"label": c, "teaser": "details"} for c in child_dirs]
        node.dirty = False
        mgr.store.write_node_atomic(p, node)

    # Recheck all 8 invariants
    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Invariants failed after property run: {health['violations']}"
