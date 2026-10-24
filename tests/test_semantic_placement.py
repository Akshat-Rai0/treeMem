"""Tests for Task A: Hybrid Semantic Placement (BM25 + TF-IDF cosine similarity)."""

import pytest
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
    {
        "path": "user/work/job",
        "name": "job",
        "aliases": ["career", "employment"],
        "summary": "Software engineer at a tech startup working on backend infrastructure.",
    },
]


@pytest.fixture
def idx():
    si = SearchIndex()
    si.build(log_entries=[], leaf_facts=[], nodes=SAMPLE_NODES)
    return si


# ---------------------------------------------------------------------------
# Task A core tests
# ---------------------------------------------------------------------------

def test_hybrid_fitness_fact(idx):
    """A mountain bike / trail riding fact must rank fitness above treemem (BM25 alone would fail)."""
    result = idx.candidate_nodes(
        fact="I bought a mountain bike and love doing trail rides on weekends",
        hint="",
        limit=3,
    )
    paths = [r["path"] for r in result]
    assert "user/hobbies/fitness" in paths, f"fitness not found in top-3: {paths}"
    # fitness must outrank treemem
    if "projects/treemem" in paths:
        fitness_rank = paths.index("user/hobbies/fitness")
        treemem_rank = paths.index("projects/treemem")
        assert fitness_rank < treemem_rank, "fitness should rank above treemem"


def test_hybrid_coursework_fact(idx):
    """An algorithms/compilers coursework fact must rank education/coursework first."""
    result = idx.candidate_nodes(
        fact="Currently studying Advanced Algorithms and Compilers for my CS degree",
        hint="",
        limit=3,
    )
    paths = [r["path"] for r in result]
    assert "user/education/coursework" in paths, f"coursework not found in top-3: {paths}"
    assert paths[0] == "user/education/coursework", f"coursework not ranked #1: {paths}"


def test_hybrid_food_fact(idx):
    """A sushi / cuisine preference fact should suggest food node, not treemem or job."""
    result = idx.candidate_nodes(
        fact="I tried a new sushi restaurant and loved the vegetarian rolls",
        hint="",
        limit=3,
    )
    paths = [r["path"] for r in result]
    assert "user/preferences/food" in paths, f"food not found in top-3: {paths}"
    assert paths[0] == "user/preferences/food", f"food not ranked #1: {paths}"


def test_exact_hint_wins(idx):
    """An exact hint match is always ranked first regardless of semantic score."""
    result = idx.candidate_nodes(
        fact="Going for a run tomorrow",
        hint="user/education/coursework",
        limit=3,
        all_node_paths=[n["path"] for n in SAMPLE_NODES],
    )
    assert result[0]["path"] == "user/education/coursework"
    assert result[0]["score"] == 1.0
    assert result[0]["source"] == "hint"


def test_scores_in_unit_interval(idx):
    """All scores must be within [0.0, 1.0]."""
    result = idx.candidate_nodes(
        fact="backend infrastructure engineering and system design",
        hint="",
        limit=5,
    )
    for r in result:
        assert 0.0 <= r["score"] <= 1.0, f"score out of range: {r}"


def test_empty_fact_returns_empty(idx):
    """Empty fact string must return empty candidates."""
    result = idx.candidate_nodes(fact="", hint="", limit=3)
    assert result == []


def test_no_nodes_returns_empty():
    """Index with no nodes must return empty candidates."""
    si = SearchIndex()
    si.build(log_entries=[], leaf_facts=[], nodes=[])
    result = si.candidate_nodes(fact="anything", hint="", limit=3)
    assert result == []


def test_source_field_present(idx):
    """Every candidate must have a 'source' key."""
    result = idx.candidate_nodes(
        fact="machine learning and backend engineering",
        hint="",
        limit=5,
    )
    for r in result:
        assert "source" in r, f"'source' missing in candidate: {r}"


def test_limit_respected(idx):
    """candidate_nodes must return at most `limit` results."""
    result = idx.candidate_nodes(
        fact="studying working eating exercising coding",
        hint="",
        limit=2,
    )
    assert len(result) <= 2


def test_index_rebuild_is_idempotent(idx):
    """Rebuilding the index twice with the same data gives same top candidate."""
    fact = "cycling at the gym for cardio workout"
    r1 = idx.candidate_nodes(fact=fact, limit=1)
    idx.build(log_entries=[], leaf_facts=[], nodes=SAMPLE_NODES)
    r2 = idx.candidate_nodes(fact=fact, limit=1)
    assert r1[0]["path"] == r2[0]["path"]
