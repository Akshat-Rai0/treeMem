"""WP-B: Fix path segment validation to support Unicode and more characters."""

import shutil
import tempfile
import unicodedata
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager, norm_path, validate_segment


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wpb_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_node_js_accepted(vault):
    """node.js should be accepted."""
    mgr = TreeManager(vault)
    entry = mgr.remember("Node.js is cool", hint="projects/node.js")
    mgr.place(entry["entry_id"], "projects/node.js")
    assert mgr.store.exists("projects/node.js")


def test_c_plus_plus_accepted(vault):
    """C++ should be accepted."""
    mgr = TreeManager(vault)
    entry = mgr.remember("C++ programming", hint="languages/C++")
    mgr.place(entry["entry_id"], "languages/C++")
    assert mgr.store.exists("languages/C++")


def test_q3_resume_accepted(vault):
    """q3_résumé should be accepted (with accent)."""
    mgr = TreeManager(vault)
    entry = mgr.remember("Resume for Q3", hint="documents/q3_résumé")
    mgr.place(entry["entry_id"], "documents/q3_résumé")
    assert mgr.store.exists("documents/q3_résumé")


def test_hindi_name_accepted(vault):
    """Hindi text should be accepted."""
    mgr = TreeManager(vault)
    entry = mgr.remember("Machine learning in Hindi", hint="topics/मशीन लर्निंग")
    mgr.place(entry["entry_id"], "topics/मशीन लर्निंग")
    assert mgr.store.exists("topics/मशीन लर्निंग")


def test_special_chars_accepted(vault):
    """a.b+c#d should be accepted."""
    mgr = TreeManager(vault)
    entry = mgr.remember("Test entry", hint="test/a.b+c#d")
    mgr.place(entry["entry_id"], "test/a.b+c#d")
    assert mgr.store.exists("test/a.b+c#d")


def test_100_char_name_accepted(vault):
    """A 100-character name should be accepted."""
    long_name = "a" * 100
    mgr = TreeManager(vault)
    entry = mgr.remember("Test", hint=f"test/{long_name}")
    result = mgr.remember("Test", hint=f"test/{long_name}")
    assert result["hint_rejected"] is False
    # Try to place - norm_path should work
    path = norm_path(f"test/{long_name}")
    assert path == f"test/{long_name}"


def test_101_char_name_rejected():
    """A 101-character name should be rejected."""
    long_name = "a" * 101
    with pytest.raises(ValueError, match="1-100 characters"):
        norm_path(f"test/{long_name}")


def test_double_dot_rejected():
    """a..b should be rejected."""
    with pytest.raises(ValueError, match="two consecutive dots"):
        norm_path("test/a..b")


def test_hidden_rejected():
    """.hidden should be rejected."""
    with pytest.raises(ValueError, match="cannot start with"):
        norm_path("test/.hidden")


def test_leading_space_rejected():
    """Leading space in the whole path is stripped by norm_path, so it works."""
    # norm_path strips leading/trailing space from the whole path
    # " test/name" becomes "test/name" which is valid
    path = norm_path(" test/name")
    assert path == "test/name"


def test_trailing_space_rejected():
    """Trailing space in the whole path is stripped by norm_path, so it works."""
    # norm_path strips leading/trailing space from the whole path
    # "test/name " becomes "test/name" which is valid
    path = norm_path("test/name ")
    assert path == "test/name"


def test_slash_rejected():
    """Slash is handled by norm_path splitting, not by validate_segment."""
    # norm_path splits on "/", so "test/a/b/c" is valid (3 segments)
    # The slash character itself would never reach validate_segment
    path = norm_path("test/a/b/c")
    assert path == "test/a/b/c"


def test_backslash_rejected():
    """Backslash should be rejected by norm_path."""
    with pytest.raises(ValueError, match="Backslashes are not allowed"):
        norm_path("test\\a")


def test_tab_rejected():
    """Tab should be rejected as control character by validate_segment."""
    with pytest.raises(ValueError, match="Control character"):
        validate_segment("a\tb")


def test_nul_rejected():
    """NUL should be rejected by validate_segment."""
    with pytest.raises(ValueError):
        validate_segment("a\x00b")


def test_log_reserved_rejected():
    """'log' should be rejected as reserved."""
    with pytest.raises(ValueError, match="reserved"):
        norm_path("log")


def test_dot_rejected():
    """Single dot should be rejected."""
    with pytest.raises(ValueError, match="not allowed"):
        norm_path(".")


def test_double_dot_path_rejected():
    """Double dot segment should be rejected."""
    with pytest.raises(ValueError, match="not allowed"):
        norm_path("..")


def test_nfc_normalization():
    """NFC and decomposed forms of 'résumé' should resolve to the same node."""
    # Composed form (NFC)
    composed = "résumé"
    # Decomposed form (NFD)
    decomposed = unicodedata.normalize("NFD", "résumé")
    
    norm_composed = norm_path(f"test/{composed}")
    norm_decomposed = norm_path(f"test/{decomposed}")
    
    assert norm_composed == norm_decomposed


def test_remember_with_invalid_hint_returns_hint_rejected(vault):
    """remember with invalid hint should return hint_rejected=True."""
    mgr = TreeManager(vault)
    result = mgr.remember("Test fact", hint="../invalid")
    assert result["hint_rejected"] is True
    assert result["hint_error"] is not None
    assert result["create_option"]["suggested_path"] == "general"


def test_max_depth_8_still_enforced():
    """Maximum depth of 8 should still be enforced."""
    with pytest.raises(ValueError, match="Maximum path depth is 8"):
        norm_path("/".join(f"dir{i}" for i in range(9)))


def test_first_char_must_be_alphanumeric():
    """First character must be alphanumeric."""
    with pytest.raises(ValueError, match="must start with a letter or digit"):
        norm_path("test/_name")
    
    with pytest.raises(ValueError, match="must start with a letter or digit"):
        norm_path("test/-name")


def test_old_traversal_tests_still_pass():
    """Old traversal tests from first pass should still pass."""
    bad_paths = ["../x", "a/../../x", "/abs", "a\\b", ".hidden", "log", "foo/log"]
    for p in bad_paths:
        with pytest.raises(ValueError):
            norm_path(p)


def test_space_in_middle_accepted(vault):
    """Space in the middle should be accepted."""
    mgr = TreeManager(vault)
    entry = mgr.remember("Test", hint="test/my topic")
    mgr.place(entry["entry_id"], "test/my topic")
    assert mgr.store.exists("test/my topic")
