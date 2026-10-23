"""Tests for concurrent writers on overlapping paths with deadlock and corruption prevention."""

import concurrent.futures
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_concurrent_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_concurrent_writers_no_corruption(vault):
    mgr = TreeManager(vault)

    # Concurrently remember and place 30 facts across overlapping topic hierarchies
    def write_worker(idx):
        # Mix of sibling and parent-child overlapping paths
        target_path = f"category_{idx % 3}/topic_{idx % 2}/leaf_{idx % 4}"
        rem = mgr.remember(f"Concurrent fact #{idx} for {target_path}", hint=target_path)
        res = mgr.place(rem["entry_id"], target_path)
        return res["entry_id"]

    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_worker, i) for i in range(30)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    duration = time.time() - start
    assert len(results) == 30
    assert duration < 10.0, "Concurrent execution took too long (possible deadlock)"

    # Invariants must still all pass
    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Violations after concurrent writes: {health['violations']}"
    assert health["total_facts"] == 30


def test_concurrent_overlapping_parent_and_child_writes(vault):
    mgr = TreeManager(vault)

    # Concurrently write to ancestor and deeply nested child
    paths = [
        "shared/sub/deep/leaf1",
        "shared/sub/deep/leaf2",
        "shared/sub/other",
        "shared/alt",
    ]

    def worker(idx):
        p = paths[idx % len(paths)]
        rem = mgr.remember(f"Fact payload {idx}", hint=p)
        return mgr.place(rem["entry_id"], p)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker, i) for i in range(24)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 24
    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Violations: {health['violations']}"
