#!/usr/bin/env python3
"""Resumable scaling evaluation runner for TreeMem.

Loops through sizes (50, 200, 1000, 5000), arms (flat, tree_follow, rag_bm25, rag_bm25_k10),
runs (1-5), and questions (1-50). Appends results to progress.jsonl for resumability.

Arms:
- flat: whole log in the prompt
- tree_follow: guided descent via recall(follow=true)
- rag_bm25: BM25 top-5 over log entries
- rag_bm25_k10: BM25 top-10 over log entries (new)

Model: qwen/qwen3.8-27b (Groq).

Usage:
    python bench/run_scaling.py                    # Full run (starts with smoke test)
    python bench/run_scaling.py --smoke-only       # Smoke test only
    python bench/run_scaling.py --size 200         # Run specific size only
"""

import argparse
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from treemem.tree_manager import TreeManager
from treemem.tokenizer import count_tokens

# Import grading functions from eval harness
sys.path.insert(0, str(Path(__file__).parent / "eval"))
from run_eval import (
    GroqKeyPool,
    grade_answer,
    grade_question,
    normalize_text,
    RequestTooLarge,
    is_request_too_large,
    NEGATIVE_KEYWORDS,
    RAG_SYSTEM_PROMPT,
    _pace,
    timed_chat,
)

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b"
SIZES = [50, 200, 1000, 5000]
ARMS = ["flat", "tree_follow", "rag_bm25", "rag_bm25_k10"]
RUNS = 5
QUESTIONS_PER_RUN = 50

RESULT_DIR = Path(__file__).parent.parent / "bench" / "results_scaling"
PROGRESS_FILE = RESULT_DIR / "progress.jsonl"


def load_groq_keys() -> List[str]:
    """Load Groq API keys from .env file."""
    keys = []
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    if k.strip().startswith("GROQ_API_KEY"):
                        cleaned = v.strip().strip("\"'")
                        if cleaned:
                            keys.append(cleaned)
    return keys


def get_model_context_window(model: str) -> Optional[int]:
    """Try to read context window from Groq models endpoint."""
    try:
        headers = {"Authorization": f"Bearer {load_groq_keys()[0]}"}
        resp = httpx.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=10.0)
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            for m in models:
                if m.get("id") == model:
                    return m.get("context_window")
    except Exception:
        pass
    return None


