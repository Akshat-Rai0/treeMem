"""Phase D tests: multi-folder README table generation and NEGATIVE_KEYWORDS word-boundary fix."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

# ---------------------------------------------------------------------------
# Helpers to import bench modules without running them as scripts
# ---------------------------------------------------------------------------

BENCH_DIR = Path(__file__).resolve().parent.parent / "bench"
EVAL_DIR = BENCH_DIR / "eval"


def _load_make_readme():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "make_readme_tables", BENCH_DIR / "make_readme_tables.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_run_eval():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_eval_module", EVAL_DIR / "run_eval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests: README table generation (D.3 / D.4)
# ---------------------------------------------------------------------------


def _make_minimal_aggregate(model: str = "test-model", runs: int = 1, questions: int = 15) -> Dict[str, Any]:
    """Return a minimal aggregate dict that format_aggregate_table can handle."""
    def _stat(v: float) -> Dict[str, float]:
        return {"mean": v, "std": 0.0}

    return {
        "model": model,
        "runs": runs,
        "questions": questions,
        "arms": {
            "tree_follow": {
                "accuracy_pct": _stat(100.0),
                "private_leaks": _stat(0.0),
                "wire_tokens": _stat(34807.0),
                "mean_hops": _stat(1.07),
                "single_call_rate_pct": _stat(93.33),
                "mean_latency_sec": _stat(6.3),
            }
        },
        "per_question_pass_rate": {},
        "key_usage_counts": {},
    }


def test_aggregate_table_placeholder_when_missing():
    mod = _load_make_readme()
    text = mod.format_aggregate_table(None)
    assert "Not measured yet" in text
    assert "run_eval.py --runs" in text


def test_aggregate_table_renders_three_arms():
    mod = _load_make_readme()
    def _metric(mean, std=0.0):
        return {"mean": mean, "std": std}

    entry = {
        "accuracy_pct": _metric(100.0, 0.0),
        "private_leaks": _metric(0.0),
        "wire_tokens": _metric(12345.0, 678.0),
        "mean_hops": _metric(2.5, 0.2),
        "single_call_rate_pct": _metric(40.0, 5.0),
        "mean_latency_sec": _metric(3.2, 0.4),
    }
    aggregate = {
        "runs": 5,
        "questions": 12,
        "model": "fake",
        "arms": {"flat": entry, "tree": entry, "tree_follow": entry},
    }
    text = mod.format_aggregate_table(aggregate)
    assert "5 runs x 12 questions" in text
    assert "guided descent" in text
    assert "12,345 ± 678" in text
    assert text.count("\n| ") >= 3


def test_smoke_block_formats_from_json():
    mod = _load_make_readme()
    smoke = {"token_reduction_pct": 9.2, "parent_stop_rate": 0.2, "latency_p50_ms": 2.29, "latency_p95_ms": 2.87}
    text = mod.format_smoke_block(smoke)
    assert "9.2%" in text and "20.0%" in text and "2.29 ms" in text and "2.87 ms" in text


def test_two_result_folders_both_appear(tmp_path):
    """Two results_* folders with aggregates both appear in the generated AGG2 block."""
    mod = _load_make_readme()

    # Create a fake primary results dir and two sibling results_* dirs
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    for name in ("results_alpha", "results_beta"):
        folder = tmp_path / name
        folder.mkdir()
        agg = _make_minimal_aggregate(model=name + "-model")
        (folder / "llm_eval_aggregate.json").write_text(json.dumps(agg), encoding="utf-8")

    found = mod.find_extra_aggregates(results_dir)
    assert len(found) == 2
    folder_names = {p.parent.name for p in found}
    assert "results_alpha" in folder_names
    assert "results_beta" in folder_names


def test_placeholder_when_no_extra_folders(tmp_path):
    """No results_* folders -> empty list from find_extra_aggregates."""
    mod = _load_make_readme()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    found = mod.find_extra_aggregates(results_dir)
    assert found == []


def test_format_large_vault_table_shows_question_mix():
    """format_large_vault_table includes the question mix when question_kinds is present."""
    mod = _load_make_readme()
    agg = _make_minimal_aggregate()
    agg["question_kinds"] = {"lookup": 15, "overview": 0, "private": 0, "negative": 0}

    result = mod.format_large_vault_table(agg, "results_large_vault")
    assert "15 lookup" in result
    assert "results_large_vault" in result


def test_format_large_vault_table_shows_missing_mix_message():
    """format_large_vault_table falls back gracefully when question_kinds is absent."""
    mod = _load_make_readme()
    agg = _make_minimal_aggregate()
    # No question_kinds key
    result = mod.format_large_vault_table(agg, "results_large_vault")
    assert "question mix not recorded" in result


# ---------------------------------------------------------------------------
# Tests: NEGATIVE_KEYWORDS word-boundary fix (D.5)
# ---------------------------------------------------------------------------


def test_none_with_punctuation_is_a_refusal():
    """'None.' should match \\bNone\\b and count as a refusal."""
    ev = _load_run_eval()
    assert ev.grade_answer("None.", ev.NEGATIVE_KEYWORDS) is True


def test_none_standalone_is_a_refusal():
    """Plain 'none' is a refusal."""
    ev = _load_run_eval()
    assert ev.grade_answer("none", ev.NEGATIVE_KEYWORDS) is True


def test_nonetheless_is_not_a_refusal():
    """'nonetheless' must NOT match the \\bNone\\b pattern."""
    ev = _load_run_eval()
    result = ev.grade_answer("nonetheless the user likes Rust", ev.NEGATIVE_KEYWORDS)
    assert result is False, "'nonetheless' matched as a refusal via bare 'none'"


def test_no_one_knows_is_not_a_refusal():
    """'no one knows' must NOT match any NEGATIVE_KEYWORD."""
    ev = _load_run_eval()
    result = ev.grade_answer("no one knows", ev.NEGATIVE_KEYWORDS)
    assert result is False, "'no one knows' matched as a refusal unexpectedly"


def test_not_mentioned_is_a_refusal():
    """Multi-word keyword 'not mentioned' still works via substring match."""
    ev = _load_run_eval()
    assert ev.grade_answer("this is not mentioned anywhere", ev.NEGATIVE_KEYWORDS) is True
