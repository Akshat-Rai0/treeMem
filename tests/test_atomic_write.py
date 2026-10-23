"""Tests for atomic file writing and lock handling."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.store import NodeData, Store


@pytest.fixture
def vault():
    d = tempfile.mkdtemp()
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_atomic_replace_and_no_tmp_left(vault):
    store = Store(vault)
    node = NodeData(name="test", summary="Hello world", dirty=False)
    store.write_node_atomic("test", node)

    # Assert target file exists
    assert store.summary_file("test").exists()

    # Assert no .tmp file left behind
    assert not (vault / "test" / "summary.md.tmp").exists()

    # Read back
    read_back = store.read_node("test")
    assert read_back is not None
    assert read_back.name == "test"
    assert read_back.summary == "Hello world"


def test_root_to_leaf_locking(vault):
    store = Store(vault)
    # Lock root and child path in top-down order
    with store.lock_paths(["", "subtopic"]):
        # Verify inside lock block
        pass