def parse_context_from_error(error_text: str) -> Optional[int]:
    """Try to parse context limit from error message."""
    # Common patterns: "context length of XXX exceeds limit of YYY", "maximum context length is YYY"
    patterns = [
        r"limit of (\d+)",
        r"maximum context length is (\d+)",
        r"context length.*?(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, error_text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


def load_questions(vault_dir: Path) -> List[Dict[str, Any]]:
    """Load questions from vault_questions.json."""
    questions_file = vault_dir.parent / f"{vault_dir.name}_questions.json"
    if not questions_file.exists():
        raise FileNotFoundError(f"Questions file not found: {questions_file}")
    
    with open(questions_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_manifest(vault_dir: Path) -> Dict[str, Any]:
    """Load manifest from vault_manifest.json."""
    manifest_file = vault_dir.parent / f"{vault_dir.name}_manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_file}")
    
    with open(manifest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def run_flat_arm(
    client: GroqKeyPool,
    model: str,
    vault_path: Path,
    question: str,
    question_id: str,
) -> Dict[str, Any]:
    """Arm: dump the whole memory log into context in one shot."""
    log_files = sorted((vault_path / "log").glob("*.md"))
    log_text = ""
    for log_file in log_files:
        log_text += log_file.read_text(encoding="utf-8") + "\n"
    
    flat_payload_tokens = count_tokens(log_text)
    
    system_prompt = (
        "You are an assistant answering questions from the user's personal memory log.\n"
        "Answer factually, accurately, and concisely based strictly on the memory notes.\n\n"
        f"<MEMORY_VAULT>\n{log_text.strip()}\n</MEMORY_VAULT>"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "temperature": 0.0,
        "max_tokens": 150,
    }
    
    try:
        resp, api_seconds = timed_chat(client, payload)
        usage = resp.get("usage", {})
        answer = resp["choices"][0]["message"]["content"].strip()
        _pace(1.0)
        
        return {
            "answer": answer,
            "payload_tokens": flat_payload_tokens,
            "api_prompt_tokens": usage.get("prompt_tokens", 0),
            "api_completion_tokens": usage.get("completion_tokens", 0),
            "api_total_tokens": usage.get("total_tokens", 0),
            "latency_sec": round(api_seconds, 3),
            "model_calls": 1,
            "tool_calls": 0,
            "outcome": "ok",
        }
    except RequestTooLarge as e:
        # Record would-be prompt token count
        return {
            "answer": "",
            "payload_tokens": 0,
            "attempted_payload_tokens": flat_payload_tokens,
            "api_prompt_tokens": 0,
            "api_completion_tokens": 0,
            "api_total_tokens": 0,
            "latency_sec": 0.0,
            "model_calls": 0,
            "tool_calls": 0,
            "outcome": "context_exceeded",
            "error": str(e),
        }
    except Exception as e:
        if is_request_too_large(None, str(e)):
            return {
                "answer": "",
                "payload_tokens": 0,
                "attempted_payload_tokens": flat_payload_tokens,
                "api_prompt_tokens": 0,
                "api_completion_tokens": 0,
                "api_total_tokens": 0,
                "latency_sec": 0.0,
                "model_calls": 0,
                "tool_calls": 0,
                "outcome": "context_exceeded",
                "error": str(e),
            }
        return {
            "answer": "",
            "payload_tokens": 0,
            "api_prompt_tokens": 0,
            "api_completion_tokens": 0,
            "api_total_tokens": 0,
            "latency_sec": 0.0,
            "model_calls": 0,
            "tool_calls": 0,
            "outcome": "api_error",
            "error": str(e),
        }


def run_rag_arm(
    client: GroqKeyPool,
    model: str,
    mgr: TreeManager,
    question: str,
    question_id: str,
    limit: int = 5,
) -> Dict[str, Any]:
    """Retrieval baseline (BM25 top-k, no tools)."""
    search_res = mgr.search(question, limit=limit, reveal=False)
    hits = search_res.get("hits", [])
    hits_json = json.dumps(hits, indent=2)
    payload_tokens = count_tokens(hits_json)
    
    system_prompt = RAG_SYSTEM_PROMPT.format(hits_json=hits_json)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "temperature": 0.0,
        "max_tokens": 150,
    }
    
    try:
        resp, api_seconds = timed_chat(client, payload)
        usage = resp.get("usage", {})
        answer = resp["choices"][0]["message"]["content"].strip()
        _pace(1.0)
        
        return {
            "answer": answer,
            "payload_tokens": payload_tokens,
            "api_prompt_tokens": usage.get("prompt_tokens", 0),
            "api_completion_tokens": usage.get("completion_tokens", 0),
            "api_total_tokens": usage.get("total_tokens", 0),
            "latency_sec": round(api_seconds, 3),
            "model_calls": 1,
            "tool_calls": 0,
            "outcome": "ok",
        }
    except RequestTooLarge as e:
        return {
            "answer": "",
            "payload_tokens": 0,
            "attempted_payload_tokens": payload_tokens,
            "api_prompt_tokens": 0,
            "api_completion_tokens": 0,
            "api_total_tokens": 0,
            "latency_sec": 0.0,
            "model_calls": 0,
            "tool_calls": 0,
            "outcome": "context_exceeded",
            "error": str(e),
        }
    except Exception as e:
        if is_request_too_large(None, str(e)):
            return {
                "answer": "",
                "payload_tokens": 0,
                "attempted_payload_tokens": payload_tokens,
                "api_prompt_tokens": 0,
                "api_completion_tokens": 0,
                "api_total_tokens": 0,
                "latency_sec": 0.0,
                "model_calls": 0,
                "tool_calls": 0,
                "outcome": "context_exceeded",
                "error": str(e),
            }
        return {
            "answer": "",
            "payload_tokens": 0,
            "api_prompt_tokens": 0,
            "api_completion_tokens": 0,
            "api_total_tokens": 0,
            "latency_sec": 0.0,
            "model_calls": 0,
            "tool_calls": 0,
            "outcome": "api_error",
            "error": str(e),
        }


def run_tree_follow_arm(
    client: GroqKeyPool,
    model: str,
    mgr: TreeManager,
    question: str,
    question_id: str,
) -> Dict[str, Any]:
    """Arm: guided descent via recall(follow=true)."""
    # Call recall with follow=true
    recall_result = mgr.recall(path="/", query=question, follow=True, max_depth=3, reveal=False)
    
    # Build system prompt with recall result
    recall_text = json.dumps(recall_result, indent=2)
    system_prompt = (
        "You are an assistant answering questions from the user's hierarchical memory.\n"
        "The server has performed a guided descent and returned the following result:\n\n"
        f"<RECALL_RESULT>\n{recall_text}\n</RECALL_RESULT>\n\n"
        "Answer factually based on this result. If the answer is not present, say so clearly."
    )
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "temperature": 0.0,
        "max_tokens": 150,
    }
    
    try:
        resp, api_seconds = timed_chat(client, payload)
        usage = resp.get("usage", {})
        answer = resp["choices"][0]["message"]["content"].strip()
        _pace(1.0)
        
        return {
            "answer": answer,
            "payload_tokens": count_tokens(recall_text),
            "api_prompt_tokens": usage.get("prompt_tokens", 0),
            "api_completion_tokens": usage.get("completion_tokens", 0),
            "api_total_tokens": usage.get("total_tokens", 0),
            "latency_sec": round(api_seconds, 3),
            "model_calls": 1,
            "tool_calls": 0,
            "outcome": "ok",
        }
    except RequestTooLarge as e:
        return {
            "answer": "",
            "payload_tokens": 0,
            "api_prompt_tokens": 0,
            "api_completion_tokens": 0,
            "api_total_tokens": 0,
            "latency_sec": 0.0,
            "model_calls": 0,
            "tool_calls": 0,
            "outcome": "context_exceeded",
            "error": str(e),
        }
    except Exception as e:
        if is_request_too_large(None, str(e)):
            return {
                "answer": "",
                "payload_tokens": 0,
                "api_prompt_tokens": 0,
                "api_completion_tokens": 0,
                "api_total_tokens": 0,
                "latency_sec": 0.0,
                "model_calls": 0,
                "tool_calls": 0,
                "outcome": "context_exceeded",
                "error": str(e),
            }
        return {
            "answer": "",
            "payload_tokens": 0,
            "api_prompt_tokens": 0,
            "api_completion_tokens": 0,
            "api_total_tokens": 0,
            "latency_sec": 0.0,
            "model_calls": 0,
            "tool_calls": 0,
            "outcome": "api_error",
            "error": str(e),
        }


