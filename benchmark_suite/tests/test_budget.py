"""Tests for budget-constrained context packing and the budget runner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark_suite.adapters.base import RetrievedItem, RetrievalResult
from benchmark_suite.budgeting import (
    ContextUnit,
    pack_to_budget,
    truncate_to_tokens,
    units_from_result,
)
from benchmark_suite.metrics.ranking import evaluate_budget_ranking
from benchmark_suite.reporting.report import aggregate_budget
from benchmark_suite.runners.budget import run_budget
from treemem.tokenizer import count_tokens


def _unit(text: str, ids=None, kind: str = "memory") -> ContextUnit:
    return ContextUnit(text=text, memory_ids=ids or [], kind=kind)


def test_pack_never_exceeds_budget():
    units = [_unit(f"memory fact number {i} about topic {i % 7}", [f"m{i}"]) for i in range(200)]
    for budget in (0, 1, 8, 50, 256, 1465, 4096):
        packed = pack_to_budget(units, budget)
        assert packed.tokens_used <= budget
        assert packed.context_text == "" or count_tokens(packed.context_text) <= budget + 2


def test_pack_preserves_order_and_ids():
    units = [
        _unit("alpha beta gamma", ["a"]),
        _unit("delta epsilon zeta", ["b"]),
        _unit("eta theta iota", ["c"]),
    ]
    budget = count_tokens(units[0].text) + count_tokens("\n\n") + count_tokens(units[1].text) + count_tokens("\n\n")
    packed = pack_to_budget(units, budget)
    assert [u.text for u in packed.units] == [units[0].text, units[1].text]
    assert packed.packed_memory_ids == ["a", "b"]
    assert packed.units_dropped == 1


def test_pack_truncates_oversized_unit():
    big = _unit(" ".join(["word"] * 200), ["big"])
    packed = pack_to_budget([big], 60)
    assert packed.tokens_used <= 60
    assert len(packed.units) == 1
    assert packed.units[0].truncated is True
    assert packed.truncated_count == 1
    assert packed.units[0].memory_ids == ["big"]


def test_pack_zero_budget_empty():
    packed = pack_to_budget([_unit("hello world", ["x"])], 0)
    assert packed.units == []
    assert packed.tokens_used == 0
    assert packed.packed_memory_ids == []


def test_pack_truncates_before_dropping_later_units():
    units = [
        _unit(" ".join(["big"] * 100), ["big"]),
        _unit("tiny fact", ["small"]),
    ]
    packed = pack_to_budget(units, 40)
    # The oversized first unit is truncated into the budget; the later unit
    # is dropped because nothing remains.
    assert packed.units[0].memory_ids == ["big"]
    assert packed.units[0].truncated is True
    assert packed.tokens_used <= 40
    assert "small" not in packed.packed_memory_ids


def test_pack_defers_zero_id_units():
    units = [
        _unit("NAVIGATIONAL PREAMBLE text", [], kind="preamble"),
        _unit("leaf fact alpha", ["m1"], kind="fact"),
        _unit("leaf fact beta", ["m2"], kind="fact"),
    ]
    budget = count_tokens(units[1].text) + count_tokens("\n\n") + count_tokens(units[2].text) + count_tokens("\n\n")
    packed = pack_to_budget(units, budget)
    # Evidence units pack first; the preamble only gets leftover budget.
    assert packed.packed_memory_ids == ["m1", "m2"]
    assert all(u.kind != "preamble" for u in packed.units)


def test_truncate_to_tokens_respects_limit():
    text = "The quick brown fox jumps over the lazy dog. " * 20
    for n in (1, 5, 17, 64):
        out = truncate_to_tokens(text, n)
        assert count_tokens(out) <= n


def test_units_from_result_default():
    result = RetrievalResult(
        arm="bm25", query_id="q1", items=[
            RetrievedItem(memory_id="m1", score=1.0, rank=1, text="fact one"),
            RetrievedItem(memory_id="m2", score=0.5, rank=2, text="fact two"),
        ],
        context_text="", context_tokens=0, latency_ms=0.0,
    )
    units = units_from_result(result)
    assert [u.memory_ids for u in units] == [["m1"], ["m2"]]
    assert all(u.kind == "memory" for u in units)


def test_units_from_result_budget_units_metadata():
    meta_units = [
        {"text": "SUMMARY preamble", "memory_ids": [], "kind": "preamble"},
        {"text": "leaf fact", "memory_ids": ["m9"], "kind": "fact"},
        {"text": "hit text", "memory_ids": ["m3"], "kind": "search_hit"},
    ]
    result = RetrievalResult(
        arm="treemem_guided", query_id="q1", items=[], context_text="",
        context_tokens=0, latency_ms=0.0, metadata={"budget_units": meta_units},
    )
    units = units_from_result(result)
    assert [u.kind for u in units] == ["preamble", "fact", "search_hit"]
    assert units[1].memory_ids == ["m9"]


def test_units_from_result_unit_cap():
    result = RetrievalResult(
        arm="flat_all", query_id="q1",
        items=[RetrievedItem(memory_id=f"m{i}", score=1.0, rank=i, text=f"fact {i}") for i in range(50)],
        context_text="", context_tokens=0, latency_ms=0.0,
    )
    assert len(units_from_result(result, unit_cap=10)) == 10


def test_evaluate_budget_ranking():
    q = {"relevant_memory_ids": ["a", "b", "c"], "graded_relevance": {"a": 1.0, "b": 1.0, "c": 1.0}}
    m = evaluate_budget_ranking(["a", "x", "b"], q)
    assert m["recall_budget"] == pytest.approx(2 / 3)
    assert m["items_in_budget"] == 3.0
    assert m["recall@3"] == pytest.approx(2 / 3)
    m_empty = evaluate_budget_ranking([], q)
    assert m_empty["recall_budget"] == 0.0


def _tiny_dataset(tmp_path: Path):
    """Write a minimal two-memory dataset for runner smoke tests."""
    memories = [
        {"memory_id": "m1", "content": "Alice prefers tea for morning meetings.", "category": "preferences",
         "timestamp": "2025-01-01T00:00:00Z", "path": "personal/preferences/group_0/leaf_0/item_0",
         "metadata": {"fields": {"entity": "Alice", "attribute": "preference", "topic": "morning meetings", "value": "tea"}}},
        {"memory_id": "m2", "content": "Bob uses Postgres for the Atlas project.", "category": "technical",
         "timestamp": "2025-01-02T00:00:00Z", "path": "technical/projects/group_1/leaf_0/item_0",
         "metadata": {"fields": {"entity": "Atlas", "attribute": "tool", "topic": "database", "value": "Postgres"}}},
    ]
    queries = [
        {"query_id": "q1", "question": "What does Alice prefer for morning meetings?",
         "category": "direct", "split": "test", "relevant_memory_ids": ["m1"],
         "expected_answer": "tea", "graded_relevance": {"m1": 1.0}},
        {"query_id": "q2", "question": "Which database does Bob use?",
         "category": "direct", "split": "test", "relevant_memory_ids": ["m2"],
         "expected_answer": "Postgres", "graded_relevance": {"m2": 1.0}},
    ]
    ds = tmp_path / "ds"
    ds.mkdir(parents=True)
    (ds / "memories.jsonl").write_text("\n".join(json.dumps(m) for m in memories) + "\n")
    (ds / "queries.jsonl").write_text("\n".join(json.dumps(q) for q in queries) + "\n")
    (ds / "manifest.json").write_text(json.dumps({"memories_file": "memories.jsonl", "queries_file": "queries.jsonl"}))
    return ds


def test_run_budget_smoke_and_resume(tmp_path):
    ds = _tiny_dataset(tmp_path)
    out = tmp_path / "out"
    res = run_budget(ds, out, arms=["bm25"], budgets=[64, 256], split="test")
    assert res["completed"] == 4  # 1 arm x 2 queries x 2 budgets
    rows = [json.loads(l) for l in (out / "episodes.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 4
    for r in rows:
        assert r["experiment"] == "budget"
        assert r["tokens_used"] <= r["budget"]
        assert 0.0 <= r["metrics"]["recall_budget"] <= 1.0
        assert r["packed_memory_ids"] or r["tokens_used"] == 0
    # Resume: second run adds nothing.
    res2 = run_budget(ds, out, arms=["bm25"], budgets=[64, 256], split="test")
    assert res2["completed"] == 4
    rows2 = [json.loads(l) for l in (out / "episodes.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows2) == 4


def test_run_budget_with_answers(tmp_path):
    ds = _tiny_dataset(tmp_path)
    out = tmp_path / "out_answers"
    res = run_budget(ds, out, arms=["bm25"], budgets=[256], split="test", answers=True)
    assert res["completed"] == 2
    rows = [json.loads(l) for l in (out / "episodes.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    for r in rows:
        assert "answer" in r
        assert "answer_grade" in r
        assert "answer_f1" in r
        assert r["answer_f1"] is None or 0.0 <= r["answer_f1"] <= 1.0
    # q1 expects "tea"; bm25 should retrieve m1 whose text contains "tea".
    q1 = next(r for r in rows if r["query_id"] == "q1")
    assert q1["answer_grade"]["correct"] is True
    # Aggregation surfaces answer metrics.
    summary = aggregate_budget(out / "episodes.jsonl", out)
    cell = summary["arms"]["bm25"]["by_budget"]["256"]
    assert "answer_f1_ci95" in cell
    assert "answer_correct_ci95" in cell


def test_run_budget_without_answers_has_no_answer_fields(tmp_path):
    ds = _tiny_dataset(tmp_path)
    out = tmp_path / "out_no_answers"
    run_budget(ds, out, arms=["bm25"], budgets=[256], split="test")
    rows = [json.loads(l) for l in (out / "episodes.jsonl").read_text().splitlines() if l.strip()]
    assert all("answer" not in r and "answer_f1" not in r for r in rows)
    summary = aggregate_budget(out / "episodes.jsonl", out)
    assert "answer_f1_ci95" not in summary["arms"]["bm25"]["by_budget"]["256"]


def test_answer_token_f1():
    from benchmark_suite.metrics.answers import answer_token_f1
    # pred {alice,prefers,tea} vs exp {tea}: P=1/3, R=1 -> F1=0.5
    assert answer_token_f1("Alice prefers tea", "tea") == pytest.approx(0.5)
    assert answer_token_f1("completely unrelated words", "tea") == 0.0
    assert answer_token_f1("anything", None) is None


def test_run_budget_guided_plus_global_arm(tmp_path):
    ds = _tiny_dataset(tmp_path)
    out = tmp_path / "out_plus_global"
    res = run_budget(ds, out, arms=["treemem_guided_plus_global"], budgets=[256], split="test")
    assert res["completed"] == 2
    rows = [json.loads(l) for l in (out / "episodes.jsonl").read_text().splitlines() if l.strip()]
    for r in rows:
        meta = r.get("metadata") or {}
        assert meta.get("global_search_limit") == 20
        assert r["experiment"] == "budget"
        assert r["tokens_used"] <= r["budget"]


def test_aggregate_budget(tmp_path):
    ep = tmp_path / "episodes.jsonl"
    rows = []
    for arm in ("bm25", "treemem_guided"):
        for budget in (64, 256):
            for i in range(3):
                rows.append({
                    "arm": arm, "query_id": f"q{i}", "query_category": "direct",
                    "budget": budget, "tokens_used": min(budget, 50), "utilization": 0.5,
                    "packed_memory_ids": ["m1"], "error": None,
                    "metrics": {"recall_budget": 1.0, "recall@5": 1.0, "mrr": 1.0},
                })
    ep.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summary = aggregate_budget(ep, tmp_path)
    assert summary["experiment"] == "budget"
    assert set(summary["budgets"]) == {64, 256}
    cell = summary["arms"]["bm25"]["by_budget"]["64"]
    assert cell["overall"]["recall_budget"] == pytest.approx(1.0)
    assert cell["tokens_used"]["mean"] == pytest.approx(50.0)
