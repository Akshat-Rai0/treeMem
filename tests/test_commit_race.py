"""Tests for Phase B: atomic commit_summary and lost-update prevention.

These tests prove that commit_summary re-reads the node fresh inside the lock,
so a concurrent write that completes between the caller's initial read and the
lock acquisition is detected as a conflict (when expected_updated is given) or
preserved (when expected_updated is absent).
"""

import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from treemem.tree_manager import TreeManager
from treemem.dashboard.server import create_app

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_memory"
VALID_TOKEN = "test-token-race"


@pytest.fixture
def mgr(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE, vault, ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"))
    return TreeManager(vault)


@pytest.fixture
def client(mgr):
    app = create_app(tree_manager=mgr, token=VALID_TOKEN)
    return TestClient(app, raise_server_exceptions=True)


def _install_racing_writer(mgr, path):
    """Monkey-patch lock_paths so that on the first call a concurrent writer
    slips in and commits a new fact + updated timestamp before the real lock
    is acquired."""
    original_lock = mgr.store.lock_paths
    state = {"fired": False}

    def racing_lock(paths, timeout=5.0):
        if not state["fired"]:
            state["fired"] = True
            other = mgr.store.read_node(path)
            other.facts.append({"fact": "CONCURRENT FACT", "entry_id": "2026-10-31#999"})
            other.updated = "2099-01-01T00:00:00+00:00"
            mgr.store.write_node_atomic(path, other)
        return original_lock(paths, timeout=timeout)

    mgr.store.lock_paths = racing_lock


# ---------------------------------------------------------------------------
# Test 1 — stale expected_updated must produce a conflict
# ---------------------------------------------------------------------------

def test_stale_expected_updated_is_a_conflict_and_keeps_the_concurrent_fact(mgr):
    """When a concurrent write lands between the caller's read and the lock,
    commit_summary with the now-stale expected_updated must return conflict=True
    and must NOT overwrite the concurrent fact."""
    path = "hobbies/fitness"
    loaded_version = mgr.store.read_node(path).updated
    _install_racing_writer(mgr, path)

    result = mgr.commit_summary(path, "Edited by the operator.", expected_updated=loaded_version)

    assert result["ok"] is False and result["conflict"] is True
    node = mgr.store.read_node(path)
    assert any("CONCURRENT FACT" in f["fact"] for f in node.facts)
    assert node.summary != "Edited by the operator."


# ---------------------------------------------------------------------------
# Test 2 — no expected_updated must succeed and preserve concurrent facts
# ---------------------------------------------------------------------------

def test_commit_without_expected_updated_never_drops_facts(mgr):
    """When expected_updated is not supplied, commit_summary is unconditional.
    It must succeed AND must preserve facts written by the concurrent writer —
    facts live on the fresh_node that was read inside the lock."""
    path = "hobbies/fitness"
    _install_racing_writer(mgr, path)

    result = mgr.commit_summary(path, "Agent summary.")

    assert result["ok"] is True
    node = mgr.store.read_node(path)
    assert any("CONCURRENT FACT" in f["fact"] for f in node.facts)
    assert node.summary == "Agent summary."


# ---------------------------------------------------------------------------
# Test 3 — matching expected_updated must still succeed
# ---------------------------------------------------------------------------

def test_matching_expected_updated_still_succeeds(mgr):
    """The happy path: expected_updated matches the current version and no
    concurrent writer interferes — commit should succeed normally."""
    path = "hobbies/fitness"
    version = mgr.store.read_node(path).updated

    result = mgr.commit_summary(path, "Edited by the operator.", expected_updated=version)

    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Test 4 — split also re-reads fresh inside the lock
# ---------------------------------------------------------------------------

def test_split_reads_fresh_inside_lock(mgr):
    """split() must re-read the parent node inside the lock; a concurrent update
    to the parent's metadata must not be silently lost."""
    path = "hobbies"
    # Write a sentinel value to the parent node BEFORE split.
    parent = mgr.store.read_node(path)
    original_lock = mgr.store.lock_paths
    state = {"fired": False}

    def racing_lock(paths, timeout=5.0):
        if not state["fired"]:
            state["fired"] = True
            # Concurrent writer updates the parent's sensitivity in-between.
            fresh = mgr.store.read_node(path)
            fresh.children_cap = 99
            mgr.store.write_node_atomic(path, fresh)
        return original_lock(paths, timeout=timeout)

    mgr.store.lock_paths = racing_lock

    # Split fitness into a group (fitness has no children so this just
    # reorganises the parent's children list).
    result = mgr.split(path, [{"name": "active", "children": ["fitness"]}])
    assert result["ok"] is True

    # The post-split parent must preserve the children_cap written by the
    # concurrent writer, not the cap from the pre-lock stale read.
    final_parent = mgr.store.read_node(path)
    assert final_parent.children_cap == 99


# ---------------------------------------------------------------------------
# Dashboard-level test: stale expected_updated → 409; force=True → 200
# ---------------------------------------------------------------------------

def test_dashboard_stale_expected_updated_returns_409(mgr, client):
    """Dashboard POST /api/node/summary with a stale timestamp → HTTP 409."""
    path = "hobbies/fitness"
    stale_ts = "2000-01-01T00:00:00+00:00"

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={
            "path": path,
            "text": "Dashboard stale attempt.",
            "expected_updated": stale_ts,
        },
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["conflict"] is True
    assert "current_updated" in detail
    assert "current_summary" in detail


def test_dashboard_force_true_overwrites_despite_stale_timestamp(mgr, client):
    """Dashboard POST /api/node/summary with force=True → HTTP 200 despite stale ts."""
    path = "hobbies/fitness"
    stale_ts = "2000-01-01T00:00:00+00:00"
    forced_text = "Forced overwrite via dashboard."

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={
            "path": path,
            "text": forced_text,
            "expected_updated": stale_ts,
            "force": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True

    # Verify the write persisted.
    node = mgr.store.read_node(path)
    assert forced_text in node.summary
