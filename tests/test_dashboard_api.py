"""Tests for FastAPI dashboard endpoints and token authentication."""

import pytest
from fastapi.testclient import TestClient

from treemem.dashboard.server import create_app
from treemem.tree_manager import TreeManager


@pytest.fixture
def test_app():
    from pathlib import Path
    sample_vault = Path("examples/sample_memory")
    mgr = TreeManager(sample_vault)
    token = "secret-test-token"
    app = create_app(mgr, token)
    client = TestClient(app)
    return client, token


def test_auth_protection(test_app):
    client, token = test_app
    # Without token -> 401
    res = client.get("/api/tree")
    assert res.status_code == 401

    # With invalid token -> 401
    res = client.get("/api/tree?t=wrong-token")
    assert res.status_code == 401

    # With valid token query param -> 200
    res = client.get(f"/api/tree?t={token}")
    assert res.status_code == 200

    # With Bearer header -> 200
    res = client.get("/api/tree", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_tree_and_node_endpoints(test_app):
    client, token = test_app
    # GET /api/tree
    res = client.get(f"/api/tree?t={token}")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) >= 20

    # GET /api/node for normal node
    res_node = client.get(f"/api/node?path=identity&t={token}")
    assert res_node.status_code == 200
    node_data = res_node.json()
    assert node_data["name"] == "identity"
    assert len(node_data["children"]) >= 3

    # GET /api/node for private node (body must be withheld)
    res_priv = client.get(f"/api/node?path=finance/banking&t={token}")
    assert res_priv.status_code == 200
    priv_data = res_priv.json()
    assert priv_data["sensitivity"] == "private"
    assert "withheld" in priv_data["summary"].lower()


def test_health_and_metrics_endpoints(test_app):
    client, token = test_app
    # GET /api/health
    res_health = client.get(f"/api/health?t={token}")
    assert res_health.status_code == 200
    h_data = res_health.json()
    assert h_data["ok"] is True
    assert h_data["total_nodes"] >= 20

    # GET /api/metrics
    res_metrics = client.get(f"/api/metrics?t={token}")
    assert res_metrics.status_code == 200
    m_data = res_metrics.json()
    assert "baseline_flat_dump_tokens" in m_data
    assert m_data["baseline_flat_dump_tokens"] > 0


def test_index_html_served(test_app):
    client, token = test_app
    res = client.get("/")
    assert res.status_code == 200
    assert "TreeMem" in res.text
    assert "cytoscape.min.js" in res.text
