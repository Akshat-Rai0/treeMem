#!/usr/bin/env python3
"""Regenerate benchmark markdown tables in README.md from committed JSON results.

Ensures that numbers reported in documentation cannot drift from raw benchmark data.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_real_llm_table(data: Dict[str, Any]) -> str:
    flat_acc = data["flat_accuracy_pct"]
    tree_acc = data["treemem_accuracy_pct"]
    total_q = data.get("accuracy_questions", data["total_questions"])
    
    flat_payload = data["memory_payload_tokens"]["flat_total"]
    tree_payload = data["memory_payload_tokens"]["treemem_total"]
    payload_red = data["memory_payload_tokens"]["reduction_pct"]
    
    flat_wire = data["api_tokens_with_tool_overhead"]["flat_total"]
    tree_wire = data["api_tokens_with_tool_overhead"]["treemem_total"]
    
    ps_rate = data["parent_stop_rate_pct"]
    ps_count = data.get("parent_stops_count", 0)
    
    questions = data.get("questions", [])
    flat_lats = [q["flat"]["latency_sec"] for q in questions if "flat" in q]
    tree_lats = [q["treemem"]["latency_sec"] for q in questions if "treemem" in q]
    
    mean_flat_lat = sum(flat_lats) / len(flat_lats) if flat_lats else 0.0
    max_flat_lat = max(flat_lats) if flat_lats else 0.0
    
    mean_tree_lat = sum(tree_lats) / len(tree_lats) if tree_lats else 0.0
    max_tree_lat = max(tree_lats) if tree_lats else 0.0

    if abs(flat_acc - tree_acc) < 0.05:
        accuracy_note = "Parity on the scored questions"
    elif tree_acc > flat_acc:
        accuracy_note = "TreeMem higher on this run (single run, noisy)"
    else:
        accuracy_note = "Flat higher on this run (single run, noisy)"

    lines = [
        "| Metric | Flat Memory Dump | TreeMem Autonomous Descent | Impact |",
        "|:---|:---|:---|:---|",
        f"| **Answer Accuracy** | **{flat_acc:.1f}%** ({round(flat_acc * total_q / 100)}/{total_q}) | **{tree_acc:.1f}%** ({round(tree_acc * total_q / 100)}/{total_q}) | {accuracy_note} |",
        f"| **Memory Payload Tokens** | {flat_payload:,} tokens | **{tree_payload:,} tokens** | **{payload_red:.2f}% payload token reduction** |",
        f"| **Total API Wire Tokens** | **{flat_wire:,} tokens** | {tree_wire:,} tokens | Multi-turn tool calling re-sends schema/prompts per hop |",
        f"| **Parent-Stop Rate** | N/A | **{ps_rate:.1f}%** ({ps_count}/{total_q}) | Evaluated at root depth 0 when summary was sufficient |",
        f"| **Mean / Max Latency** | {mean_flat_lat:.2f}s / {max_flat_lat:.2f}s | {mean_tree_lat:.2f}s / {max_tree_lat:.2f}s | Multi-hop sequential tool execution latency |",
    ]
    leaks = data.get("private_leaks")
    if leaks is not None:
        lines.append(
            f"| **Private Data Leaked** (1 private question) | {leaks.get('flat', 0)} | {leaks.get('treemem', 0)} | Flat has no access control; TreeMem withholds private nodes unless the operator grants reveal |"
        )
    return "\n".join(lines)


def format_synthetic_table(data: Dict[str, Any]) -> str:
    scales = data.get("scales", {})
    lines = [
        "| Memory Scale | Flat Dump Cost | TreeMem Average Cost | Token Savings |",
        "|:---|:---|:---|:---|",
    ]
    for scale_key in sorted(scales.keys(), key=lambda x: int(x)):
        item = scales[scale_key]
        num = item["num_memories"]
        flat = item["flat_dump_tokens"]
        avg_tree = item["avg_tree_recall_tokens"]
        savings = item["token_savings_pct"]
        lines.append(f"| **{num:,} memories** | {flat:,} tokens | {avg_tree:,} tokens | **{savings:.2f}%** |")
    return "\n".join(lines)


def format_aggregate_table(aggregate: Optional[Dict[str, Any]]) -> str:
    """Repeated-run table (mean +/- std) from bench/results/llm_eval_aggregate.json."""
    if not aggregate:
        return (
            "_Not measured yet._ Run `python bench/eval/run_eval.py --runs 5` (needs Groq keys in `.env`) "
            "and then `python bench/make_readme_tables.py`."
        )

    arm_labels = {
        "flat": "Flat dump",
        "tree": "TreeMem, manual descent",
        "tree_follow": "TreeMem, guided descent (`follow=true`)",
    }

    def cell(entry: Dict[str, Any], metric: str, digits: int = 1) -> str:
        value = entry[metric]
        return f"{value['mean']:.{digits}f} ± {value['std']:.{digits}f}"

    header = (
        f"{aggregate['runs']} runs x {aggregate['questions']} questions, `{aggregate['model']}`, mean ± std. "
        "Accuracy is over the non-private questions; latency excludes pacing sleeps."
    )
    lines = [
        header,
        "",
        "| Arm | Accuracy % | Private leaks | Wire tokens | Mean hops | Single-call % | Mean latency (s) |",
        "|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for arm, entry in aggregate["arms"].items():
        label = arm_labels.get(arm, arm)
        wire_cell = f"{entry['wire_tokens']['mean']:,.0f} ± {entry['wire_tokens']['std']:,.0f}"
        lines.append(
            f"| {label} | {cell(entry, 'accuracy_pct')} | {cell(entry, 'private_leaks')} | {wire_cell} | "
            f"{cell(entry, 'mean_hops', 2)} | {cell(entry, 'single_call_rate_pct')} | {cell(entry, 'mean_latency_sec', 2)} |"
        )
    return "\n".join(lines)


def format_smoke_block(smoke: Dict[str, Any]) -> str:
    return "\n".join([
        f"- **Token Reduction**: {smoke['token_reduction_pct']}% on a small 8-fact vault.",
        f"- **Parent-Stop Rate**: {smoke['parent_stop_rate'] * 100:.1f}% (depth 0).",
        f"- **Descent Latency**: p50 = {smoke['latency_p50_ms']} ms, p95 = {smoke['latency_p95_ms']} ms.",
        "- *Raw data committed in [`bench/results/smoke_test_results.json`](bench/results/smoke_test_results.json).*",
    ])


def count_passing_tests(repo_root: Path) -> Optional[int]:
    """Run pytest and return the number of passed tests (None if it cannot be determined)."""
    command = [sys.executable, "-m", "pytest", "-q", "tests", "-p", "no:cacheprovider"]
    env_path = str(repo_root / "src")
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=900,
            env={**__import__("os").environ, "PYTHONPATH": env_path},
        )
    except Exception:
        return None
    output = completed.stdout + completed.stderr
    match = re.search(r"(\d+) passed", output)
    if not match:
        return None
    if re.search(r"\d+ failed", output):
        return None
    return int(match.group(1))


def format_portfolio_table(
    real: Dict[str, Any],
    synth: Dict[str, Any],
    smoke: Dict[str, Any],
    test_count: Optional[int],
) -> str:
    total_q = real["total_questions"]
    questions = real.get("questions", [])
    tree_lats = [q["treemem"]["latency_sec"] for q in questions if "treemem" in q]
    flat_lats = [q["flat"]["latency_sec"] for q in questions if "flat" in q]
    mean_tree = sum(tree_lats) / len(tree_lats) if tree_lats else 0.0
    mean_flat = sum(flat_lats) / len(flat_lats) if flat_lats else 0.0

    savings = [item["token_savings_pct"] for item in synth.get("scales", {}).values()]
    low = min(savings) if savings else 0.0
    high = max(savings) if savings else 0.0

    key_counts = real.get("key_usage_counts", {})
    total_calls = sum(key_counts.values())

    flat_wire = real["api_tokens_with_tool_overhead"]["flat_total"]
    tree_wire = real["api_tokens_with_tool_overhead"]["treemem_total"]
    ratio = tree_wire / flat_wire if flat_wire else 0.0

    tests_cell = f"{test_count} passing" if test_count is not None else "not measured"

    lines = [
        "| Metric | Measured Value | Benchmark Configuration |",
        "|:---|:---|:---|",
        f"| **Answer Accuracy** | flat {real['flat_accuracy_pct']:.1f}% / tree {real['treemem_accuracy_pct']:.1f}% | single run, n={total_q}, `{real['model']}` (`bench/results/llm_eval_results.json`) |",
        f"| **Memory Payload Reduction** | {real['memory_payload_tokens']['reduction_pct']:.2f}% | same run; payload tokens only |",
        f"| **Total API Wire Tokens** | flat {flat_wire:,} / tree {tree_wire:,} ({ratio:.1f}x) | same run; includes tool schemas re-sent per hop |",
        f"| **Parent-Stop Rate** | {real['parent_stop_rate_pct']:.1f}% ({real.get('parent_stops_count', 0)}/{total_q}) | same run |",
        f"| **Mean Latency** | flat {mean_flat:.2f}s / tree {mean_tree:.2f}s | same run |",
        f"| **Scaling Payload Savings** | {low:.2f}% - {high:.2f}% | synthetic vault, scripted descent (`bench/results/flat_vs_tree_tokens.json`) |",
        f"| **Descent Plumbing Latency** | p50 = {smoke['latency_p50_ms']} ms, p95 = {smoke['latency_p95_ms']} ms | in-memory traversal only (`bench/results/smoke_test_results.json`) |",
        f"| **Rate-Limit Failover** | {total_calls} calls across {len(key_counts)} keys | Groq key rotation in the eval harness |",
        f"| **Test Suite** | {tests_cell} | `pytest tests` (concurrency, property, crash recovery, privacy) |",
    ]
    return "\n".join(lines)


def update_test_count_mentions(readme: str, test_count: Optional[int]) -> str:
    """Keep the README badge and the sample pytest output in sync with the measured count."""
    if test_count is None:
        return readme
    readme = re.sub(r"Tests: \d+ Passing", f"Tests: {test_count} Passing", readme)
    readme = re.sub(r"tests-\d+%20passed", f"tests-{test_count}%20passed", readme)
    readme = re.sub(r"(=+ )\d+( passed in )", rf"\g<1>{test_count}\g<2>", readme)
    return readme


def replace_table(content: str, start_tag: str, end_tag: str, new_table: str) -> str:
    if start_tag not in content or end_tag not in content:
        raise ValueError(f"Marker tags {start_tag} / {end_tag} not found in target text.")
    before = content.split(start_tag)[0] + start_tag + "\n"
    after = "\n" + end_tag + content.split(end_tag)[1]
    return before + new_table + after


def main():
    parser = argparse.ArgumentParser(description="Regenerate benchmark tables from committed JSON.")
    parser.add_argument("--skip-tests", action="store_true", help="Do not run pytest (test count shown as not measured).")
    parser.add_argument("--tests", type=int, default=None, help="Use this test count instead of running pytest.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    readme_path = repo_root / "README.md"
    portfolio_path = repo_root / "docs" / "portfolio.md"
    results_dir = repo_root / "bench" / "results"

    if not readme_path.exists():
        print(f"Error: {readme_path} not found.")
        return

    real_data = load_json(results_dir / "llm_eval_results.json")
    synth_data = load_json(results_dir / "flat_vs_tree_tokens.json")
    smoke_data = load_json(results_dir / "smoke_test_results.json")

    if args.tests is not None:
        test_count: Optional[int] = args.tests
    elif args.skip_tests:
        test_count = None
    else:
        test_count = count_passing_tests(repo_root)

    aggregate_path = results_dir / "llm_eval_aggregate.json"
    aggregate_data = load_json(aggregate_path) if aggregate_path.exists() else None

    real_table = format_real_llm_table(real_data)
    synth_table = format_synthetic_table(synth_data)

    readme = readme_path.read_text(encoding="utf-8")
    readme = replace_table(
        readme,
        "<!-- BENCHMARK_TABLE_REAL_START -->",
        "<!-- BENCHMARK_TABLE_REAL_END -->",
        real_table,
    )
    readme = replace_table(
        readme,
        "<!-- BENCHMARK_TABLE_SYNTHETIC_START -->",
        "<!-- BENCHMARK_TABLE_SYNTHETIC_END -->",
        synth_table,
    )
    readme = replace_table(
        readme,
        "<!-- BENCHMARK_TABLE_AGG_START -->",
        "<!-- BENCHMARK_TABLE_AGG_END -->",
        format_aggregate_table(aggregate_data),
    )
    readme = replace_table(
        readme,
        "<!-- SMOKE_BLOCK_START -->",
        "<!-- SMOKE_BLOCK_END -->",
        format_smoke_block(smoke_data),
    )
    readme = update_test_count_mentions(readme, test_count)
    readme_path.write_text(readme, encoding="utf-8")

    if portfolio_path.exists():
        portfolio = portfolio_path.read_text(encoding="utf-8")
        portfolio_table = format_portfolio_table(real_data, synth_data, smoke_data, test_count)
        portfolio = replace_table(
            portfolio,
            "<!-- BENCHMARK_TABLE_PORTFOLIO_START -->",
            "<!-- BENCHMARK_TABLE_PORTFOLIO_END -->",
            portfolio_table,
        )
        portfolio_path.write_text(portfolio, encoding="utf-8")

    print(f"Regenerated benchmark tables (tests: {test_count}).")


if __name__ == "__main__":
    main()
