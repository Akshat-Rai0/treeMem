"""Smoke test runner measuring basic descent plumbing on 5 sample questions with scripted descent."""

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager

# Fictional sample persona questions with varying target descent depths
SMOKE_DATASET = [
    {
        "id": "q1",
        "question": "What is my full name?",
        "expected_answer": "Alex Mercer",
        "target_path": "identity",
        "depth_needed": 0,  # Answered directly by root summary
    },
    {
        "id": "q2",
        "question": "What degree program am I enrolled in?",
        "expected_answer": "B.S. in Computer Science",
        "target_path": "education/degree",
        "depth_needed": 1,  # Answered by education summary
    },
    {
        "id": "q3",
        "question": "What is my current age?",
        "expected_answer": "28",
        "target_path": "identity/age",
        "depth_needed": 2,  # Leaf fact
    },
    {
        "id": "q4",
        "question": "What is the repo URL for the TreeMem project?",
        "expected_answer": "github.com/example/treemem",
        "target_path": "projects/treemem",
        "depth_needed": 2,
    },
    {
        "id": "q5",
        "question": "Which gym do I train at?",
        "expected_answer": "Apex Fitness",
        "target_path": "hobbies/fitness",
        "depth_needed": 2,
    },
]


def setup_smoke_vault(vault_path: Path) -> TreeManager:
    mgr = TreeManager(vault_path)

    facts = [
        ("User full name is Alex Mercer", "identity"),
        ("User age is 28", "identity/age"),
        ("User lives in Metropolis", "identity/location"),
        ("Enrolled in B.S. in Computer Science", "education/degree"),
        ("GPA is 3.85", "education/grades"),
        ("Building TreeMem at github.com/example/treemem", "projects/treemem"),
        ("Trains at Apex Fitness", "hobbies/fitness"),
        ("Favorite programming language is Python", "skills/languages"),
    ]

    for fact, hint in facts:
        rem = mgr.remember(fact=fact, hint=hint, session="smoke")
        mgr.place(rem["entry_id"], hint)

    # Set up realistic root and parent summaries
    mgr.commit_summary(
        "",
        "---\nname: root\ndirty: false\n---\nPersonal catalog for Alex Mercer, 28-year-old software engineer.\n\n"
        "## Children\n- [[identity]] - Personal bio\n- [[education]] - Academic background\n"
        "- [[projects]] - Software projects\n- [[hobbies]] - Personal fitness\n- [[skills]] - Technical skills\n"
    )

    mgr.commit_summary(
        "education",
        "---\nname: education\ndirty: false\n---\nEnrolled in B.S. in Computer Science with a 3.85 GPA.\n\n"
        "## Children\n- [[degree]] - degree info\n- [[grades]] - academic grades\n"
    )

    return mgr


def run_smoke_test():
    temp_dir = tempfile.mkdtemp(prefix="treemem_smoke_")
    vault_path = Path(temp_dir)
    try:
        mgr = setup_smoke_vault(vault_path)

        latencies = []
        tokens_tree = []
        parent_stops = 0
        correct_stops = 0
        correct_answers = 0

        flat_text = ""
        for p in mgr.health_checker.get_all_node_paths():
            n = mgr.store.read_node(p)
            if n:
                for f in n.facts:
                    flat_text += f["fact"] + "\n"
        flat_tokens_per_query = count_tokens(flat_text)

        eval_records = []

        for item in SMOKE_DATASET:
            t0 = time.time()
            query_id = item["id"]
            depth_needed = item["depth_needed"]

            # Simulated Agent Descent Logic (Scripted plumbing check)
            # 1. Start with root recall
            r_root = mgr.recall("/", query_id=query_id)
            tokens_read = r_root["tokens"]
            stopped_at = "/"

            if depth_needed == 0:
                parent_stops += 1
                if item["expected_answer"].lower() in r_root["summary"].lower():
                    correct_stops += 1
                    correct_answers += 1
            else:
                # Descend to first level
                top_part = item["target_path"].split("/")[0]
                r_top = mgr.recall(top_part, query_id=query_id)
                tokens_read += r_top["tokens"]
                stopped_at = top_part

                if depth_needed == 1:
                    if item["expected_answer"].lower() in r_top["summary"].lower():
                        correct_answers += 1
                else:
                    # Expand leaf
                    r_leaf = mgr.expand(item["target_path"], query_id=query_id)
                    tokens_read += r_leaf["tokens"]
                    stopped_at = item["target_path"]
                    facts_str = " ".join(f["fact"] for f in r_leaf.get("facts", []))
                    if item["expected_answer"].lower() in facts_str.lower():
                        correct_answers += 1

            latency_ms = round((time.time() - t0) * 1000, 2)
            latencies.append(latency_ms)
            tokens_tree.append(tokens_read)

            eval_records.append({
                "query_id": query_id,
                "question": item["question"],
                "depth_needed": depth_needed,
                "stopped_at": stopped_at,
                "tokens_tree": tokens_read,
                "tokens_flat": flat_tokens_per_query,
                "latency_ms": latency_ms,
            })

        latencies.sort()
        p50_latency = latencies[len(latencies) // 2]
        p95_latency = latencies[int(len(latencies) * 0.95)]

        summary = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "test_type": "smoke_test_scripted_descent",
            "total_questions": len(SMOKE_DATASET),
            "accuracy_pct": round((correct_answers / len(SMOKE_DATASET)) * 100, 1),
            "parent_stop_rate": round(parent_stops / len(SMOKE_DATASET), 3),
            "parent_stop_correctness": round(correct_stops / max(1, parent_stops), 3),
            "avg_tokens_tree": round(sum(tokens_tree) / len(tokens_tree), 1),
            "avg_tokens_flat": flat_tokens_per_query,
            "token_reduction_pct": round((1 - (sum(tokens_tree) / (flat_tokens_per_query * len(tokens_tree)))) * 100, 1),
            "latency_p50_ms": p50_latency,
            "latency_p95_ms": p95_latency,
            "records": eval_records,
        }

        out_file = Path(__file__).parent / "results" / "smoke_test_results.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w") as f:
            json.dump(summary, f, indent=2)

        print("\nSmoke Test (Scripted Descent, n=5) Results:")
        print(f" Accuracy: {summary['accuracy_pct']}%")
        print(f" Parent-stop rate: {summary['parent_stop_rate'] * 100}%")
        print(f" Average tokens per recall: {summary['avg_tokens_tree']} (vs flat dump {summary['avg_tokens_flat']} tok, {summary['token_reduction_pct']}% reduction)")
        print(f" Latency: p50 = {summary['latency_p50_ms']} ms | p95 = {summary['latency_p95_ms']} ms")
        print(f" Committed results to: {out_file}")

        return summary
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_smoke_test()
