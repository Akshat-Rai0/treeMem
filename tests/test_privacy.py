"""Tests for sensitivity: private nodes and privacy guarantees."""

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
