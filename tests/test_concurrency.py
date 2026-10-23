"""Tests for concurrent writers on overlapping paths."""

import concurrent.futures
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


def test_concurrent_writers_no_corruption(vault):
    mgr = TreeManager(vault)

    # Concurrently remember and place 20 facts
    def write_worker(idx):
        rem = mgr.remember(f"Fact number {idx} regarding identity", hint=f"identity/item_{idx % 4}")
        mgr.place(rem["entry_id"], f"identity/item_{idx % 4}")
        return rem["entry_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(write_worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20

    # Invariants must still all pass
    health = mgr.health_checker.check_all()
    assert health["ok"] is True, f"Violations after concurrent writes: {health['violations']}"
    assert health["total_facts"] == 20
