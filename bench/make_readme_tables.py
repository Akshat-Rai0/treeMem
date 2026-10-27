#!/usr/bin/env python3
"""Regenerate benchmark markdown tables in README.md from committed JSON results.

Ensures that numbers reported in documentation cannot drift from raw benchmark data.
"""

import json
from pathlib import Path
from typing import Dict, Any, List


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_real_llm_table(data: Dict[str, Any]) -> str:
    flat_acc = data["flat_accuracy_pct"]
    tree_acc = data["treemem_accuracy_pct"]
    total_q = data["total_questions"]
    
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

    lines = [
        "| Metric | Flat Memory Dump | TreeMem Autonomous Descent | Impact |",
        "|:---|:---|:---|:---|",
        f"| **Answer Accuracy** | **{flat_acc:.1f}%** ({int(flat_acc * total_q / 100)}/{total_q}) | **{tree_acc:.1f}%** ({int(tree_acc * total_q / 100)}/{total_q}) | Parity across benchmark suite |",
        f"| **Memory Payload Tokens** | {flat_payload:,} tokens | **{tree_payload:,} tokens** | **{payload_red:.2f}% payload token reduction** |",
        f"| **Total API Wire Tokens** | **{flat_wire:,} tokens** | {tree_wire:,} tokens | Multi-turn tool calling re-sends schema/prompts per hop |",
        f"| **Parent-Stop Rate** | N/A | **{ps_rate:.1f}%** ({ps_count}/{total_q}) | Evaluated at root depth 0 when summary was sufficient |",
        f"| **Mean / Max Latency** | {mean_flat_lat:.2f}s / {max_flat_lat:.2f}s | {mean_tree_lat:.2f}s / {max_tree_lat:.2f}s | Multi-hop sequential tool execution latency |",
    ]
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


def replace_table(content: str, start_tag: str, end_tag: str, new_table: str) -> str:
    if start_tag not in content or end_tag not in content:
        raise ValueError(f"Marker tags {start_tag} / {end_tag} not found in target text.")
    before = content.split(start_tag)[0] + start_tag + "\n"
    after = "\n" + end_tag + content.split(end_tag)[1]
    return before + new_table + after


def main():
    repo_root = Path(__file__).resolve().parent.parent
    readme_path = repo_root / "README.md"
    real_results_path = repo_root / "bench" / "results" / "llm_eval_results.json"
    synth_results_path = repo_root / "bench" / "results" / "flat_vs_tree_tokens.json"

    if not readme_path.exists():
        print(f"Error: {readme_path} not found.")
        return

    real_data = load_json(real_results_path)
    synth_data = load_json(synth_results_path)

    real_table = format_real_llm_table(real_data)
    synth_table = format_synthetic_table(synth_data)

    content = readme_path.read_text(encoding="utf-8")

    content = replace_table(
        content,
        "<!-- BENCHMARK_TABLE_REAL_START -->",
        "<!-- BENCHMARK_TABLE_REAL_END -->",
        real_table,
    )
    content = replace_table(
        content,
        "<!-- BENCHMARK_TABLE_SYNTHETIC_START -->",
        "<!-- BENCHMARK_TABLE_SYNTHETIC_END -->",
        synth_table,
    )

    readme_path.write_text(content, encoding="utf-8")
    print(f"Successfully regenerated benchmark tables in {readme_path}")


if __name__ == "__main__":
    main()
