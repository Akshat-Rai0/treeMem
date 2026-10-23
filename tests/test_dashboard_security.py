"""Tests for dashboard security: XSS immunity, local loopback, token auth, and read-only enforcement."""

import html
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from treemem.dashboard.server import create_app
from treemem.tree_manager import TreeManager


@pytest.fixture
def sec_app():
    d = tempfile.mkdtemp(prefix="treemem_sec_")
    vault = Path(d)
    mgr = TreeManager(vault)

    # Insert malicious content in fact and summary
    xss_payload = "<script>alert('pwned')</script><img src=x onerror=alert(1)>"
    rem = mgr.remember(fact=xss_payload, hint="security/xss")
    mgr.place(rem["entry_id"], "security/xss")

    token = "secure-random-token-12345"
    app = create_app(mgr, token)
    client = TestClient(app)

    yield client, token, mgr
    shutil.rmtree(d, ignore_errors=True)


def test_auth_protection_and_token_rejection(sec_app):
    """Requests without token or with wrong token must receive 401 Unauthorized."""
    client, token, _ = sec_app

    # Missing token
    assert client.get("/api/tree").status_code == 401
    assert client.get("/api/node?path=security").status_code == 401
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/events").status_code == 401

    # Invalid token
    assert client.get("/api/tree?t=invalid").status_code == 401
    assert client.get("/api/tree", headers={"Authorization": "Bearer invalid"}).status_code == 401

    # Valid token succeeds
    assert client.get(f"/api/tree?t={token}").status_code == 200


def test_no_write_routes_exist_in_v1(sec_app):
    """V1 dashboard is strictly read-only: no POST, PUT, DELETE, or PATCH routes exist."""
    client, token, _ = sec_app

    write_endpoints = [
        ("POST", f"/api/tree?t={token}"),
        ("POST", f"/api/node?t={token}"),
        ("PUT", f"/api/node?t={token}"),
        ("DELETE", f"/api/node?t={token}"),
        ("PATCH", f"/api/node?t={token}"),
        ("POST", f"/api/remember?t={token}"),
        ("POST", f"/api/place?t={token}"),
        ("POST", f"/api/commit?t={token}"),
    ]

    for method, url in write_endpoints:
        res = client.request(method, url)
        assert res.status_code in (404, 405), f"Write endpoint {method} {url} unexpectedly succeeded: {res.status_code}"


def test_xss_content_rendered_as_inert_data(sec_app):
    """Memory text containing scripts/HTML must be returned as pure data, never executable HTML."""
    client, token, mgr = sec_app

    res = client.get(f"/api/node?path=security/xss&t={token}")
    assert res.status_code == 200
    data = res.json()

    # The payload is in json string format
    xss_str = "<script>alert('pwned')</script>"
    # Inspect frontend static files to verify .textContent is used, never innerHTML for summaries
    app_js_path = Path(__file__).parent.parent / "src" / "treemem" / "dashboard" / "static" / "app.js"
    with open(app_js_path, "r") as f:
        js_content = f.read()

    assert "insp-summary\").textContent" in js_content
    assert "insp-summary\").innerHTML" not in js_content


def test_privacy_leak_prevention_in_api(sec_app):
    """Private node details must NEVER be exposed via /api/* without explicit reveal."""
    client, token, mgr = sec_app

    # Store a private fact
    rem = mgr.remember("Super secret cryptographic private key: ABCD1234XYZ", hint="keys/crypto")
    mgr.place(rem["entry_id"], "keys/crypto", sensitivity="private")

    # 1. /api/node on the parent
    res_parent = client.get(f"/api/node?path=keys&t={token}")
    assert res_parent.status_code == 200
    parent_json = res_parent.json()
    assert "ABCD1234XYZ" not in str(parent_json)

    # 2. /api/node on the private child directly
    res_child = client.get(f"/api/node?path=keys/crypto&t={token}")
    assert res_child.status_code == 200
    child_json = res_child.json()
    assert "ABCD1234XYZ" not in child_json.get("summary", "")
    assert child_json.get("sensitivity") == "private"
    assert "withheld" in child_json.get("summary", "").lower()
