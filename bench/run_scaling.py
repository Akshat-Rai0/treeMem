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
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from treemem.tree_manager import TreeManager
from treemem.tokenizer import count_tokens

sys.path.insert(0, str(Path(__file__).parent))
from make_scaled_vault import (  # noqa: E402
    GENERATOR_VERSION,
    file_sha256,
    log_sha256,
    manifest_path,
    questions_path,
)

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
INVALIDATED_FILE = RESULT_DIR / "invalidated.jsonl"
VAULT_ROOT = Path(__file__).parent / "vaults"
PLAN_FILE = Path(__file__).parent.parent / "docs" / "experiments_plan.md"

# An episode is final only when it produced a gradable result. Transient failures
# (rate limits, network errors) are retried on the next resume instead of being
# frozen into the data as wrong answers.
DONE_OUTCOMES = {"ok", "context_exceeded"}


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
    vault_copy: Path,
    mgr: TreeManager,
    question: Dict[str, Any],
    arm: str,
    run_num: int,
    size: int,
    fingerprint: Dict[str, str],
) -> Dict[str, Any]:
    """Run a single episode (one question with one arm) on a prepared vault copy."""
    question_id = question["id"]
    question_text = question["question"]

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
    
    # Add metadata (the hashes make it impossible to mix episodes from different question sets)
    result.update(fingerprint)
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


def vault_fingerprint(size: int) -> Dict[str, str]:
    """Hashes of the questions file and the log for scaled_<size>, computed from the files."""
    vault_dir = VAULT_ROOT / f"scaled_{size}"
    qfile = questions_path(vault_dir)
    if not vault_dir.exists() or not qfile.exists():
        raise FileNotFoundError(
            f"Vault or questions missing for size {size}. Run: python bench/make_scaled_vault.py --all"
        )
    return {
        "generator": GENERATOR_VERSION,
        "questions_sha": file_sha256(qfile),
        "vault_sha": log_sha256(vault_dir),
    }


def find_stale_rows(sizes: List[int]) -> List[Dict[str, Any]]:
    """Rows in progress.jsonl whose question/vault hashes differ from the current files."""
    if not PROGRESS_FILE.exists():
        return []
    current = {size: vault_fingerprint(size) for size in sizes}
    stale = []
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            size = row.get("size")
            if size not in current:
                continue
            fp = current[size]
            if (row.get("questions_sha"), row.get("vault_sha")) != (fp["questions_sha"], fp["vault_sha"]):
                stale.append(row)
    return stale


def invalidate_rows(stale: List[Dict[str, Any]], reason: str) -> None:
    """Move stale rows out of progress.jsonl into invalidated.jsonl (never deleted)."""
    stale_keys = {(r["size"], r["arm"], r["run"], r["question_id"], r.get("questions_sha")) for r in stale}
    kept: List[str] = []
    moved: List[str] = []
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (row["size"], row["arm"], row["run"], row["question_id"], row.get("questions_sha"))
            if key in stale_keys:
                row["invalidation_reason"] = reason
                moved.append(json.dumps(row))
            else:
                kept.append(line.rstrip("\n"))
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    with open(INVALIDATED_FILE, "a", encoding="utf-8") as f:
        for line in moved:
            f.write(line + "\n")
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")
    print(f"Moved {len(moved)} stale rows to {INVALIDATED_FILE.name}; {len(kept)} rows kept.")


def guard_against_stale_results(sizes: List[int], invalidate: bool) -> None:
    stale = find_stale_rows(sizes)
    if not stale:
        return
    by_size: Dict[int, int] = {}
    for row in stale:
        by_size[row["size"]] = by_size.get(row["size"], 0) + 1
    print("ERROR: progress.jsonl contains episodes produced with a different question set or vault")
    print(f"       (or without hashes): {by_size}")
    if not invalidate:
        print("       Refusing to resume. Re-run with --invalidate-stale to move them to invalidated.jsonl.")
        sys.exit(2)
    invalidate_rows(stale, "stale: questions/vault hash differs from current files")


def load_progress() -> Dict[str, Dict[str, Any]]:
    """Load progress from progress.jsonl."""
    progress = {}
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("outcome") not in DONE_OUTCOMES:
                        continue  # transient failure: retry on resume
                    key = f"{entry['size']}_{entry['arm']}_{entry['run']}_{entry['question_id']}"
                    progress[key] = entry
    return progress


def save_progress(entry: Dict[str, Any]) -> None:
    """Append a single entry to progress.jsonl."""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()


class PreparedVault:
    """A private copy of one vault plus a TreeManager over it, reused for a whole (size, run)."""

    def __init__(self, vault_dir: Path):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "vault"
        shutil.copytree(vault_dir, self.path)
        self.mgr = TreeManager(self.path)

    def close(self) -> None:
        self._tmp.cleanup()


