"""The agent must not be able to grant itself access to private data."""

import json
import shutil
from pathlib import Path

import pytest

import treemem.mcp_layer as mcp_layer
from treemem.reveal_policy import ENV_VAR, resolve_reveal
from treemem.tree_manager import TreeManager

SAMPLE_VAULT = Path(__file__).resolve().parent.parent / "examples" / "sample_memory"
SECRET = "987654321"


@pytest.fixture
def server(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    shutil.copytree(
        SAMPLE_VAULT,
        vault,
        ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"),
    )
    monkeypatch.setattr(mcp_layer, "_MANAGER", TreeManager(vault))
    monkeypatch.delenv(ENV_VAR, raising=False)
    return mcp_layer


def test_resolve_reveal_not_requested():
    assert resolve_reveal(False) == (False, False)


def test_resolve_reveal_denied_without_grant(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert resolve_reveal(True) == (False, True)


def test_resolve_reveal_granted(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    assert resolve_reveal(True) == (True, False)


def test_resolve_reveal_other_values_do_not_grant(monkeypatch):
    for value in ("0", "true", "yes", ""):
        monkeypatch.setenv(ENV_VAR, value)
        assert resolve_reveal(True) == (False, True)


def test_expand_reveal_true_is_denied_by_default(server):
    out = json.loads(server.expand("finance/banking", reveal=True))
    assert SECRET not in json.dumps(out)
    assert out.get("reveal_denied") is True


def test_search_reveal_true_is_denied_by_default(server):
    out = json.loads(server.search("bank routing number", limit=5, reveal=True))
    assert SECRET not in json.dumps(out)
    assert out.get("reveal_denied") is True


def test_expand_reveal_works_when_operator_grants(server, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    out = json.loads(server.expand("finance/banking", reveal=True))
    assert SECRET in json.dumps(out)
    assert "reveal_denied" not in out


def test_search_reveal_works_when_operator_grants(server, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    out = json.loads(server.search("bank routing number", limit=5, reveal=True))
    assert SECRET in json.dumps(out)


def test_plain_expand_unaffected(server):
    out = json.loads(server.expand("identity"))
    assert "reveal_denied" not in out
