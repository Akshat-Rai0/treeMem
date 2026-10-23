"""Tests for Option B AutoCompressor: bottom-up ordering, LLM validation retries, and background worker."""

import shutil
import tempfile
import time
from pathlib import Path

import pytest
from treemem.auto_compress import AutoCompressor
from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_autocompress_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_auto_compress_single_node_mock_llm(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Shipped new indexing pipeline v2", hint="work/projects")
    mgr.place(rem["entry_id"], "work/projects")

    node_before = mgr.store.read_node("work/projects")
    assert node_before.dirty is True

    # Mock LLM that returns valid summary
    def mock_llm(system_prompt, user_prompt):
        return """---
name: projects
dirty: false
---
Work projects overview including indexing pipeline v2.
"""

    compressor = AutoCompressor(mgr, llm_caller=mock_llm)
    res = compressor.compress_node("work/projects")

    assert res["ok"] is True
    node_after = mgr.store.read_node("work/projects")
    assert node_after.dirty is False
    assert "indexing pipeline v2" in node_after.summary


def test_bottom_up_compression_order(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Deep nested metric fact", hint="alpha/beta/gamma/leaf")
    mgr.place(rem["entry_id"], "alpha/beta/gamma/leaf")

    dirty_nodes = mgr.get_dirty_nodes()
    assert len(dirty_nodes) >= 4

    compressed_order = []

    def mock_llm(system_prompt, user_prompt):
        # Extract path or topic from user prompt
        for line in user_prompt.splitlines():
            if line.startswith("Topic:"):
                # line looks like "Topic: leaf (path: 'alpha/beta/gamma/leaf')"
                parts = line.split("path: '")
                if len(parts) > 1:
                    path = parts[1].split("'")[0]
                    compressed_order.append(path)
                    child_dirs = mgr.store.list_child_dirs(path)
                    children_md = ""
                    if child_dirs:
                        children_md = "\n\n## Children\n" + "\n".join(f"- [[{c}]] - details" for c in child_dirs)
                    return f"---\nname: topic\ndirty: false\n---\nSummary for {path}.{children_md}"
        return "---\nname: node\ndirty: false\n---\nDefault summary."

    compressor = AutoCompressor(mgr, llm_caller=mock_llm)
    res = compressor.compress_all_dirty()

    assert res["ok"] is True
    assert res["cleaned_count"] >= 4

    # Verify strictly bottom-up: deepest (3 slashes) before root (0 slashes)
    assert compressed_order[0] == "alpha/beta/gamma/leaf"
    assert compressed_order[-1] == "/" or compressed_order[-1] == ""

    # All nodes are now clean
    assert len(mgr.get_dirty_nodes()) == 0


def test_validation_retry_loop(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Fact A", hint="category/item")
    mgr.place(rem["entry_id"], "category/item")

    attempt_count = 0

    def mock_flaky_llm(system_prompt, user_prompt):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            # Attempt 1: Intentionally return summary that exceeds 150 token cap
            long_text = "word " * 160
            return f"---\nname: item\ndirty: false\n---\n{long_text}"
        else:
            # Attempt 2: Fixed concise summary
            assert "[RETRY FEEDBACK]" in user_prompt
            assert "exceeds length cap" in user_prompt
            return "---\nname: item\ndirty: false\n---\nConcise summary under cap."

    compressor = AutoCompressor(mgr, llm_caller=mock_flaky_llm)
    res = compressor.compress_node("category/item", max_retries=2)

    assert res["ok"] is True
    assert res["attempts"] == 2
    node = mgr.store.read_node("category/item")
    assert node.dirty is False
    assert "Concise summary under cap." in node.summary


def test_background_worker_auto_cleans(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Fact for background test", hint="reports/daily")
    mgr.place(rem["entry_id"], "reports/daily")

    assert len(mgr.get_dirty_nodes()) > 0

    def mock_llm(system_prompt, user_prompt):
        # Generate valid summary with children if needed
        for line in user_prompt.splitlines():
            if "path: '" in line:
                p = line.split("path: '")[1].split("'")[0]
                child_dirs = mgr.store.list_child_dirs(p)
                ch_block = ""
                if child_dirs:
                    ch_block = "\n\n## Children\n" + "\n".join(f"- [[{c}]] - details" for c in child_dirs)
                return f"---\nname: node\ndirty: false\n---\nCleaned summary for {p}.{ch_block}"
        return "---\nname: node\ndirty: false\n---\nCleaned summary."

    compressor = AutoCompressor(mgr, llm_caller=mock_llm)
    compressor.start_background_worker(interval_seconds=0.1)

    try:
        # Give background thread a short moment to clean dirty nodes
        time.sleep(0.4)
        assert len(mgr.get_dirty_nodes()) == 0
    finally:
        compressor.stop_background_worker()
