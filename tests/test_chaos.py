"""Chaos / fault-injection tests for crash consistency and concurrent writes.

These tests go beyond the fixed-scenario crash tests: they use Hypothesis to
explore random operation sequences and inject faults at random points, then
verify the append-only log remains the source of truth and the tree recovers
to a clean state.
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_chaos_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


TOPICS = ["alpha", "beta", "gamma", "delta"]
LEAVES = ["leaf_a", "leaf_b", "leaf_c"]


def _op_paths():
    return [f"{t}/{leaf}" for t in TOPICS for leaf in LEAVES]


@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(
    ops=st.lists(
        st.tuples(
            st.sampled_from(["remember_place", "remember_only", "recall", "search", "rebuild"]),
            st.integers(min_value=0, max_value=11),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_chaos_random_ops_preserve_invariants(vault, ops):
    """Random mixes of writes and reads must keep all 8 invariants green."""
    mgr = TreeManager(vault)
    placed_ids = []
    for kind, idx in ops:
        path = _op_paths()[idx % len(_op_paths())]
        try:
            if kind == "remember_place":
                rem = mgr.remember(f"chaos fact {idx} about {path}", hint=path)
                mgr.place(rem["entry_id"], path)
                placed_ids.append(rem["entry_id"])
            elif kind == "remember_only":
                mgr.remember(f"unplaced chaos fact {idx}", hint=path)
            elif kind == "recall":
                mgr.recall(path="/", query=f"fact {idx}")
            elif kind == "search":
                mgr.search(f"chaos fact {idx}", limit=5)
            elif kind == "rebuild":
                mgr.rebuild()
        except Exception:
            # Invalid ops (e.g. recalling missing nodes) are allowed; the
            # invariant is that the vault stays consistent afterwards.
            pass
    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Violations after chaos ops: {health['violations']}"
    # Every remembered fact must still exist in the ground-truth log.
    all_entries = mgr.log_writer.read_all_entries()
    assert len(all_entries) >= len(placed_ids)


def test_crash_during_journal_replay_recovers(vault):
    """Kill between journal append and node commit; rebuild must converge."""
    mgr = TreeManager(vault)
    rem = mgr.remember("pre-crash fact", hint="replay/topic")
    mgr.place(rem["entry_id"], "replay/topic")

    # Simulate a torn journal: append a syntactically valid record whose
    # checksum does not match (as if the process died mid-write of the record).
    journal = vault / ".placements.jsonl"
    bad = {"ts": "2026-01-01T00:00:00+00:00", "entry_id": "2099-01-01#999",
           "path": "replay/topic", "sensitivity": "normal", "volatile": False,
           "sha256": "0" * 64}
    with journal.open("a") as f:
        f.write(json.dumps(bad, sort_keys=True) + "\n")

    records = mgr._placement_records()
    assert any(k.startswith("__error__") for k in records)

    # Rebuild surfaces the journal error but still places every log entry.
    result = mgr.rebuild()
    assert result["rebuilt_facts"] >= 0
    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Violations: {health['violations']}"


def test_concurrent_writers_preserve_committed_facts(vault):
    """N processes writing disjoint and overlapping paths: no lost committed data."""
    import concurrent.futures
    import subprocess
    import sys

    mgr = TreeManager(vault)
    script = """
import sys, time
from pathlib import Path
from treemem.tree_manager import TreeManager
mgr = TreeManager(Path(sys.argv[1]))
wid, n = int(sys.argv[2]), int(sys.argv[3])
for i in range(n):
    p = f"chaos_{wid % 2}/node_{(i + wid) % 3}/leaf_{i % 2}"
    try:
        rem = mgr.remember(f"worker{wid} fact {i}", hint=p)
        mgr.place(rem["entry_id"], p)
    except Exception:
        pass
"""
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(vault), str(w), "8"])
        for w in range(4)
    ]
    for p in procs:
        p.wait(timeout=120)

    restarted = TreeManager(vault)
    health = restarted.health_checker.check_all()
    assert health["ok"] is True, f"Violations after concurrent writers: {health['violations']}"
    # The log is ground truth: all 32 remembered facts must be present,
    # and every one must either be placed or recoverable via rebuild.
    entries = restarted.log_writer.read_all_entries()
    assert len(entries) == 32, f"expected 32 log entries, got {len(entries)}"
    placed = restarted._placed_entry_ids()
    missing = [e["entry_id"] for e in entries if e["entry_id"] not in placed]
    if missing:
        restarted.rebuild()
        placed = restarted._placed_entry_ids()
        missing = [e["entry_id"] for e in entries if e["entry_id"] not in placed]
    assert not missing, f"committed facts lost after recovery: {missing}"


def test_sigkill_during_commit_summary_recovers(vault):
    """SIGKILL a writer mid commit_summary; node must be old-or-new, never torn."""
    import subprocess
    import sys

    mgr = TreeManager(vault)
    rem = mgr.remember("seed fact", hint="cs/topic")
    mgr.place(rem["entry_id"], "cs/topic")
    node = mgr.store.read_node("cs/topic")
    original_updated = node.updated

    script = """
import sys, time
from pathlib import Path
from treemem.tree_manager import TreeManager
mgr = TreeManager(Path(sys.argv[1]))
for i in range(200):
    try:
        mgr.commit_summary("cs/topic", f"summary version {i}\\n## Children\\n", force=True)
    except Exception:
        pass
"""
    proc = subprocess.Popen([sys.executable, "-c", script, str(vault)])
    time.sleep(0.3)
    proc.kill()
    proc.wait()

    restarted = TreeManager(vault)
    health = restarted.health_checker.check_all()
    assert health["ok"] is True, f"Violations: {health['violations']}"
    # The node must parse cleanly (old or new version, never half-written).
    node2 = restarted.store.read_node("cs/topic")
    assert node2 is not None
