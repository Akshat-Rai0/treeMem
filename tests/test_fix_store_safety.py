"""WP5 regression coverage for in-flight atomic writes and unambiguous locks."""

import os
import time

from treemem.store import NodeData, Store


def test_startup_keeps_fresh_temp_file_and_write_uses_unique_name(tmp_path):
    store = Store(tmp_path / "vault")
    fresh = store.root_dir / "summary.md.other.tmp"
    fresh.write_text("in flight", encoding="utf-8")
    Store(store.root_dir)
    assert fresh.exists()
    old = store.root_dir / "summary.md.old.tmp"
    old.write_text("old", encoding="utf-8")
    os.utime(old, (time.time() - 61, time.time() - 61))
    Store(store.root_dir)
    assert not old.exists()
    store.write_node_atomic("a", NodeData(name="a", summary="hello"))
    assert not list((store.root_dir / "a").glob("summary.md.*.tmp"))


def test_path_locks_do_not_collide_for_slash_and_double_underscore(tmp_path):
    store = Store(tmp_path / "vault")
    with store.lock_paths(["a/b", "a__b"]):
        names = {p.name for p in store.lock_dir.glob("*.lock")}
    assert len(names) == 2