def run_episode(
    client: GroqKeyPool,
    model: str,
    vault_path: Path,
    question: Dict[str, Any],
    arm: str,
    run_num: int,
    size: int,
) -> Dict[str, Any]:
    """Run a single episode (one question with one arm)."""
    question_id = question["id"]
    question_text = question["question"]
    
    # Make a temporary copy of the vault for this run
    with tempfile.TemporaryDirectory() as tmp:
        vault_copy = Path(tmp) / "vault"
        shutil.copytree(vault_path, vault_copy)
        mgr = TreeManager(vault_copy)
        
        if arm == "flat":
            result = run_flat_arm(client, model, vault_copy, question_text, question_id)
        elif arm == "tree_follow":
            result = run_tree_follow_arm(client, model, mgr, question_text, question_id)
        elif arm == "rag_bm25":
            result = run_rag_arm(client, model, mgr, question_text, question_id, limit=5)
        elif arm == "rag_bm25_k10":
            result = run_rag_arm(client, model, mgr, question_text, question_id, limit=10)
        else:
            raise ValueError(f"Unknown arm: {arm}")
    
    # Grade the answer
    grade = grade_question(question, result["answer"])
    
    # Add metadata
    result["size"] = size
    result["arm"] = arm
    result["run"] = run_num
    result["question_id"] = question_id
    result["correct"] = grade["correct"]
    result["leaked_private"] = grade["leaked"]
    
    # Determine question type
    if question.get("private"):
        result["question_type"] = "private"
        result["refused_correctly"] = not grade["leaked"]
    elif question.get("negative"):
        result["question_type"] = "unanswerable"
        result["refused_correctly"] = grade["correct"]
    elif question.get("require_all"):
        result["question_type"] = "overview"
        result["complete"] = grade["correct"]  # Overview completeness
    else:
        result["question_type"] = "lookup"
        result["complete"] = None
    
    return result


def load_progress() -> Dict[str, Dict[str, Any]]:
    """Load progress from progress.jsonl."""
    progress = {}
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    key = f"{entry['size']}_{entry['arm']}_{entry['run']}_{entry['question_id']}"
                    progress[key] = entry
    return progress


def save_progress(entry: Dict[str, Any]) -> None:
    """Append a single entry to progress.jsonl."""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()


