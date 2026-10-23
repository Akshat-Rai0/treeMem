"""Tests for sensitivity: private nodes and privacy guarantees."""

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from treemem.dashboard.server import create_app
from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_priv_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_private_node_recall_and_expand(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("My medical diagnosis is hypertension", hint="health/conditions")
    mgr.place(rem["entry_id"], "health/conditions", sensitivity="private")

    # Parent recall MUST NOT reveal private child summary or fact
    rec_parent = mgr.recall("health")
    child_teaser = rec_parent["children"][0]["teaser"]
    assert "contains private details" in child_teaser
    assert "hypertension" not in child_teaser

    # Expand without reveal=True MUST NOT return raw facts
    exp_hidden = mgr.expand("health/conditions", reveal=False)
    facts_text = " ".join(f["fact"] for f in exp_hidden["facts"])
    assert "hypertension" not in facts_text
    assert "withheld" in facts_text.lower()

    # Expand with reveal=True returns the raw facts
    exp_revealed = mgr.expand("health/conditions", reveal=True)
    facts_text_revealed = " ".join(f["fact"] for f in exp_revealed["facts"])
    assert "hypertension" in facts_text_revealed


def test_reject_summary_leaking_private_child(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Private tax ID is 9988776655", hint="finance/tax")
    mgr.place(rem["entry_id"], "finance/tax", sensitivity="private")

    # Attempt to commit parent summary containing private fact
    leaky_summary = """---
name: finance
dirty: false
---
Tax ID is 9988776655.

## Children
- [[tax]] - details
"""
    res = mgr.commit_summary("finance", leaky_summary)
    assert res["ok"] is False
    assert "leaks" in res["error"]


def test_deep_ancestor_cannot_leak_private_descendant(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Encrypted password token SecretToken9999", hint="vault/credentials/tokens")
    mgr.place(rem["entry_id"], "vault/credentials/tokens", sensitivity="private")

    # Root summary cannot leak it
    leaky_root = """---
name: root
dirty: false
---
Root summary with SecretToken9999 included.

## Children
- [[vault]] - details
"""
    res_root = mgr.commit_summary("", leaky_root)
    # Root check or health check flags private leakage
    if res_root["ok"]:
        health = mgr.health_checker.check_all()
        assert health["ok"] is False, "Health check should detect private leakage into root"


def test_api_never_exposes_private_fact_without_reveal(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Very confidential secret: OmegaPassword99", hint="confidential/passwords")
    mgr.place(rem["entry_id"], "confidential/passwords", sensitivity="private")

    token = "test-token"
    client = TestClient(create_app(mgr, token))

    # 1. /api/tree
    res_tree = client.get(f"/api/tree?t={token}")
    assert "OmegaPassword99" not in res_tree.text

    # 2. /api/node for parent
    res_parent = client.get(f"/api/node?path=confidential&t={token}")
    assert "OmegaPassword99" not in res_parent.text

    # 3. /api/node for child
    res_child = client.get(f"/api/node?path=confidential/passwords&t={token}")
    assert "OmegaPassword99" not in res_child.text
    assert "withheld" in res_child.json()["summary"].lower()
