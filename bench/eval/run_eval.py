"""End-to-End LLM Agent Evaluation: Flat Memory vs. TreeMem Hierarchical Descent.

Uses Groq API with multi-key round-robin rotation, polite pacing, and failover.
Compares Arm A (Flat context dump) against Arm B (Autonomous TreeMem descent).
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager


class GroqKeyPool:
    """Manages rotation and automatic failover across multiple Groq API keys."""

    def __init__(self, keys: List[str]):
        if not keys:
            raise ValueError("No Groq API keys provided.")
        self.keys = keys
        self.current_idx = 0
        self.key_usage = {i: 0 for i in range(len(keys))}

    def get_key(self) -> Tuple[int, str]:
        idx = self.current_idx
        self.current_idx = (self.current_idx + 1) % len(self.keys)
        self.key_usage[idx] += 1
        return idx, self.keys[idx]

    def execute_with_failover(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        max_retries: int = 8,
        timeout: float = 40.0,
    ) -> Dict[str, Any]:
        """Executes a request to Groq, rotating keys and failing over on rate limits (429)."""
        last_error = None
        for attempt in range(max_retries):
            key_idx, key = self.get_key()
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            try:
                response = httpx.post(endpoint, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = 2.0
                    if "retry-after" in response.headers:
                        try:
                            retry_after = float(response.headers["retry-after"])
                        except Exception:
                            pass
                    else:
                        m = re.search(r"try again in ([\d\.]+)s", response.text)
                        if m:
                            retry_after = float(m.group(1)) + 0.5
                    sleep_dur = max(retry_after, 2.5)
                    last_error = f"HTTP 429 Rate Limit on Key {key_idx}: {response.text[:100]}"
                    print(f"      [429 RateLimit] Key {key_idx}. Backing off {sleep_dur:.1f}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(sleep_dur)
                    continue
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:120]}"
                    time.sleep(1.5)
            except Exception as e:
                last_error = str(e)
                time.sleep(1.5)

        raise RuntimeError(f"Groq request failed after {max_retries} retries across keys. Last error: {last_error}")


# 12 Benchmark Questions representing varied descent depths and negative controls
EVAL_QUESTIONS = [
    # Depth 0: Root Parent-Stop (Answered directly by root summary)
    {
        "id": "q01_name",
        "question": "What is the user's full name?",
        "expected": "Alex Mercer",
        "target_depth": 0,
        "keywords": ["alex", "mercer"],
    },
    {
        "id": "q02_profession",
        "question": "What is the user's primary profession?",
        "expected": "Software Engineer",
        "target_depth": 0,
        "keywords": ["software engineer", "engineer"],
    },
    {
        "id": "q03_location",
        "question": "Which city does the user currently reside in?",
        "expected": "Metropolis",
        "target_depth": 0,
        "keywords": ["metropolis"],
    },
    # Depth 1: Category Summary
    {
        "id": "q04_education_overview",
        "question": "What is the user's academic and educational background?",
        "expected": "B.S. in Computer Science from Metro State University",
        "target_depth": 1,
        "keywords": ["computer science", "metro state", "degree"],
    },
    {
        "id": "q05_career_overview",
        "question": "Summarize the user's career and current employer.",
        "expected": "Software Engineer at Nova Labs",
        "target_depth": 1,
        "keywords": ["nova labs", "software engineer"],
    },
    # Depth 2: Leaf Facts (Needle-in-haystack drilldown)
    {
        "id": "q06_college_name",
        "question": "Which exact university did the user graduate from?",
        "expected": "Metro State University",
        "target_depth": 2,
        "keywords": ["metro state"],
    },
    {
        "id": "q07_email",
        "question": "What is the user's email address?",
        "expected": "alex.mercer@example.org",
        "target_depth": 2,
        "keywords": ["alex.mercer@example.org"],
    },
    {
        "id": "q08_gym",
        "question": "Where does the user go to workout and train?",
        "expected": "Apex Fitness",
        "target_depth": 2,
        "keywords": ["apex fitness"],
    },
    {
        "id": "q09_project",
        "question": "What hierarchical memory project is the user building?",
        "expected": "TreeMem",
        "target_depth": 2,
        "keywords": ["treemem"],
    },
    {
        "id": "q10_coding_preferences",
        "question": "What programming languages does the user prefer for backend engineering?",
        "expected": "Python and Rust",
        "target_depth": 2,
        "keywords": ["python", "rust"],
    },
    {
        "id": "q11_sensitive_routing",
        "question": "What is the user's bank routing number?",
        "expected": "987654321",
        "target_depth": 2,
        "keywords": ["987654321"],
    },
    # Negative Control: Fact not in memory
    {
        "id": "q12_negative_control",
        "question": "What is the user's favorite sports car brand?",
        "expected": "Not specified / Unknown",
        "target_depth": 0,
        "keywords": ["not", "unknown", "unspecified", "no information", "does not mention"],
    },
]


def load_groq_keys() -> List[str]:
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


def run_flat_arm(
    pool: GroqKeyPool,
    model: str,
    vault_path: Path,
    question: str,
) -> Dict[str, Any]:
    """Arm A: Dump all leaf facts into context in one shot."""
    # Concatenate all leaf facts
    log_files = sorted((vault_path / "log").glob("*.md"))
    log_text = ""
    for lf in log_files:
        log_text += lf.read_text(encoding="utf-8") + "\n"

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

    start = time.time()
    resp = pool.execute_with_failover("https://api.groq.com/openai/v1/chat/completions", payload)
    latency = time.time() - start

    usage = resp.get("usage", {})
    answer = resp["choices"][0]["message"]["content"].strip()

    # Brief pacing sleep
    time.sleep(1.0)

    return {
        "answer": answer,
        "payload_tokens": flat_payload_tokens,
        "api_prompt_tokens": usage.get("prompt_tokens", 0),
        "api_completion_tokens": usage.get("completion_tokens", 0),
        "api_total_tokens": usage.get("total_tokens", 0),
        "latency_sec": round(latency, 3),
    }


def run_treemem_arm(
    pool: GroqKeyPool,
    model: str,
    mgr: TreeManager,
    question: str,
) -> Dict[str, Any]:
    """Arm B: Autonomous TreeMem descent using function calling."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Reads a node's concise summary and 1-line child teasers. ALWAYS call recall('/') first. NEVER returns child bodies.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The topic path to recall (e.g. '/' for root, 'identity', 'projects').",
                        },
                        "query": {
                            "type": "string",
                            "description": "The question or search query being answered, used by the descent gate to evaluate parent sufficiency.",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "expand",
                "description": "Drill down into deeper child summaries or raw leaf facts under path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path to expand into.",
                        },
                        "reveal": {
                            "type": "boolean",
                            "description": "Set true to reveal private details if needed.",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "BM25 keyword search over all logs and leaves as a fallback if descent does not reveal the answer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keyword or phrase."},
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    system_prompt = (
        "You are an assistant querying a hierarchical memory tree.\n"
        "You have tools: recall(path, query), expand(path, reveal), search(query).\n\n"
        "RULES:\n"
        "1. ALWAYS begin by calling recall('/').\n"
        "2. PARENT-STOP: If the parent summary answers the question, or if recall() indicates gate.action == 'stop', DO NOT call any more tools! Stop immediately and state your answer.\n"
        "3. Only recall or expand a child topic if the parent summary indicates more specific detail is required.\n"
        "4. If a fact cannot be found after searching relevant topics, stop and state clearly that it is not specified or unknown in the memory notes.\n"
        "5. Be concise and accurate in your final answer."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    total_prompt_tokens = 0
    total_completion_tokens = 0
    memory_payload_tokens = 0
    hops = []
    start = time.time()

    for turn in range(5):  # Max 5 hops
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.0,
            "max_tokens": 200,
        }

        resp = pool.execute_with_failover("https://api.groq.com/openai/v1/chat/completions", payload)
        usage = resp.get("usage", {})
        total_prompt_tokens += usage.get("prompt_tokens", 0)
        total_completion_tokens += usage.get("completion_tokens", 0)

        choice = resp["choices"][0]
        msg = choice["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            # Final text response reached
            break

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except Exception:
                fn_args = {}

            hops.append({"tool": fn_name, "args": fn_args})

            # Execute tool locally
            if fn_name == "recall":
                p = fn_args.get("path", "/")
                q_text = fn_args.get("query") or question
                res = mgr.recall(p, query=q_text, session="eval")
            elif fn_name == "expand":
                p = fn_args.get("path", "")
                rev = fn_args.get("reveal", False)
                res = mgr.expand(p, reveal=rev, session="eval")
            elif fn_name == "search":
                q = fn_args.get("query", "")
                res = mgr.search(q, session="eval")
            else:
                res = {"error": f"Unknown tool {fn_name}"}

            memory_payload_tokens += res.get("tokens", 0)

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(res),
            })

        # Polite inter-turn pacing sleep to avoid bursting Groq rate limits
        time.sleep(1.2)

    latency = time.time() - start

    # If the conversation ended with a tool call and no assistant text synthesis,
    # prompt the model one final time to synthesize its answer based on the search/recall outputs.
    if messages and messages[-1].get("role") == "tool":
        final_payload = {
            "model": model,
            "messages": messages + [
                {
                    "role": "user",
                    "content": "Based strictly on the tool outputs above, answer the original question concisely. If the fact was not found in the memory notes, state clearly that it is not specified or unknown.",
                }
            ],
            "temperature": 0.0,
            "max_tokens": 150,
        }
        try:
            resp = pool.execute_with_failover("https://api.groq.com/openai/v1/chat/completions", final_payload)
            usage = resp.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)
            final_answer = resp["choices"][0]["message"]["content"].strip()
        except Exception:
            final_answer = messages[-1].get("content", "")
    else:
        # Extract the last assistant text message
        final_answer = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("content"):
                final_answer = m["content"].strip()
                break
        if not final_answer and messages:
            final_answer = messages[-1].get("content", "")

    # Calculate descent depth
    depth = 0
    for h in hops:
        path = h.get("args", {}).get("path", "")
        if path and path != "/":
            d = len(path.strip("/").split("/"))
            depth = max(depth, d)

    is_parent_stop = len(hops) == 1 and hops[0].get("args", {}).get("path") in ["/", ""]

    return {
        "answer": final_answer,
        "payload_tokens": memory_payload_tokens,
        "api_prompt_tokens": total_prompt_tokens,
        "api_completion_tokens": total_completion_tokens,
        "api_total_tokens": total_prompt_tokens + total_completion_tokens,
        "hops": len(hops),
        "hop_details": hops,
        "depth_reached": depth,
        "is_parent_stop": is_parent_stop,
        "latency_sec": round(latency, 3),
    }


