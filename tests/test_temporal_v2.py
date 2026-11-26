"""Tests for temporal memory v2: retracts, valid-time intervals, contradiction warnings."""

import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_temporal_v2_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_retract_hides_fact_by_default(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Secret project codename Falcon", hint="projects/codename")
    mgr.place(rem["entry_id"], "projects/codename")

    res = mgr.retract(rem["entry_id"])
    assert res["ok"] and res["retracted"] == rem["entry_id"]

    out = mgr.expand("projects/codename")
    assert not any("Falcon" in f["fact"] for f in out["facts"])

    out_all = mgr.expand("projects/codename", include_history=True)
    assert any("Falcon" in f["fact"] for f in out_all["facts"])


def test_retract_missing_target_rejected(vault):
    mgr = TreeManager(vault)
    with pytest.raises(ValueError, match="not found"):
        mgr.retract("1999-01-01#999")


def test_remember_retracts_field_roundtrip(vault):
    mgr = TreeManager(vault)
    old = mgr.remember("temp fact", hint="t/x")
    tomb = mgr.remember("[manual tombstone]", hint="t/x", retracts=old["entry_id"])
    entry = mgr.log_writer.get_entry(tomb["entry_id"])
    assert entry["retracts"] == old["entry_id"]
    assert entry["supersedes"] == ""


def test_supersedes_and_retracts_mutually_exclusive(vault):
    mgr = TreeManager(vault)
    a = mgr.remember("fact a", hint="t/x")
    b = mgr.remember("fact b", hint="t/x")
    with pytest.raises(ValueError, match="mutually exclusive"):
        mgr.remember("fact c", supersedes=a["entry_id"], retracts=b["entry_id"])


def test_valid_time_interval_and_at_query(vault):
    mgr = TreeManager(vault)
    old = mgr.remember(
        "User prefers tea", hint="prefs/drink",
        valid_from="2025-01-01T00:00:00Z", valid_to="2025-06-01T00:00:00Z",
    )
    mgr.place(old["entry_id"], "prefs/drink")
    new = mgr.remember(
        "User prefers coffee", hint="prefs/drink",
        valid_from="2025-06-01T00:00:00Z",
        supersedes=old["entry_id"],
    )
    mgr.place(new["entry_id"], "prefs/drink")

    # Now: only coffee
    out = mgr.expand("prefs/drink")
    texts = [f["fact"] for f in out["facts"]]
    assert any("coffee" in t for t in texts) and not any("tea" in t for t in texts)

    # At March: only tea (coffee not yet valid, tea still valid then)
    out_mar = mgr.expand("prefs/drink", at="2025-03-15T00:00:00Z")
    texts_mar = [f["fact"] for f in out_mar["facts"]]
    assert any("tea" in t for t in texts_mar) and not any("coffee" in t for t in texts_mar)

    # At July: only coffee
    out_jul = mgr.expand("prefs/drink", at="2025-07-01T00:00:00Z")
    texts_jul = [f["fact"] for f in out_jul["facts"]]
    assert any("coffee" in t for t in texts_jul) and not any("tea" in t for t in texts_jul)


def test_at_before_any_valid_from_returns_empty(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember(
        "Future fact", hint="t/x",
        valid_from="2030-01-01T00:00:00Z",
    )
    mgr.place(rem["entry_id"], "t/x")
    out = mgr.expand("t/x", at="2020-01-01T00:00:00Z")
    assert out["facts"] == []


def test_invalid_at_timestamp_rejected(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("fact", hint="t/x")
    mgr.place(rem["entry_id"], "t/x")
    with pytest.raises(ValueError, match="Invalid 'at'"):
        mgr.expand("t/x", at="not-a-date")


def test_invalid_validity_timestamps_rejected(vault):
    mgr = TreeManager(vault)
    with pytest.raises(ValueError, match="valid_from"):
        mgr.remember("fact", valid_from="garbage")
    with pytest.raises(ValueError, match="valid_to must be after"):
        mgr.remember("fact", valid_from="2025-06-01T00:00:00Z", valid_to="2025-01-01T00:00:00Z")


def test_search_at_filters_by_valid_time(vault):
    mgr = TreeManager(vault)
    old = mgr.remember("Project Falcon launched", hint="projects/x",
                       valid_from="2024-01-01T00:00:00Z", valid_to="2025-01-01T00:00:00Z")
    mgr.place(old["entry_id"], "projects/x")
    new = mgr.remember("Project Osprey launched", hint="projects/x",
                       valid_from="2025-01-01T00:00:00Z", supersedes=old["entry_id"])
    mgr.place(new["entry_id"], "projects/x")

    res_now = mgr.search("launched")
    texts = [h.get("text", "") for h in res_now["hits"]]
    assert any("Osprey" in t for t in texts) and not any("Falcon" in t for t in texts)

    res_past = mgr.search("launched", at="2024-06-01T00:00:00Z")
    texts_past = [h.get("text", "") for h in res_past["hits"]]
    assert any("Falcon" in t for t in texts_past) and not any("Osprey" in t for t in texts_past)


def test_retract_survives_rebuild(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Doomed fact", hint="t/x")
    mgr.place(rem["entry_id"], "t/x")
    mgr.retract(rem["entry_id"])

    mgr2 = TreeManager(vault)
    out = mgr2.expand("t/x")
    assert not any("Doomed" in f["fact"] for f in out["facts"])
    health = mgr2.health_checker.check_all()
    assert health["ok"], health["violations"]


def test_contradiction_warning_fires_on_value_change(vault):
    mgr = TreeManager(vault)
    mgr.remember("User age is 30 years old", hint="identity/age")
    res = mgr.remember("User age is 31 years old", hint="identity/age")
    assert "contradiction_warning" in res
    assert "supersedes" in res["contradiction_warning"]


def test_contradiction_warning_silent_on_unrelated(vault):
    mgr = TreeManager(vault)
    mgr.remember("User likes pizza", hint="prefs/food")
    res = mgr.remember("Server runs on port 8080", hint="infra/server")
    assert "contradiction_warning" not in res


def test_tombstone_not_indexed_in_search(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("Indexed fact alpha", hint="t/x")
    mgr.retract(rem["entry_id"])
    res = mgr.search("retracted memory")
    assert all("retracted memory" not in h.get("text", "") for h in res["hits"])
