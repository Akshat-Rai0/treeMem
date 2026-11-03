"""WP4 regressions for split parity and journal-driven, idempotent rebuilds."""

import shutil

from treemem.tree_manager import TreeManager


def test_split_preserves_ungrouped_children_and_health(tmp_path):
    mgr = TreeManager(tmp_path / "vault")
    for name in ("one", "two", "keep"):
        item = mgr.remember(name, hint=name)
        mgr.place(item["entry_id"], name)
    mgr.split("/", [{"name": "group", "children": ["one", "two"]}])
    root = mgr.store.read_node("")
    assert {c["label"] for c in root.children} == {"group", "keep"}
    assert mgr.health_checker.check_all()["ok"]


def test_rebuild_uses_journal_and_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    mgr = TreeManager(vault)
    item = mgr.remember("a private fact", hint="wrong", sensitivity="private")
    mgr.place(item["entry_id"], "actual/path")
    assert (vault / ".placements.jsonl").exists()
    first = mgr.rebuild()
    assert first["ok"] and first["rebuilt_facts"] == 0
    shutil.rmtree(vault / "actual")
    second = mgr.rebuild()
    restored = mgr.store.read_node("actual/path")
    assert second["ok"]
    assert restored and restored.facts[0]["entry_id"] == item["entry_id"]
    assert restored.sensitivity == "private"
    before = (vault / "actual" / "path" / "summary.md").read_bytes()
    third = mgr.rebuild()
    assert third["rebuilt_facts"] == 0
    assert (vault / "actual" / "path" / "summary.md").read_bytes() == before
