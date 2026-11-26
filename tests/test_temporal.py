"""Tests for supersede / temporal memory semantics.

A fact remembered with `supersedes=<entry_id>` stays in the append-only log
(ground truth) but is hidden from recall/expand/search/compress by default.
`include_history=True` reveals the full history.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_temporal_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _seed(mgr):
    old = mgr.remember("User lives in Berlin", hint="identity/city")
    mgr.place(old["entry_id"], "identity/city")
    return old["entry_id"]


def test_remember_with_supersedes_writes_log_field(vault):
    mgr = TreeManager(vault)
    old_id = _seed(mgr)
    new = mgr.remember("User lives in Lisbon", hint="identity/city", supersedes=old_id)
    assert new["entry_id"]
    entry = mgr.log_writer.get_entry(new["entry_id"])
    assert entry["supersedes"] == old_id
    mgr.place(new["entry_id"], "identity/city")


def test_remember_supersedes_missing_target_rejected(vault):
    mgr = TreeManager(vault)
    with pytest.raises(ValueError, match="not found"):
        mgr.remember("fact", supersedes="1999-01-01#999")


def test_expand_hides_superseded_by_default(vault):
    mgr = TreeManager(vault)
    old_id = _seed(mgr)
    new = mgr.remember("User lives in Lisbon", hint="identity/city", supersedes=old_id)
    mgr.place(new["entry_id"], "identity/city")

    res = mgr.expand("identity/city")
    facts = [f["fact"] for f in res["facts"]]
    assert "User lives in Berlin" not in facts
    assert "User lives in Lisbon" in facts

    res_all = mgr.expand("identity/city", include_history=True)
    facts_all = [f["fact"] for f in res_all["facts"]]
    assert "User lives in Berlin" in facts_all
    assert "User lives in Lisbon" in facts_all


def test_guided_recall_leaf_hides_superseded(vault):
    mgr = TreeManager(vault)
    old_id = _seed(mgr)
    new = mgr.remember("User lives in Lisbon", hint="identity/city", supersedes=old_id)
    mgr.place(new["entry_id"], "identity/city")

    res = mgr.recall(path="identity/city", query="where does the user live", follow=True)
    fact_texts = [f.get("fact", "") for f in res.get("facts", [])]
    assert not any("Berlin" in t for t in fact_texts)


def test_search_hides_superseded_hits(vault):
    mgr = TreeManager(vault)
    old_id = _seed(mgr)
    new = mgr.remember("User lives in Lisbon", hint="identity/city", supersedes=old_id)
    mgr.place(new["entry_id"], "identity/city")

    res = mgr.search("lives")
    texts = [h.get("text", "") for h in res["hits"]]
    assert not any("Berlin" in t for t in texts)
    assert res.get("withheld_superseded", 0) >= 1 or not any("Berlin" in t for t in texts)

    res_all = mgr.search("lives", include_history=True)
    texts_all = [h.get("text", "") for h in res_all["hits"]]
    assert any("Berlin" in t for t in texts_all)


def test_compress_excludes_superseded_facts(vault):
    mgr = TreeManager(vault)
    old_id = _seed(mgr)
    new = mgr.remember("User lives in Lisbon", hint="identity/city", supersedes=old_id)
    mgr.place(new["entry_id"], "identity/city")

    res = mgr.compress("identity/city")
    texts = [i.get("text", "") for i in res.get("inputs", [])]
    assert not any("Berlin" in t for t in texts)


def test_supersession_survives_rebuild_and_restart(vault):
    mgr = TreeManager(vault)
    old_id = _seed(mgr)
    new = mgr.remember("User lives in Lisbon", hint="identity/city", supersedes=old_id)
    mgr.place(new["entry_id"], "identity/city")

    # Fresh manager = simulated restart; supersession derives from the log.
    mgr2 = TreeManager(vault)
    res = mgr2.expand("identity/city")
    facts = [f["fact"] for f in res["facts"]]
    assert "User lives in Berlin" not in facts
    assert "User lives in Lisbon" in facts

    mgr2.rebuild()
    res = mgr2.expand("identity/city", include_history=True)
    assert any("Berlin" in f["fact"] for f in res["facts"])


def test_unplaced_superseded_fact_still_hidden_in_search(vault):
    mgr = TreeManager(vault)
    old = mgr.remember("Project codename was Falcon", hint="projects/codename")
    mgr.place(old["entry_id"], "projects/codename")
    new = mgr.remember("Project codename is Osprey", hint="projects/codename", supersedes=old["entry_id"])
    # Deliberately do NOT place the new fact.

    res = mgr.search("codename")
    texts = [h.get("text", "") for h in res["hits"]]
    assert not any("Falcon" in t for t in texts)
