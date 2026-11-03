from treemem import tokenizer
from treemem.mcp_layer import set_manager, status
from treemem.tree_manager import TreeManager


def test_fallback_is_explicit_and_status_reports_it(tmp_path, monkeypatch):
    monkeypatch.setattr(tokenizer, "_ENCODER", None)
    assert tokenizer.tokenizer_is_fallback()
    assert tokenizer.count_tokens("one two three") >= 3
    mgr = TreeManager(tmp_path / "vault")
    set_manager(mgr)
    assert '"tokenizer": "fallback"' in status()
    set_manager(None)
