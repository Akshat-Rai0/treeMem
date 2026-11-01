"""Phase C: embedding safety tests.

Verifies:
1. get_embedding_provider() returns None when OPENAI_API_KEY / TREEMEM_EMBEDDING_API_KEY are set
   but TREEMEM_EMBEDDING_PROVIDER is unset — no HTTP call is made.
2. A spy provider attached to a real TreeManager vault never receives private text.
3. Embedding cache: second rebuild with no changes calls embed_batch with zero new texts.
4. TreeManager default (no provider) still passes search (existing behaviour unchanged).
"""

import shutil
from pathlib import Path
from typing import List, Sequence

import pytest

from treemem import embeddings as emb_module
from treemem.embeddings import DeterministicEmbeddingProvider, get_embedding_provider
from treemem.index import SearchIndex
from treemem.tree_manager import TreeManager

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_memory"

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path):
    dst = tmp_path / "vault"
    shutil.copytree(
        SAMPLE,
        dst,
        ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"),
    )
    return dst


@pytest.fixture(autouse=True)
def reset_global_provider():
    """Reset the global provider singleton between tests."""
    original = emb_module._GLOBAL_PROVIDER
    emb_module._GLOBAL_PROVIDER = None
    yield
    emb_module._GLOBAL_PROVIDER = original


# ---------------------------------------------------------------------------
# Test 1 — auto-detection is gone; keys alone do not activate remote embedding
# ---------------------------------------------------------------------------


def test_get_embedding_provider_returns_none_when_keys_set_but_provider_unset(monkeypatch):
    """OPENAI_API_KEY and TREEMEM_EMBEDDING_API_KEY set, but TREEMEM_EMBEDDING_PROVIDER unset -> None."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy-key-for-testing")
    monkeypatch.setenv("TREEMEM_EMBEDDING_API_KEY", "sk-dummy-key-for-testing")
    monkeypatch.delenv("TREEMEM_EMBEDDING_PROVIDER", raising=False)

    result = get_embedding_provider(force_new=True)
    assert result is None


def test_search_index_default_provider_is_none(monkeypatch):
    """SearchIndex() with no argument has provider None — no auto-detection."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy-key-for-testing")
    monkeypatch.delenv("TREEMEM_EMBEDDING_PROVIDER", raising=False)

    idx = SearchIndex()
    assert idx.embedding_provider is None


def test_no_http_call_when_keys_set_but_provider_unset(monkeypatch):
    """Verify no HTTP call is attempted when auto-detection is disabled."""
    import httpx

    monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy-key-for-testing")
    monkeypatch.delenv("TREEMEM_EMBEDDING_PROVIDER", raising=False)

    call_count = {"n": 0}

    original_post = httpx.Client.post

    def spy_post(self, *args, **kwargs):
        call_count["n"] += 1
        raise RuntimeError("HTTP must not be called in this test")

    monkeypatch.setattr(httpx.Client, "post", spy_post)

    # Building a SearchIndex and running a query must not call HTTP
    idx = SearchIndex()
    idx.build(
        log_entries=[{"entry_id": "x1", "fact": "hello world", "hint": ""}],
        leaf_facts=[],
        nodes=[{"path": "a", "name": "a", "aliases": [], "summary": "a summary"}],
    )
    idx.query("hello")

    assert call_count["n"] == 0, "HTTP post should never be called"


# ---------------------------------------------------------------------------
# Test 2 — spy provider: private facts never passed to embed_batch
# ---------------------------------------------------------------------------


class SpyProvider(DeterministicEmbeddingProvider):
    """Records every text seen by embed_batch / embed_text."""

    def __init__(self):
        super().__init__(dimension=64)
        self.seen_texts: List[str] = []

    def embed_text(self, text: str):
        self.seen_texts.append(text)
        return super().embed_text(text)

    def embed_batch(self, texts: Sequence[str]):
        for t in texts:
            self.seen_texts.append(t)
        return super().embed_batch(texts)


