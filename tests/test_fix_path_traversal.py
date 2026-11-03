"""WP2: path traversal via place/split must not write outside the vault."""

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from treemem.dashboard.server import create_app
from treemem.mcp_layer import place as mcp_place, remember as mcp_remember, set_manager
from treemem.store import Store
from treemem.tree_manager import TreeManager, norm_path


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wp2_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def _outside_unchanged(vault: Path, parent_before: set):
    parent = vault.parent
    assert set(parent.iterdir()) == parent_before
    assert not (parent / "x").exists()
    assert not (parent / "escaped").exists()
    assert not (parent / "abs").exists()


def test_place_rejects_traversal_and_reserved_names(vault):
    mgr = TreeManager(vault)
    rem = mgr.remember("secret")
    parent_before = set(vault.parent.iterdir())
    bad_paths = ["../x", "a/../../x", "/abs", "a\\b", ".hidden", "log", "foo/log"]
    for p in bad_paths:
        with pytest.raises(ValueError):
            mgr.place(rem["entry_id"], p)
        _outside_unchanged(vault, parent_before)
        assert not (vault / "x").exists()


def test_split_rejects_dotdot_group_without_mutating(vault):
    mgr = TreeManager(vault)
    r1 = mgr.remember("a", hint="child_a")
    mgr.place(r1["entry_id"], "child_a")
    r2 = mgr.remember("b", hint="child_b")
    mgr.place(r2["entry_id"], "child_b")
    parent_before = set(vault.parent.iterdir())
    children_before = set(vault.iterdir())

    with pytest.raises(ValueError):
        mgr.split("", [{"name": "../g", "children": ["child_a"]}])

    _outside_unchanged(vault, parent_before)
    assert set(vault.iterdir()) == children_before
    assert mgr.store.exists("child_a")
    assert not (vault.parent / "g").exists()


def test_split_refuses_existing_destination_and_name_collision(vault):
    mgr = TreeManager(vault)
    for name in ("keep", "move_me", "taken"):
        rem = mgr.remember(name, hint=name)
        mgr.place(rem["entry_id"], name)

    with pytest.raises(ValueError, match="not being moved"):
        mgr.split("", [{"name": "keep", "children": ["move_me"]}])
    assert mgr.store.exists("move_me")
    assert mgr.store.exists("keep")

    stray = vault / "straygroup"
    stray.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        mgr.split("", [{"name": "straygroup", "children": ["move_me"]}])
    assert mgr.store.exists("move_me")


def test_remember_invalid_hint_falls_back_to_general(vault):
    mgr = TreeManager(vault)
    res = mgr.remember("fact with bad hint", hint="../escaped")
    assert res["create_option"]["suggested_path"] == "general"
    entry = mgr.log_writer.get_entry(res["entry_id"])
    assert entry["fact"] == "fact with bad hint"


def test_norm_path_rejects_depth_and_bad_segments():
    with pytest.raises(ValueError):
        norm_path("/".join(f"s{i}" for i in range(9)))
    with pytest.raises(ValueError):
        norm_path("a//b")
    with pytest.raises(ValueError):
        norm_path("has\x00nul")
    assert norm_path("/") == ""
    assert norm_path("Identity_1/sub-topic") == "Identity_1/sub-topic"


def test_node_dir_refuses_escaped_resolved_path(vault):
    store = Store(vault)
    with pytest.raises(ValueError):
        store.node_dir("../escaped")


def test_dashboard_maps_valueerror_to_400(vault):
    mgr = TreeManager(vault)
    token = "t"
    client = TestClient(create_app(mgr, token))
    res = client.get("/api/node", params={"path": "../x", "t": token})
    assert res.status_code == 400


def test_mcp_returns_error_string_for_bad_place(vault):
    mgr = TreeManager(vault)
    set_manager(mgr)
    rem_raw = mcp_remember(fact="x", hint="ok")
    import json

    rem = json.loads(rem_raw)
    out = mcp_place(entry_id=rem["entry_id"], path="../escaped")
    assert "error" in out.lower() or "invalid" in out.lower() or ".." in out
    assert "../escaped" in out or "not allowed" in out.lower() or "ValueError" not in out
    set_manager(None)
