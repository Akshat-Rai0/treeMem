"""Scaling benchmark comparing token cost of flat dump vs TreeMem hierarchical recall (synthetic vault, scripted descent, tokens only)."""

import json
import random
import shutil
import tempfile
import time
from pathlib import Path

from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager


def generate_benchmark_vault(num_memories: int, base_dir: Path) -> TreeManager:
    """Generate a synthetic memory vault with a fixed seed."""
    random.seed(42)
    mgr = TreeManager(base_dir)

    topics = [
        "identity", "career", "education", "hobbies", "projects",
        "finance", "travel", "health", "preferences", "reading"
    ]
    subtopics = ["general", "history", "current", "goals", "notes"]

    for i in range(num_memories):
        top = topics[i % len(topics)]
        sub = subtopics[(i // len(topics)) % len(subtopics)]
        path = f"{top}/{sub}"
        fact = f"Fact {i}: The user recorded detailed event {i} about {top} {sub} with unique metric {i * 17}."
        rem = mgr.remember(fact=fact, hint=path, session="bench")
        mgr.place(rem["entry_id"], path)

    # Compress top-level nodes with realistic summaries
    for top in topics:
        sub_list = [f"- [[{sub}]] - summary of {top} {sub}" for sub in subtopics]
        summary_text = (
            f"---\nname: {top}\ndirty: false\n---\n"
            f"Synthesized overview of all topics and activities related to {top}.\n\n"
            f"## Children\n" + "\n".join(sub_list) + "\n"
        )
        try:
            mgr.commit_summary(top, summary_text)
        except Exception:
            pass

    return mgr


def run_benchmark():
    scales = [100, 1000, 10000]
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark": "flat_vs_tree_tokens_synthetic",
        "benchmark_type": "synthetic vault, scripted descent, tokens only",
        "scales": {},
    }

    print("Running Scaling Benchmark (synthetic vault, scripted descent, tokens only)...")

    for scale in scales:
        temp_dir = tempfile.mkdtemp(prefix=f"treemem_bench_{scale}_")
        vault_path = Path(temp_dir)
        try:
            t0 = time.time()
            mgr = generate_benchmark_vault(scale, vault_path)
            build_time = time.time() - t0

            # Measure Flat Dump Tokens (concatenation of all raw leaf facts)
            all_paths = mgr.health_checker.get_all_node_paths()
            flat_text = ""
            for p in all_paths:
                node = mgr.store.read_node(p)
                if node:
                    for f in node.facts:
                        flat_text += f["fact"] + "\n"
            flat_tokens = count_tokens(flat_text)

            # Measure TreeMem Recalls
            # 1. Depth 0 Parent-stop recall
            root_rec = mgr.recall("/")
            parent_stop_tokens = root_rec["tokens"]

            # 2. Depth 1 topic recall
            topic_rec = mgr.recall("career")
            depth1_tokens = parent_stop_tokens + topic_rec["tokens"]

            # 3. Depth 2 leaf expansion (descent to raw fact)
            leaf_exp = mgr.expand("career/current")
            depth2_tokens = depth1_tokens + leaf_exp["tokens"]

            # Average simulated descent cost (30% parent stops, 40% depth 1, 30% depth 2)
            avg_tree_tokens = int(0.3 * parent_stop_tokens + 0.4 * depth1_tokens + 0.3 * depth2_tokens)
            token_savings_pct = round((1 - (avg_tree_tokens / max(1, flat_tokens))) * 100, 2)

            results["scales"][str(scale)] = {
                "num_memories": scale,
                "flat_dump_tokens": flat_tokens,
                "parent_stop_tokens": parent_stop_tokens,
                "tree_depth1_tokens": depth1_tokens,
                "tree_depth2_tokens": depth2_tokens,
                "avg_tree_recall_tokens": avg_tree_tokens,
                "token_savings_pct": token_savings_pct,
                "build_time_seconds": round(build_time, 2),
            }

            print(f" Scale {scale:>5} memories: Flat Dump = {flat_tokens:>6} tok | Tree Avg = {avg_tree_tokens:>3} tok | Savings = {token_savings_pct}%")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    out_file = Path(__file__).parent / "results" / "flat_vs_tree_tokens.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nRaw benchmark results committed to: {out_file}")
    return results


if __name__ == "__main__":
    run_benchmark()
