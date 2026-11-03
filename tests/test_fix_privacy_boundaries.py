"""WP3 regressions: effective privacy is inherited and never serialized by default."""

import os

from treemem.auto_compress import AutoCompressor
from treemem.tree_manager import TreeManager


def _private_child(mgr: TreeManager):
    entry = mgr.remember("routing secret 987654321", hint="private/child", sensitivity="private")
    mgr.place(entry["entry_id"], "private/child")
    # A deliberately normal descendant still inherits the parent's privacy.
    entry2 = mgr.remember("descendant secret", hint="private/child/grandchild")
    mgr.place(entry2["entry_id"], "private/child/grandchild")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()


def test_effective_private_withholds_all_read_surfaces(tmp_path, monkeypatch):
    monkeypatch.delenv("TREEMEM_ALLOW_REVEAL", raising=False)
    mgr = TreeManager(tmp_path / "vault")
    _private_child(mgr)

    for output in (
        mgr.recall("private/child"),
        mgr.expand("private/child"),
        mgr.compress("private/child"),
        mgr.recall("/", query="routing secret", follow=True),
        mgr.search("routing secret"),
    ):
        assert "987654321" not in str(output)
    assert mgr.is_private("private/child/grandchild")


def test_operator_grant_allows_explicit_private_recall_expand_and_compress(tmp_path, monkeypatch):
    monkeypatch.setenv("TREEMEM_ALLOW_REVEAL", "1")
    mgr = TreeManager(tmp_path / "vault")
    entry = mgr.remember("routing secret 987654321", hint="private/child", sensitivity="private")
    mgr.place(entry["entry_id"], "private/child")
    assert "987654321" in str(mgr.recall("private/child", reveal=True))
    assert "987654321" in str(mgr.expand("private/child", reveal=True))
    assert "987654321" in str(mgr.compress("private/child", reveal=True))


def test_auto_compressor_never_receives_private_prompt_without_grant(tmp_path, monkeypatch):
    monkeypatch.delenv("TREEMEM_ALLOW_REVEAL", raising=False)
    mgr = TreeManager(tmp_path / "vault")
    _private_child(mgr)
    received = []
    compressor = AutoCompressor(mgr, llm_caller=lambda system, prompt: received.append(prompt) or "summary")
    result = compressor.compress_node("private/child")
    assert result["skipped_private"] is True
    assert not received
