"""Regression test for dashboard compress endpoint AutoCompressor wiring."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from treemem.dashboard.server import create_app
from treemem.tree_manager import TreeManager


class _FakeSummarizer:
    def __init__(self, keys=None):
        self.keys = keys or []

    def generate(self, system_prompt, user_prompt):
        return "summary"


class _FakeCompressor:
    captured = {}

    def __init__(self, tree_manager, llm_caller=None, model="qwen/qwen3.8-27b"):
        _FakeCompressor.captured = {
            "tree_manager": tree_manager,
            "llm_caller": llm_caller,
            "model": model,
        }

    def compress_node(self, path):
        return {"ok": True, "path": path}


def test_compress_endpoint_uses_llm_caller_not_api_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("treemem.auto_compress.GroqSummarizerClient", _FakeSummarizer)
    monkeypatch.setattr("treemem.auto_compress.AutoCompressor", _FakeCompressor)

    mgr = TreeManager(Path("examples/sample_memory"))
    client = TestClient(create_app(mgr, "token"))
    res = client.post("/api/node/compress", json={"path": "identity"}, headers={"Authorization": "Bearer token"})
    assert res.status_code == 200, res.text
    assert callable(_FakeCompressor.captured["llm_caller"])
    assert "api_key" not in _FakeCompressor.captured