def run_scaling(
    sizes: List[int] = None,
    arms: List[str] = None,
    runs: int = RUNS,
    model: str = DEFAULT_MODEL,
    smoke_only: bool = False,
) -> None:
    """Main scaling runner."""
    if sizes is None:
        sizes = SIZES
    if arms is None:
        arms = ARMS
    
    # Load Groq keys
    keys = load_groq_keys()
    if not keys:
        print("ERROR: No Groq API keys found in .env file")
        print("Please set GROQ_API_KEY_1 or GROQ_API_KEY in .env")
        sys.exit(1)
    
    client = GroqKeyPool(keys)
    
    # Load existing progress
    progress = load_progress()
    
    # Smoke test first
    print("\n=== SMOKE TEST ===")
    smoke_size = 50
    smoke_questions = 3
    smoke_run = 1
    smoke_arms = arms
    
    vault_dir = Path(__file__).parent.parent / "bench" / "vaults" / f"scaled_{smoke_size}"
    if not vault_dir.exists():
        print(f"ERROR: Vault directory not found: {vault_dir}")
        print("Run bench/make_scaled_vault.py first to generate vaults")
        sys.exit(1)
    
    questions = load_questions(vault_dir)[:smoke_questions]
    
    smoke_results = []
    for arm in smoke_arms:
        for q in questions:
            key = f"{smoke_size}_{arm}_{smoke_run}_{q['id']}"
            if key in progress:
                print(f"  SKIP: {key} (already done)")
                continue
            
            print(f"  Running: {key}")
            result = run_episode(client, model, vault_dir, q, arm, smoke_run, smoke_size)
            save_progress(result)
            smoke_results.append(result)
            progress[key] = result
    
    # Calculate projected time and tokens
    if smoke_results:
        avg_latency = sum(r["latency_sec"] for r in smoke_results) / len(smoke_results)
        avg_tokens = sum(r["api_total_tokens"] for r in smoke_results) / len(smoke_results)
        
        total_episodes = len(sizes) * len(arms) * runs * QUESTIONS_PER_RUN
        projected_time_sec = avg_latency * total_episodes
        projected_time_hours = projected_time_sec / 3600
        projected_tokens = avg_tokens * total_episodes
        
        print(f"\n=== PROJECTION ===")
        print(f"  Total episodes: {total_episodes}")
        print(f"  Projected time: {projected_time_hours:.1f} hours")
        print(f"  Projected tokens: {projected_tokens:,.0f}")
        
        # Write to experiments_plan.md
        plan_file = Path(__file__).parent.parent / "docs" / "experiments_plan.md"
        if plan_file.exists():
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_content = f.read()
            
            projection_section = f"\n## Time Projection\n\nBased on smoke test:\n- Total episodes: {total_episodes}\n- Projected time: {projected_time_hours:.1f} hours\n- Projected tokens: {projected_tokens:,.0f}\n"
            
            if "## Time Projection" not in plan_content:
                plan_content += projection_section
                with open(plan_file, "w", encoding="utf-8") as f:
                    f.write(plan_content)
                print(f"  Added projection to {plan_file}")
    
    if smoke_only:
        print("\n=== SMOKE TEST COMPLETE ===")
        return
    
    print("\n=== FULL RUN ===")
    
    # Full run
    for size in sizes:
        print(f"\n=== SIZE {size} ===")
        vault_dir = Path(__file__).parent.parent / "bench" / "vaults" / f"scaled_{size}"
        if not vault_dir.exists():
            print(f"ERROR: Vault directory not found: {vault_dir}")
            continue
        
        questions = load_questions(vault_dir)
        
        for arm in arms:
            print(f"  Arm: {arm}")
            for run_num in range(1, runs + 1):
                print(f"    Run {run_num}/{runs}")
                for q in questions:
                    key = f"{size}_{arm}_{run_num}_{q['id']}"
                    if key in progress:
                        continue
                    
                    result = run_episode(client, model, vault_dir, q, arm, run_num, size)
                    save_progress(result)
                    progress[key] = result
        
        # Commit after each size
        print(f"  Size {size} complete, committing...")
        os.system(f"git add {RESULT_DIR} && git commit -m '[WP2] Add results for size {size}'")


def main():
    parser = argparse.ArgumentParser(description="Resumable scaling evaluation runner")
    parser.add_argument("--size", type=int, help="Run specific size only")
    parser.add_argument("--arm", type=str, help="Run specific arm only")
    parser.add_argument("--runs", type=int, default=RUNS, help="Number of runs per arm")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--smoke-only", action="store_true", help="Run smoke test only")
    args = parser.parse_args()
    
    sizes = [args.size] if args.size else None
    arms = [args.arm] if args.arm else None
    
    run_scaling(sizes=sizes, arms=arms, runs=args.runs, model=args.model, smoke_only=args.smoke_only)


if __name__ == "__main__":
    main()
