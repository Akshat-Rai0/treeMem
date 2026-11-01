"""Tests for Dense Vector Embeddings and hybrid candidate placement / search."""

import numpy as np
import pytest
from unittest.mock import MagicMock

from treemem.embeddings import (
    DeterministicEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    cosine_similarity,
    cosine_similarity_matrix,
    get_embedding_provider,
    normalize_matrix,
    normalize_vector,
)
from treemem.index import SearchIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_NODES = [
    {
        "path": "user/hobbies/fitness",
        "name": "fitness",
        "aliases": ["exercise", "workout", "gym"],
        "summary": "User trains at Apex Fitness gym three times a week. Enjoys cycling and trail runs.",
    },
    {
        "path": "user/education/coursework",
        "name": "coursework",
        "aliases": ["classes", "subjects"],
        "summary": "Advanced Algorithms, Compilers, Operating Systems, and Machine Learning courses.",
    },
    {
        "path": "projects/treemem",
        "name": "treemem",
        "aliases": ["memory", "mcp"],
        "summary": "Hierarchical agent-writable memory server stored as plain markdown.",
    },
    {
        "path": "user/preferences/food",
        "name": "food",
        "aliases": ["diet", "eating"],
        "summary": "User prefers vegetarian food, likes sushi and Thai cuisine.",
    },
]


@pytest.fixture
def mock_provider():
    return DeterministicEmbeddingProvider(dimension=64, seed=123)


@pytest.fixture
def dense_index(mock_provider):
    si = SearchIndex(embedding_provider=mock_provider)
    si.build(
        log_entries=[
            {"entry_id": "e1", "fact": "I ran a half marathon last month", "hint": "fitness"},
            {"entry_id": "e2", "fact": "Taking a deep learning course on transformers", "hint": "education"},
        ],
        leaf_facts=[
            {"entry_id": "e1", "path": "user/hobbies/fitness"},
            {"entry_id": "e2", "path": "user/education/coursework"},
        ],
        nodes=SAMPLE_NODES,
    )
    return si


# ---------------------------------------------------------------------------
# Vector Math Tests
# ---------------------------------------------------------------------------

def test_normalize_vector():
    v = np.array([3.0, 4.0], dtype=np.float32)
    normed = normalize_vector(v)
    assert pytest.approx(np.linalg.norm(normed), rel=1e-5) == 1.0
    assert pytest.approx(normed[0], rel=1e-5) == 0.6
    assert pytest.approx(normed[1], rel=1e-5) == 0.8

    zero_v = np.zeros(5, dtype=np.float32)
    assert np.all(normalize_vector(zero_v) == zero_v)


def test_normalize_matrix():
    mat = np.array([[3.0, 4.0], [1.0, 0.0], [0.0, 0.0]], dtype=np.float32)
    normed = normalize_matrix(mat)
    assert pytest.approx(np.linalg.norm(normed[0]), rel=1e-5) == 1.0
    assert pytest.approx(np.linalg.norm(normed[1]), rel=1e-5) == 1.0
    assert np.all(normed[2] == 0.0)


def test_cosine_similarity():
    u = np.array([1.0, 0.0], dtype=np.float32)
    v = np.array([0.0, 1.0], dtype=np.float32)
    assert pytest.approx(cosine_similarity(u, v)) == 0.0

    w = np.array([1.0, 0.0], dtype=np.float32)
    assert pytest.approx(cosine_similarity(u, w)) == 1.0


def test_cosine_similarity_matrix():
    q = np.array([1.0, 0.0], dtype=np.float32)
    docs = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]], dtype=np.float32)
    sims = cosine_similarity_matrix(q, docs)
    assert pytest.approx(sims[0]) == 1.0
    assert pytest.approx(sims[1]) == 0.0
    assert pytest.approx(sims[2]) == -1.0


# ---------------------------------------------------------------------------
# Deterministic Provider Tests
# ---------------------------------------------------------------------------

def test_deterministic_provider_properties(mock_provider):
    assert mock_provider.dimension == 64
    assert mock_provider.name == "deterministic-64d"

    vec = mock_provider.embed_text("trail running and cycling workout")
    assert vec.shape == (64,)
    assert pytest.approx(np.linalg.norm(vec), rel=1e-5) == 1.0


def test_deterministic_provider_reproducibility(mock_provider):
    text = "Machine learning and distributed systems"
    v1 = mock_provider.embed_text(text)
    v2 = mock_provider.embed_text(text)
    assert np.allclose(v1, v2)