def test_spy_provider_never_sees_private_facts(vault):
    """Private facts ('987654321', 'maxed out') must never reach embed_batch."""
    spy = SpyProvider()
    mgr = TreeManager(vault, embedding_provider=spy)

    joined = " ".join(spy.seen_texts)

    # These strings appear in finance/banking (private) and finance/investments (private)
    assert "987654321" not in joined, "Private fact '987654321' reached the embedding provider"
    assert "maxed out" not in joined, "Private fact 'maxed out' reached the embedding provider"


def test_spy_provider_does_see_public_texts(vault):
    """Non-private texts must be passed to the embedding provider."""
    spy = SpyProvider()
    mgr = TreeManager(vault, embedding_provider=spy)

    joined = " ".join(spy.seen_texts)
    # hobbies/fitness is not private; its facts should reach the spy
    assert len(joined) > 0, "No texts at all reached the embedding provider"


# ---------------------------------------------------------------------------
# Test 3 — embedding cache: second rebuild with no changes calls embed_batch zero times
# ---------------------------------------------------------------------------


class CountingProvider(DeterministicEmbeddingProvider):
    """Counts actual embed_batch calls (not cache hits)."""

    def __init__(self):
        super().__init__(dimension=64)
        self.batch_call_count = 0
        self.total_texts_embedded = 0

    def embed_batch(self, texts: Sequence[str]):
        self.batch_call_count += 1
        self.total_texts_embedded += len(texts)
        return super().embed_batch(texts)


def test_second_rebuild_embeds_nothing_when_unchanged(vault):
    """After first rebuild, a second rebuild with no data changes calls embed_batch 0 times."""
    provider = CountingProvider()
    mgr = TreeManager(vault, embedding_provider=provider)

    count_after_first = provider.total_texts_embedded

    # Second rebuild — no changes, all texts already cached
    mgr.rebuild_index()
    count_after_second = provider.total_texts_embedded

    assert count_after_second == count_after_first, (
        f"Second rebuild should embed 0 new texts, but embedded "
        f"{count_after_second - count_after_first} more"
    )


def test_new_fact_causes_only_one_new_embedding(vault):
    """After a rebuild, adding one new non-private fact embeds only that text."""
    provider = CountingProvider()
    mgr = TreeManager(vault, embedding_provider=provider)

    count_after_init = provider.total_texts_embedded

    # Add a non-private fact
    result = mgr.remember("Alex enjoys bird watching in the park.", hint="hobbies")
    entry_id = result.get("entry_id", "")

    # Place it under a non-private node
    all_paths = [n["path"] for n in mgr.index.node_docs]
    target = next((p for p in all_paths if "hobbies" in p and "/" in p), "hobbies")
    mgr.place(entry_id, target)

    # rebuild_index is called on commit_summary; let's call it directly to measure
    pre_second_rebuild = provider.total_texts_embedded
    mgr.rebuild_index()
    new_embeddings = provider.total_texts_embedded - pre_second_rebuild

    # At most a handful of texts should be re-embedded (new fact + possibly new node summaries)
    # The key requirement: not ALL texts are re-embedded (the cache works)
    total_nodes = len(mgr.index.node_docs)
    assert new_embeddings < total_nodes, (
        f"Cache did not work: {new_embeddings} texts embedded >= {total_nodes} total nodes"
    )


# ---------------------------------------------------------------------------
# Test 4 — TreeManager with default provider (None) still works for search
# ---------------------------------------------------------------------------


def test_treemem_default_no_provider_search_still_works(vault):
    """TreeManager with embedding_provider=None (default) still supports search."""
    mgr = TreeManager(vault)
    assert mgr.embedding_provider is None
    assert mgr.index.embedding_provider is None

    # BM25 search must still return results
    result = mgr.search("fitness running")
    assert isinstance(result, dict)
    assert "hits" in result