def run_scaling(
    sizes: List[int] = None,
    arms: List[str] = None,
    runs: int = RUNS,
    model: str = DEFAULT_MODEL,
    smoke_only: bool = False,
    invalidate_stale: bool = False,
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

    # Refuse to mix episodes produced with a different question set or vault.
    guard_against_stale_results(sorted(set(sizes) | {50}), invalidate_stale)

    # Load existing progress
    progress = load_progress()
    
    # Smoke test first
    print("\n=== SMOKE TEST ===")
    smoke_size = 50
    smoke_questions = 3
    smoke_run = 1
    smoke_arms = arms
    
    vault_dir = VAULT_ROOT / f"scaled_{smoke_size}"
    if not vault_dir.exists():
        print(f"ERROR: Vault directory not found: {vault_dir}")
        print("Run bench/make_scaled_vault.py first to generate vaults")
        sys.exit(1)
    
    questions = load_questions(vault_dir)[:smoke_questions]
    
    smoke_results = []
    smoke_fp = vault_fingerprint(smoke_size)
    for arm in smoke_arms:
        prepared = None
        try:
            for q in questions:
                key = f"{smoke_size}_{arm}_{smoke_run}_{q['id']}"
                if key in progress:
                    print(f"  SKIP: {key} (already done)")
                    continue
                if prepared is None:
                    prepared = PreparedVault(vault_dir)
                print(f"  Running: {key}")
                result = run_episode(client, model, prepared.path, prepared.mgr, q, arm, smoke_run, smoke_size, smoke_fp)
                save_progress(result)
                if result["outcome"] in DONE_OUTCOMES:
                    progress[key] = result
                smoke_results.append(result)
        finally:
            if prepared is not None:
                prepared.close()

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
        print(f"  Projected time: at least {projected_time_hours:.1f} hours (lower bound: ignores rate-limit waits and retries)")
        print(f"  Projected tokens: {projected_tokens:,.0f}")
        
        # Write to experiments_plan.md
        plan_file = PLAN_FILE
        if plan_file.exists():
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_content = f.read()
            
            projection_section = f"\n## Time Projection\n\nBased on smoke test (lower bound, ignores rate-limit waits and retries):\n- Total episodes: {total_episodes}\n- At least {projected_time_hours:.1f} hours\n- About {projected_tokens:,.0f} tokens\n"
            
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
        vault_dir = VAULT_ROOT / f"scaled_{size}"
        if not vault_dir.exists():
            print(f"ERROR: Vault directory not found: {vault_dir}")
            continue
        
        questions = load_questions(vault_dir)
        fingerprint = vault_fingerprint(size)

        for arm in arms:
            print(f"  Arm: {arm}")
            for run_num in range(1, runs + 1):
                pending = [q for q in questions if f"{size}_{arm}_{run_num}_{q['id']}" not in progress]
                print(f"    Run {run_num}/{runs}: {len(pending)} pending")
                if not pending:
                    continue
                prepared = PreparedVault(vault_dir)
                try:
                    for q in pending:
                        key = f"{size}_{arm}_{run_num}_{q['id']}"
                        result = run_episode(client, model, prepared.path, prepared.mgr, q, arm, run_num, size, fingerprint)
                        save_progress(result)
                        if result["outcome"] in DONE_OUTCOMES:
                            progress[key] = result
                finally:
                    prepared.close()

        # Commit after each size (best effort; never stops the run)
        print(f"  Size {size} complete, committing...")
        try:
            subprocess.run(["git", "add", str(RESULT_DIR)], check=False)
            subprocess.run(["git", "commit", "-m", f"[WP2] Add results for size {size}"], check=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  (git commit skipped: {exc})")


def main():
    parser = argparse.ArgumentParser(description="Resumable scaling evaluation runner")
    parser.add_argument("--size", type=int, help="Run specific size only")
    parser.add_argument("--arm", type=str, help="Run specific arm only")
    parser.add_argument("--runs", type=int, default=RUNS, help="Number of runs per arm")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--smoke-only", action="store_true", help="Run smoke test only")
    parser.add_argument(
        "--invalidate-stale",
        action="store_true",
        help="Move episodes whose question/vault hashes differ from the current files to invalidated.jsonl",
    )
    args = parser.parse_args()
    
    sizes = [args.size] if args.size else None
    arms = [args.arm] if args.arm else None
    
    run_scaling(sizes=sizes, arms=arms, runs=args.runs, model=args.model, smoke_only=args.smoke_only,
                invalidate_stale=args.invalidate_stale)


if __name__ == "__main__":
    main()