def test_deterministic_provider_batch(mock_provider):
    texts = ["cycling workout", "operating systems", "sushi dinner"]
    mat = mock_provider.embed_batch(texts)
    assert mat.shape == (3, 64)
    for row in mat:
        assert pytest.approx(np.linalg.norm(row), rel=1e-5) == 1.0


def test_deterministic_provider_semantic_proximity(mock_provider):
    v_fit1 = mock_provider.embed_text("running at the gym for workout and fitness")
    v_fit2 = mock_provider.embed_text("fitness gym workout session with cycling")
    v_food = mock_provider.embed_text("vegetarian sushi roll with avocado")

    sim_fit = cosine_similarity(v_fit1, v_fit2)
    sim_diff = cosine_similarity(v_fit1, v_food)
    assert sim_fit > sim_diff, f"Expected {sim_fit} > {sim_diff}"


# ---------------------------------------------------------------------------
# API Provider Mocking Tests
# ---------------------------------------------------------------------------

def test_openai_compatible_provider(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    {"index": 0, "embedding": [0.6, 0.8]},
                    {"index": 1, "embedding": [1.0, 0.0]},
                ]
            }

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.post.return_value = FakeResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key",
        base_url="https://api.fake.com/v1",
        model="test-embed-model",
        dimension=2,
    )
    assert provider.name == "api-test-embed-model"
    mat = provider.embed_batch(["hello", "world"])
    assert mat.shape == (2, 2)
    assert pytest.approx(np.linalg.norm(mat[0]), rel=1e-5) == 1.0
    assert pytest.approx(np.linalg.norm(mat[1]), rel=1e-5) == 1.0


# ---------------------------------------------------------------------------
# Factory Tests
# ---------------------------------------------------------------------------

def test_get_embedding_provider_factory(monkeypatch):
    monkeypatch.setenv("TREEMEM_EMBEDDING_PROVIDER", "deterministic")
    prov = get_embedding_provider(force_new=True, dimension=32)
    assert prov is not None
    assert prov.dimension == 32

    monkeypatch.setenv("TREEMEM_EMBEDDING_PROVIDER", "none")
    assert get_embedding_provider(force_new=True) is None


# ---------------------------------------------------------------------------
# Hybrid Placement & Search Integration Tests
# ---------------------------------------------------------------------------

def test_dense_candidate_placement_fitness(dense_index):
    """Fact about trail runs and gym exercises should rank fitness top with source=dense."""
    candidates = dense_index.candidate_nodes(
        fact="Did an intense cycling workout and trail run at the gym",
        hint="",
        limit=3,
    )
    assert len(candidates) > 0
    top = candidates[0]
    assert top["path"] == "user/hobbies/fitness"
    assert top["source"] in ("dense", "tfidf", "bm25")
    assert 0.0 <= top["score"] <= 1.0


def test_dense_candidate_exact_hint_still_dominates(dense_index):
    """Explicit user hint should always have score 1.0 and source=hint."""
    candidates = dense_index.candidate_nodes(
        fact="Studying hard for exams",
        hint="projects/treemem",
        limit=3,
        all_node_paths=[n["path"] for n in SAMPLE_NODES],
    )
    assert candidates[0]["path"] == "projects/treemem"
    assert candidates[0]["score"] == 1.0
    assert candidates[0]["source"] == "hint"


def test_dense_query_search_hybrid(dense_index):
    """Dense query should retrieve matching log entries."""
    hits = dense_index.query("half marathon run", limit=5)
    assert len(hits) > 0
    assert hits[0]["entry_id"] == "e1"
    assert "marathon" in hits[0]["text"]


def test_dense_add_entry_dynamic(dense_index):
    """Dynamically adding an entry updates entry embeddings."""
    assert len(dense_index.entry_docs) == 2
    dense_index.add_entry("e3", "Tasting matcha green tea and sushi", hint="food")
    assert len(dense_index.entry_docs) == 3
    assert dense_index._entry_embeddings.shape[0] == 3

    hits = dense_index.query("matcha sushi", limit=5)
    assert any(h["entry_id"] == "e3" for h in hits)


def test_index_without_embeddings_still_works():
    """Index with embedding_provider=None gracefully falls back."""
    si = SearchIndex(embedding_provider=None)
    si.build(log_entries=[], leaf_facts=[], nodes=SAMPLE_NODES)
    res = si.candidate_nodes(fact="cycling workout at gym", limit=2)
    assert len(res) <= 2
    assert res[0]["source"] in ("bm25", "tfidf")
