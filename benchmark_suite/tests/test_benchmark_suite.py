"""Tests for benchmark_suite metrics, schemas, and adapters."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark_suite.adapters.lexical import BM25Retriever, FlatAllRetriever
from benchmark_suite.metrics.answers import extractive_answer, grade_answer
from benchmark_suite.metrics.ranking import evaluate_ranking, ndcg_at_k, precision_at_k, recall_at_k
from benchmark_suite.schemas import MemoryRecord, QueryRecord, memory_path_for
from benchmark_suite.dataset_tools.generate import validate_dataset, write_dataset


def _mem(i: int, **kw) -> MemoryRecord:
    base = dict(
        memory_id=f"m{i}", content=f"User {i} prefers color {i % 7} for dashboards.",
        category="preferences", timestamp="2025-01-01T00:00:00Z",
        path=memory_path_for("preferences", i, None, {"topic": "design"}),
        metadata={"fields": {"entity": f"User {i}", "attribute": "preference", "topic": "design", "value": f"color{i%7}"}},
    )
    base.update(kw)
    return MemoryRecord(**base)


def test_ranking_metrics_known_values():
    retrieved = ["a", "b", "c"]
    relevant = ["b", "d"]
    graded = {"b": 1.0, "d": 1.0}
    assert precision_at_k(retrieved, relevant, graded, 3) == pytest.approx(1/3)
    assert recall_at_k(retrieved, relevant, graded, 3) == pytest.approx(0.5)
    m = evaluate_ranking(retrieved, {"relevant_memory_ids": relevant, "graded_relevance": graded})
    assert m["mrr"] == pytest.approx(0.5)
    assert 0.0 <= m["ndcg@10"] <= 1.0


def test_bm25_and_flat_adapters():
    mems = [_mem(i) for i in range(10)]
    q = QueryRecord(query_id="q1", question="What color does User 3 prefer?", category="direct", split="test", relevant_memory_ids=["m3"])
    bm = BM25Retriever(mems).retrieve(q, k=5)
    assert bm.items and bm.items[0].memory_id == "m3"
    flat = FlatAllRetriever(mems).retrieve(q, k=5)
    assert len(flat.items) == 10


def test_private_filtering():
    mems = [_mem(1), _mem(2, sensitivity="private", privacy_canary="secret-value", provenance={"privacy_mode": "private"})]
    q = QueryRecord(query_id="q2", question="secret-value", category="private", split="test", relevant_memory_ids=["m2"], forbidden_values=["secret-value"])
    bm = BM25Retriever(mems).retrieve(q, k=5, reveal=False)
    assert all(i.memory_id != "m2" for i in bm.items)
    grade = grade_answer("I don't have enough information to answer.", q.to_dict() | {"abstain_expected": True})
    assert grade["correct"] is True


def test_dataset_write_and_validate(tmp_path: Path):
    out = tmp_path / "ds"
    manifest = write_dataset(out, scale=20, seed=3, query_count=24)
    assert manifest["memory_stats"]["memories_written"] >= 20
    report = validate_dataset(out)
    assert report["ok"], report["errors"][:5]


def test_extractive_answer_and_grade():
    q = {"expected_answer": "Alice preference: tea", "abstain_expected": False, "forbidden_values": []}
    ans = extractive_answer("[1] Alice prefers tea for meetings.\n[2] Bob likes coffee.", q["expected_answer"])
    assert "tea" in ans
    assert grade_answer(ans, q)["correct"] is True
