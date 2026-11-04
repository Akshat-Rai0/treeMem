"""Pass 3: names differing only by case collide on case-insensitive filesystems."""
import pytest
from treemem.tree_manager import TreeManager


def _place(m, path):
    r = m.remember("t", hint="x")
    return m.place(r["entry_id"], path)


def test_place_rejects_case_variant_of_existing_node(tmp_path):
    m = TreeManager(tmp_path / "v")
    _place(m, "Docs/a")
    for bad in ["docs/b", "DOCS/a/deep", "Docs/A"]:
        with pytest.raises(ValueError, match="differs only by letter case"):
            _place(m, bad)
    assert m.store.list_child_dirs("") == ["Docs"]


def test_exact_spelling_and_new_names_still_work(tmp_path):
    m = TreeManager(tmp_path / "v")
    _place(m, "Docs/a")
    _place(m, "Docs/b")
    _place(m, "other/x")
    assert m.store.list_child_dirs("Docs") == ["a", "b"]


def test_split_rejects_case_collision_with_existing_child(tmp_path):
    m = TreeManager(tmp_path / "v")
    for p in ["a/x", "a/y", "a/Group"]:
        _place(m, p)
    with pytest.raises(ValueError, match="only by case"):
        m.split("a", [{"name": "group", "children": ["x"]}])
    assert sorted(m.store.list_child_dirs("a")) == ["Group", "x", "y"]


def test_split_rejects_two_groups_differing_by_case(tmp_path):
    m = TreeManager(tmp_path / "v")
    for p in ["a/x", "a/y"]:
        _place(m, p)
    with pytest.raises(ValueError, match="Duplicate group name"):
        m.split("a", [{"name": "G", "children": ["x"]}, {"name": "g", "children": ["y"]}])


def test_node_names_ending_in_dot_are_listed_correctly(tmp_path):
    m = TreeManager(tmp_path / "v")
    _place(m, "v2./leaf.")
    paths = m.health_checker.get_all_node_paths()
    assert "v2." in paths and "v2./leaf." in paths
    assert m.health_checker.check_all()["violations"] == []
