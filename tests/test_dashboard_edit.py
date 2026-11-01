"""Tests for Task C: Dashboard write endpoints (compress + edit summary)."""

import pytest
from fastapi.testclient import TestClient

from treemem.tree_manager import TreeManager
from treemem.dashboard.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_TOKEN = "test-token-abc123"


@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def mgr(tmp_vault):
    m = TreeManager(tmp_vault)
    # Create a sample node with a fact so there's something to edit
    m.remember("Alice uses pytest for unit testing", hint="")
    return m


@pytest.fixture
def client(mgr):
    app = create_app(tree_manager=mgr, token=VALID_TOKEN)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Token auth on write endpoints
# ---------------------------------------------------------------------------

def test_compress_requires_token(client):
    """POST /api/node/compress without token → 401."""
    res = client.post("/api/node/compress", json={"path": "/"})
    assert res.status_code == 401


def test_edit_summary_requires_token(client):
    """POST /api/node/summary without token → 401."""
    res = client.post("/api/node/summary", json={"path": "/", "text": "hello"})
    assert res.status_code == 401


def test_compress_wrong_token(client):
    """POST /api/node/compress with wrong token → 401."""
    res = client.post(
        f"/api/node/compress?t=wrongtoken",
        json={"path": "/"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Edit summary — valid and invalid paths / content
# ---------------------------------------------------------------------------

def test_edit_summary_nonexistent_node(client):
    """Editing a node that doesn't exist → 404."""
    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={"path": "nonexistent/path", "text": "New summary text"},
    )
    assert res.status_code == 404


def test_edit_summary_empty_text(client, mgr):
    """Editing with empty text → 422."""
    all_paths = mgr.health_checker.get_all_node_paths()
    assert all_paths, "Expected at least one node after remember()"
    path = all_paths[0]

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={"path": path, "text": "   "},
    )
    assert res.status_code == 422


def test_edit_summary_too_long(client, mgr):
    """Editing with > 4000 char text → 422."""
    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={"path": path, "text": "x" * 4001},
    )
    assert res.status_code == 422


def test_edit_summary_success(client, mgr):
    """Valid edit → 200 ok:True and summary is persisted."""
    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]
    new_text = "Updated summary written via dashboard edit."

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={"path": path, "text": new_text},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["path"] == path
    assert isinstance(body["tokens"], int) and body["tokens"] > 0

    # Verify persistence
    node = mgr.store.read_node(path)
    assert node is not None
    assert new_text in node.summary


def test_edit_summary_matching_expected_updated_succeeds(client, mgr):
    """When expected_updated matches node.updated, edit succeeds."""
    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]
    initial_node = mgr.store.read_node(path)
    assert initial_node.updated is not None

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={
            "path": path,
            "text": "Summary edit with valid expected_updated timestamp.",
            "expected_updated": initial_node.updated,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["updated"] is not None
    assert data["updated"] != initial_node.updated


def test_edit_summary_conflict_mismatch_fails_409(client, mgr):
    """When expected_updated is outdated, returns 409 Conflict with conflict details."""
    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]
    outdated_timestamp = "2020-01-01T00:00:00+00:00"

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={
            "path": path,
            "text": "Attempting edit on top of stale version.",
            "expected_updated": outdated_timestamp,
        },
    )
    assert res.status_code == 409
    data = res.json()["detail"]
    assert data["conflict"] is True
    assert "current_updated" in data
    assert "current_summary" in data


def test_edit_summary_force_overrides_conflict(client, mgr):
    """When force=True is provided, 409 Conflict is bypassed and edit succeeds."""
    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]
    outdated_timestamp = "2020-01-01T00:00:00+00:00"
    forced_text = "Forced overwrite summary bypassing stale conflict."

    res = client.post(
        f"/api/node/summary?t={VALID_TOKEN}",
        json={
            "path": path,
            "text": forced_text,
            "expected_updated": outdated_timestamp,
            "force": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True

    # Verify forced write persisted
    node = mgr.store.read_node(path)
    assert forced_text in node.summary


def test_tree_manager_commit_summary_conflict(mgr):
    """TreeManager.commit_summary returns conflict dict on mismatched timestamp."""
    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]
    node = mgr.store.read_node(path)

    res = mgr.commit_summary(
        path,
        "New text for direct commit_summary conflict test.",
        expected_updated="2000-01-01T00:00:00+00:00",
    )
    assert res["ok"] is False
    assert res.get("conflict") is True
    assert "current_updated" in res
    assert res["current_updated"] == node.updated


# ---------------------------------------------------------------------------
# Compress endpoint — missing API key
# ---------------------------------------------------------------------------

def test_compress_no_groq_key(client, mgr, monkeypatch):
    """compress endpoint without GROQ key → 503."""
    monkeypatch.delenv("GROQ_API_KEY_1", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    all_paths = mgr.health_checker.get_all_node_paths()
    path = all_paths[0]

    res = client.post(
        f"/api/node/compress?t={VALID_TOKEN}",
        json={"path": path},
    )
    assert res.status_code == 503
    assert "GROQ" in res.json()["detail"]


def test_compress_nonexistent_node(client, monkeypatch):
    """compress on non-existent path → 404."""
    monkeypatch.setenv("GROQ_API_KEY_1", "fake-key")
    res = client.post(
        f"/api/node/compress?t={VALID_TOKEN}",
        json={"path": "does/not/exist"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Existing read endpoints still work (regression)
# ---------------------------------------------------------------------------

def test_get_tree_still_works(client):
    res = client.get(f"/api/tree?t={VALID_TOKEN}")
    assert res.status_code == 200
    assert "nodes" in res.json()


def test_get_health_still_works(client):
    res = client.get(f"/api/health?t={VALID_TOKEN}")
    assert res.status_code == 200
    assert "ok" in res.json()
