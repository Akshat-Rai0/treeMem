"""The README generator must handle both 'no aggregate yet' and a real aggregate."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_generator():
    spec = importlib.util.spec_from_file_location("make_readme_tables_under_test", ROOT / "bench" / "make_readme_tables.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


def _metric(mean, std=0.0):
    return {"mean": mean, "std": std}


def test_aggregate_table_placeholder_when_missing():
    text = gen.format_aggregate_table(None)
    assert "Not measured yet" in text
    assert "run_eval.py --runs" in text


def test_aggregate_table_renders_three_arms():
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
    text = gen.format_aggregate_table(aggregate)
    assert "5 runs x 12 questions" in text
    assert "guided descent" in text
    assert "12,345 ± 678" in text
    assert text.count("\n| ") >= 3


def test_smoke_block_formats_from_json():
    smoke = {"token_reduction_pct": 9.2, "parent_stop_rate": 0.2, "latency_p50_ms": 2.29, "latency_p95_ms": 2.87}
    text = gen.format_smoke_block(smoke)
    assert "9.2%" in text and "20.0%" in text and "2.29 ms" in text and "2.87 ms" in text


def test_find_extra_aggregate(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    assert gen.find_extra_aggregate(results) is None
    second = tmp_path / "results_gptoss"
    second.mkdir()
    (second / "llm_eval_aggregate.json").write_text("{}")
    assert gen.find_extra_aggregate(results) == second / "llm_eval_aggregate.json"