def grade_answer(answer: str, expected_keywords: List[str]) -> bool:
    low = answer.lower()
    return any(k.lower() in low for k in expected_keywords)


def main():
    keys = load_groq_keys()
    if not keys:
        print("Error: No GROQ_API_KEY_1 or GROQ_API_KEY_2 found in .env")
        return

    print(f"Loaded {len(keys)} Groq API keys for evaluation pool.")
    pool = GroqKeyPool(keys)
    model = "qwen/qwen3.8-27b"

    vault_path = Path("examples/sample_memory")
    mgr = TreeManager(vault_path)

    print(f"\n=======================================================")
    print(f"  TreeMem Real LLM Evaluation Benchmark ({model})")
    print(f"=======================================================\n")

    results = []
    flat_total_payload_tokens = 0
    tree_total_payload_tokens = 0
    flat_total_api_tokens = 0
    tree_total_api_tokens = 0
    parent_stops = 0
    flat_correct = 0
    tree_correct = 0

    for idx, item in enumerate(EVAL_QUESTIONS, 1):
        q = item["question"]
        print(f"[{idx}/{len(EVAL_QUESTIONS)}] Query: {q}")

        # Run Arm A: Flat
        flat_res = run_flat_arm(pool, model, vault_path, q)
        flat_ok = grade_answer(flat_res["answer"], item["keywords"])
        if flat_ok:
            flat_correct += 1
        flat_total_payload_tokens += flat_res["payload_tokens"]
        flat_total_api_tokens += flat_res["api_total_tokens"]

        # Run Arm B: TreeMem
        tree_res = run_treemem_arm(pool, model, mgr, q)
        tree_ok = grade_answer(tree_res["answer"], item["keywords"])
        if tree_ok:
            tree_correct += 1
        tree_total_payload_tokens += tree_res["payload_tokens"]
        tree_total_api_tokens += tree_res["api_total_tokens"]
        if tree_res["is_parent_stop"]:
            parent_stops += 1

        print(f"   Flat: {flat_res['payload_tokens']} mem tok (API: {flat_res['api_total_tokens']}) | Correct: {flat_ok} | Latency: {flat_res['latency_sec']}s")
        print(f"   Tree: {tree_res['payload_tokens']} mem tok (API: {tree_res['api_total_tokens']}, hops={tree_res['hops']}, depth={tree_res['depth_reached']}, parent_stop={tree_res['is_parent_stop']}) | Correct: {tree_ok} | Latency: {tree_res['latency_sec']}s")
        print(f"   Ans: {tree_res['answer'][:70]}...")
        print(f"   --------------------------------------------------")

        results.append({
            "id": item["id"],
            "question": q,
            "expected": item["expected"],
            "target_depth": item["target_depth"],
            "flat": {**flat_res, "correct": flat_ok},
            "treemem": {**tree_res, "correct": tree_ok},
        })

    # Summary Calculations
    total_q = len(EVAL_QUESTIONS)
    payload_reduction_pct = (
        ((flat_total_payload_tokens - tree_total_payload_tokens) / flat_total_payload_tokens) * 100
        if flat_total_payload_tokens else 0
    )
    parent_stop_pct = (parent_stops / total_q) * 100

    summary = {
        "model": model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_questions": total_q,
        "flat_accuracy_pct": round((flat_correct / total_q) * 100, 1),
        "treemem_accuracy_pct": round((tree_correct / total_q) * 100, 1),
        "memory_payload_tokens": {
            "flat_total": flat_total_payload_tokens,
            "treemem_total": tree_total_payload_tokens,
            "reduction_pct": round(payload_reduction_pct, 2),
        },
        "api_tokens_with_tool_overhead": {
            "flat_total": flat_total_api_tokens,
            "treemem_total": tree_total_api_tokens,
        },
        "parent_stop_rate_pct": round(parent_stop_pct, 1),
        "parent_stops_count": parent_stops,
        "key_usage_counts": pool.key_usage,
        "questions": results,
    }

    # Save output to bench/results/llm_eval_results.json
    out_dir = Path("bench/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_eval_results.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n================== SUMMARY ==================")
    print(f"Questions Evaluated:      {total_q}")
    print(f"Flat Memory Accuracy:     {summary['flat_accuracy_pct']}% ({flat_correct}/{total_q})")
    print(f"TreeMem Accuracy:         {summary['treemem_accuracy_pct']}% ({tree_correct}/{total_q})")
    print(f"Memory Payload Tokens:    Flat = {flat_total_payload_tokens:,} | TreeMem = {tree_total_payload_tokens:,} ({summary['memory_payload_tokens']['reduction_pct']}% payload reduction)")
    print(f"API Wire Tokens:          Flat = {flat_total_api_tokens:,} | TreeMem = {tree_total_api_tokens:,} (reflects multi-turn tool calling)")
    print(f"Parent-Stop Rate:         {summary['parent_stop_rate_pct']}% ({parent_stops}/{total_q})")
    print(f"Key Rotation Usage:       {pool.key_usage}")
    print(f"Raw results committed to: {out_path}")
    print("=============================================\n")


if __name__ == "__main__":
    main()
