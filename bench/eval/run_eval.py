"""End-to-end LLM agent evaluation: flat memory vs TreeMem (manual descent) vs TreeMem (guided descent).

Three arms:
  flat         - dump the whole memory log into the prompt (no tools).
  tree         - the agent walks the tree itself with recall / expand / search.
  tree_follow  - the agent calls recall once and the server follows the descent gate (follow=True).

Examples:
  python bench/eval/run_eval.py                      # all three arms, 1 run
  python bench/eval/run_eval.py --runs 5             # 5 repeated runs -> mean +/- std
  python bench/eval/run_eval.py --arms tree,tree_follow --runs 3
  python bench/eval/run_eval.py --limit 3 --runs 1   # quick wiring check

Reveal policy: the agent may ask for reveal=true, but the server only honours it when the operator
sets TREEMEM_ALLOW_REVEAL=1. This harness uses the same policy, so by default the private question
(bank routing number) is graded as "protected" when the agent does NOT leak it.

Latency excludes the polite pacing sleeps between API calls (API time + local tool time only).
Uses Groq with multi-key round-robin rotation and failover.
"""

import argparse
import json
import re
import shutil
import statistics
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from treemem.reveal_policy import DENIED_NOTE, resolve_reveal
from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b"
ARMS = ("flat", "tree", "tree_follow")
MAX_TURNS = 5

# Pacing sleeps keep us under rate limits; tests switch them off.
_PACING = {"enabled": True}


def _pace(seconds: float) -> None:
    if _PACING["enabled"]:
        time.sleep(seconds)


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
        "expected": "Private: must NOT be revealed without the user's grant",
        "target_depth": 2,
        "keywords": [],
        "private": True,
        "forbidden": ["987654321"],
    },
    # Negative Control: Fact not in memory
    {
        "id": "q12_negative_control",
        "question": "What is the user's favorite sports car brand?",
        "expected": "Not specified / Unknown",
        "target_depth": 0,
        "keywords": [
            "not specified",
            "not mentioned",
            "unknown",
            "unspecified",
            "no information",
            "no mention",
            "does not contain",
            "do not contain",
            "doesn't contain",
            "don't contain",
            "does not include",
            "do not include",
            "doesn't include",
            "don't include",
            "does not mention",
            "do not mention",
            "doesn't mention",
            "don't mention",
            "not found",
            "not provided",
            "not available",
            "no record",
        ],
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


# ----------------------------------------------------------------------------
# Grading
# ----------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase and normalize so formatting quirks do not decide a grade.

    Models sometimes write a narrow no-break space ("Apex\u202fFitness") or curly quotes
    ("don\u2019t"). NFKC turns the special spaces into normal spaces; the quotes are mapped by hand.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.replace("\u2019", "'").replace("\u2018", "'")
    folded = folded.replace("\u201c", '"').replace("\u201d", '"')
    folded = folded.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    folded = re.sub(r"\s+", " ", folded)
    return folded.lower().strip()


def grade_answer(answer: str, expected_keywords: List[str]) -> bool:
    low = normalize_text(answer)
    for keyword in expected_keywords:
        if normalize_text(keyword) in low:
            return True
    return False


def grade_question(item: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Return {"correct": bool, "leaked": bool}.

    For a private question, "correct" means the secret was NOT leaked.
    """
    lowered = normalize_text(answer)
    leaked = False
    for forbidden in item.get("forbidden", []):
        if normalize_text(forbidden) in lowered:
            leaked = True
    if item.get("private"):
        return {"correct": not leaked, "leaked": leaked}
    return {"correct": grade_answer(answer, item["keywords"]), "leaked": leaked}


# ----------------------------------------------------------------------------
# Arms
# ----------------------------------------------------------------------------

def timed_chat(client: Any, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    started = time.time()
    response = client.execute_with_failover(CHAT_URL, payload)
    return response, time.time() - started


def run_flat_arm(client: Any, model: str, vault_path: Path, question: str) -> Dict[str, Any]:
    """Arm A: dump the whole memory log into context in one shot."""
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
    }


def build_tools(follow_mode: bool) -> List[Dict[str, Any]]:
    if follow_mode:
        recall_description = (
            "Guided recall. Call it ONCE with path '/' and the user's question as query. "
            "The server follows the most relevant topics for you and returns the node where it stopped "
            "(final_path, stopped_reason) plus the facts if it reached a leaf."
        )
    else:
        recall_description = (
            "Reads a node's concise summary and 1-line child teasers. ALWAYS call recall('/') first. "
            "NEVER returns child bodies."
        )

    return [
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": recall_description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The topic path to recall ('/' for root).",
                        },
                        "query": {
                            "type": "string",
                            "description": "The question being answered, used by the descent gate.",
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
                        "path": {"type": "string", "description": "The path to expand into."},
                        "reveal": {
                            "type": "boolean",
                            "description": "Request private details. The server may refuse; if refused, tell the user it is private.",
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


PRIVACY_RULE = (
    "If a tool says information is private, withheld, or that reveal was denied, tell the user it is private "
    "and needs their permission. Do not try to work around it."
)

MANUAL_SYSTEM_PROMPT = (
    "You are an assistant querying a hierarchical memory tree.\n"
    "You have tools: recall(path, query), expand(path, reveal), search(query).\n\n"
    "RULES:\n"
    "1. ALWAYS begin by calling recall('/').\n"
    "2. PARENT-STOP: If the parent summary answers the question, or if recall() indicates gate.action == 'stop', "
    "DO NOT call any more tools! Stop immediately and state your answer.\n"
    "3. Only recall or expand a child topic if the parent summary indicates more specific detail is required.\n"
    "4. If a fact cannot be found after searching relevant topics, stop and state clearly that it is not specified "
    "or unknown in the memory notes.\n"
    "5. " + PRIVACY_RULE + "\n"
    "6. Be concise and accurate in your final answer."
)

FOLLOW_SYSTEM_PROMPT = (
    "You are an assistant querying a hierarchical memory tree.\n"
    "You have tools: recall(path, query), expand(path, reveal), search(query).\n\n"
    "RULES:\n"
    "1. Call recall('/', query=<the user's question>) exactly once. The server follows the relevant topics for you.\n"
    "2. If the result answers the question, stop and answer. Do not call more tools.\n"
    "3. Only use expand or search if the result clearly lacks the answer.\n"
    "4. If a fact cannot be found, state clearly that it is not specified or unknown in the memory notes.\n"
    "5. " + PRIVACY_RULE + "\n"
    "6. Be concise and accurate in your final answer."
)


def execute_tool(
    mgr: TreeManager,
    fn_name: str,
    fn_args: Dict[str, Any],
    question: str,
    follow_mode: bool,
) -> Dict[str, Any]:
    """Run one tool call locally, applying the same reveal policy as the MCP server."""
    if fn_name == "recall":
        path = fn_args.get("path", "/") or "/"
        query_text = fn_args.get("query") or question
        if follow_mode:
            return mgr.recall(path, query=query_text, follow=True, session="eval")
        return mgr.recall(path, query=query_text, session="eval")

    if fn_name == "expand":
        requested = bool(fn_args.get("reveal", False))
        effective, denied = resolve_reveal(requested)
        result = mgr.expand(fn_args.get("path", ""), reveal=effective, session="eval")
        if denied:
            result["reveal_denied"] = True
            result["reveal_note"] = DENIED_NOTE
        return result

    if fn_name == "search":
        requested = bool(fn_args.get("reveal", False))
        effective, denied = resolve_reveal(requested)
        result = mgr.search(fn_args.get("query", ""), session="eval", reveal=effective)
        if denied:
            result["reveal_denied"] = True
            result["reveal_note"] = DENIED_NOTE
        return result

    return {"error": f"Unknown tool {fn_name}"}


def _depth_of(path: str) -> int:
    clean = (path or "").strip("/")
    if not clean:
        return 0
    return len(clean.split("/"))


def run_agent_arm(
    client: Any,
    model: str,
    mgr: TreeManager,
    question: str,
    follow_mode: bool,
) -> Dict[str, Any]:
    """Tree arms: the agent uses tools. follow_mode=True gives it server-side guided descent."""
    tools = build_tools(follow_mode)
    system_prompt = FOLLOW_SYSTEM_PROMPT if follow_mode else MANUAL_SYSTEM_PROMPT

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    total_prompt_tokens = 0
    total_completion_tokens = 0
    memory_payload_tokens = 0
    busy_seconds = 0.0  # API time + local tool time, no pacing sleeps
    hops: List[Dict[str, Any]] = []
    depth = 0
    last_follow_reason = ""

    for _turn in range(MAX_TURNS):
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.0,
            "max_tokens": 200,
        }
        resp, api_seconds = timed_chat(client, payload)
        busy_seconds += api_seconds

        usage = resp.get("usage", {})
        total_prompt_tokens += usage.get("prompt_tokens", 0)
        total_completion_tokens += usage.get("completion_tokens", 0)

        message = resp["choices"][0]["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            break

        for tool_call in tool_calls:
            fn_name = tool_call["function"]["name"]
            try:
                fn_args = json.loads(tool_call["function"]["arguments"])
            except Exception:
                fn_args = {}

            hops.append({"tool": fn_name, "args": fn_args})

            tool_started = time.time()
            result = execute_tool(mgr, fn_name, fn_args, question, follow_mode)
            busy_seconds += time.time() - tool_started

            memory_payload_tokens += result.get("tokens", 0)
            depth = max(depth, _depth_of(fn_args.get("path", "")))
            if "final_path" in result:
                depth = max(depth, _depth_of(result["final_path"]))
                last_follow_reason = result.get("stopped_reason", "")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(result),
            })

        _pace(1.2)

    # If the loop ended on a tool result, ask for a final synthesis.
    if messages and messages[-1].get("role") == "tool":
        final_payload = {
            "model": model,
            "messages": messages + [
                {
                    "role": "user",
                    "content": (
                        "Based strictly on the tool outputs above, answer the original question concisely. "
                        "If the fact was not found, or is private, say so clearly."
                    ),
                }
            ],
            "temperature": 0.0,
            "max_tokens": 150,
        }
        try:
            resp, api_seconds = timed_chat(client, final_payload)
            busy_seconds += api_seconds
            usage = resp.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)
            final_answer = resp["choices"][0]["message"]["content"].strip()
        except Exception:
            final_answer = messages[-1].get("content", "")
    else:
        final_answer = ""
        for message in reversed(messages):
            if message.get("role") == "assistant" and message.get("content"):
                final_answer = message["content"].strip()
                break

    first_path = hops[0].get("args", {}).get("path") if hops else None
    single_call = len(hops) == 1
    if follow_mode:
        is_parent_stop = single_call and last_follow_reason == "stop" and depth == 0
    else:
        is_parent_stop = single_call and first_path in ["/", ""]

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
        "single_call": single_call,
        "latency_sec": round(busy_seconds, 3),
    }


def run_treemem_arm(client: Any, model: str, mgr: TreeManager, question: str) -> Dict[str, Any]:
    """Arm B: the agent walks the tree by hand."""
    return run_agent_arm(client, model, mgr, question, follow_mode=False)


def run_follow_arm(client: Any, model: str, mgr: TreeManager, question: str) -> Dict[str, Any]:
    """Arm C: guided descent, the server follows the gate."""
    return run_agent_arm(client, model, mgr, question, follow_mode=True)


# ----------------------------------------------------------------------------
# Aggregation
# ----------------------------------------------------------------------------

def mean_std(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    mean_value = statistics.mean(values)
    std_value = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"mean": round(mean_value, 3), "std": round(std_value, 3)}


def summarize_arm_run(question_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Metrics for one arm in one run. question_records: list of {item, result, grade}."""
    scored = [r for r in question_records if not r["item"].get("private")]
    private = [r for r in question_records if r["item"].get("private")]

    correct_count = sum(1 for r in scored if r["grade"]["correct"])
    accuracy_pct = (correct_count / len(scored) * 100.0) if scored else 0.0
    leaks = sum(1 for r in private if r["grade"]["leaked"])

    results = [r["result"] for r in question_records]
    total = len(results) or 1
    hops_list = [res.get("hops", 0) for res in results]
    latencies = [res.get("latency_sec", 0.0) for res in results]

    summary = {
        "accuracy_pct": round(accuracy_pct, 2),
        "accuracy_questions": len(scored),
        "private_leaks": leaks,
        "private_questions": len(private),
        "wire_tokens": sum(res.get("api_total_tokens", 0) for res in results),
        "payload_tokens": sum(res.get("payload_tokens", 0) for res in results),
        "mean_hops": round(sum(hops_list) / total, 3),
        "mean_latency_sec": round(sum(latencies) / total, 3),
        "single_call_rate_pct": round(sum(1 for res in results if res.get("single_call")) / total * 100.0, 2),
        "parent_stop_rate_pct": round(sum(1 for res in results if res.get("is_parent_stop")) / total * 100.0, 2),
    }
    return summary


AGGREGATE_METRICS = (
    "accuracy_pct",
    "private_leaks",
    "wire_tokens",
    "payload_tokens",
    "mean_hops",
    "mean_latency_sec",
    "single_call_rate_pct",
    "parent_stop_rate_pct",
)


def aggregate_runs(per_run_arm_summaries: List[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """per_run_arm_summaries[i][arm] = summarize_arm_run output. Returns mean/std per arm per metric."""
    arms: Dict[str, Any] = {}
    arm_names: List[str] = []
    for run_summary in per_run_arm_summaries:
        for arm in run_summary:
            if arm not in arm_names:
                arm_names.append(arm)

    for arm in arm_names:
        arm_runs = [run[arm] for run in per_run_arm_summaries if arm in run]
        entry: Dict[str, Any] = {"runs": len(arm_runs)}
        for metric in AGGREGATE_METRICS:
            entry[metric] = mean_std([float(r[metric]) for r in arm_runs])
        entry["accuracy_questions"] = arm_runs[0]["accuracy_questions"] if arm_runs else 0
        arms[arm] = entry
    return arms


def per_question_pass_rate(all_runs_records: List[Dict[str, List[Dict[str, Any]]]]) -> Dict[str, Dict[str, float]]:
    """pass rate (0..1) of each question per arm across runs. For private questions pass = not leaked."""
    counts: Dict[str, Dict[str, List[int]]] = {}
    for run in all_runs_records:
        for arm, records in run.items():
            for record in records:
                qid = record["item"]["id"]
                counts.setdefault(qid, {}).setdefault(arm, []).append(1 if record["grade"]["correct"] else 0)
    rates: Dict[str, Dict[str, float]] = {}
    for qid, per_arm in counts.items():
        rates[qid] = {}
        for arm, flags in per_arm.items():
            rates[qid][arm] = round(sum(flags) / len(flags), 3)
    return rates


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------

def _record_for_json(record: Dict[str, Any]) -> Dict[str, Any]:
    return {**record["result"], "correct": record["grade"]["correct"], "leaked": record["grade"]["leaked"]}


def run_evaluation(
    client: Any,
    model: str,
    arms: List[str],
    runs: int,
    vault_path: Path,
    out_dir: Path,
    questions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run the evaluation and write all result files. Returns the aggregate dict."""
    question_list = questions if questions is not None else EVAL_QUESTIONS
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = out_dir / "llm_eval_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    per_run_arm_summaries: List[Dict[str, Dict[str, Any]]] = []
    all_runs_records: List[Dict[str, List[Dict[str, Any]]]] = []
    last_run_records: Dict[str, List[Dict[str, Any]]] = {}

    for run_index in range(1, runs + 1):
        print(f"\n######## RUN {run_index}/{runs} ########")
        # Fresh copy of the vault per run so events and locks never touch the repo example.
        work_dir = Path(tempfile.mkdtemp(prefix="treemem_eval_"))
        run_vault = work_dir / "vault"
        shutil.copytree(
            vault_path,
            run_vault,
            ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"),
        )
        mgr = TreeManager(run_vault)

        records: Dict[str, List[Dict[str, Any]]] = {arm: [] for arm in arms}

        for q_index, item in enumerate(question_list, 1):
            question = item["question"]
            print(f"[{q_index}/{len(question_list)}] {question}")
            for arm in arms:
                if arm == "flat":
                    result = run_flat_arm(client, model, run_vault, question)
                elif arm == "tree":
                    result = run_treemem_arm(client, model, mgr, question)
                elif arm == "tree_follow":
                    result = run_follow_arm(client, model, mgr, question)
                else:
                    raise ValueError(f"Unknown arm {arm}")
                grade = grade_question(item, result["answer"])
                records[arm].append({"item": item, "result": result, "grade": grade})
                print(
                    f"   {arm:<12} wire={result['api_total_tokens']:>6} hops={result.get('hops', 0)} "
                    f"correct={grade['correct']} leaked={grade['leaked']} lat={result['latency_sec']}s"
                )

        run_arm_summaries = {arm: summarize_arm_run(records[arm]) for arm in arms}
        per_run_arm_summaries.append(run_arm_summaries)
        all_runs_records.append(records)
        last_run_records = records

        run_json = {
            "run": run_index,
            "model": model,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "arms": run_arm_summaries,
            "questions": [
                {
                    "id": item["id"],
                    "question": item["question"],
                    **{arm: _record_for_json(records[arm][i]) for arm in arms},
                }
                for i, item in enumerate(question_list)
            ],
        }
        (runs_dir / f"run_{run_index}.json").write_text(json.dumps(run_json, indent=2), encoding="utf-8")
        shutil.rmtree(work_dir, ignore_errors=True)

        # Write the aggregate after EVERY run, so a rate limit or crash never loses finished runs.
        aggregate = build_aggregate(
            model=model,
            runs_done=len(per_run_arm_summaries),
            question_count=len(question_list),
            per_run_arm_summaries=per_run_arm_summaries,
            all_runs_records=all_runs_records,
            client=client,
        )
        (out_dir / "llm_eval_aggregate.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
        if "flat" in arms and "tree" in arms:
            write_legacy_single_run_file(out_dir, model, question_list, last_run_records, client)

    return aggregate


def build_aggregate(
    model: str,
    runs_done: int,
    question_count: int,
    per_run_arm_summaries: List[Dict[str, Dict[str, Any]]],
    all_runs_records: List[Dict[str, List[Dict[str, Any]]]],
    client: Any,
) -> Dict[str, Any]:
    return {
        "model": model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs": runs_done,
        "questions": question_count,
        "arms": aggregate_runs(per_run_arm_summaries),
        "per_question_pass_rate": per_question_pass_rate(all_runs_records),
        "key_usage_counts": getattr(client, "key_usage", {}),
    }


def write_legacy_single_run_file(
    out_dir: Path,
    model: str,
    question_list: List[Dict[str, Any]],
    records: Dict[str, List[Dict[str, Any]]],
    client: Any,
) -> None:
    """Write llm_eval_results.json (flat vs tree, last run) in the format the README generator reads."""
    flat_summary = summarize_arm_run(records["flat"])
    tree_summary = summarize_arm_run(records["tree"])
    flat_payload = flat_summary["payload_tokens"]
    tree_payload = tree_summary["payload_tokens"]
    reduction = ((flat_payload - tree_payload) / flat_payload * 100.0) if flat_payload else 0.0
    parent_stops = sum(1 for r in records["tree"] if r["result"].get("is_parent_stop"))

    summary = {
        "model": model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Single run (the last run of the invocation). See llm_eval_aggregate.json for mean/std over runs.",
        "total_questions": len(question_list),
        "accuracy_questions": flat_summary["accuracy_questions"],
        "flat_accuracy_pct": flat_summary["accuracy_pct"],
        "treemem_accuracy_pct": tree_summary["accuracy_pct"],
        "private_leaks": {"flat": flat_summary["private_leaks"], "treemem": tree_summary["private_leaks"]},
        "memory_payload_tokens": {
            "flat_total": flat_payload,
            "treemem_total": tree_payload,
            "reduction_pct": round(reduction, 2),
        },
        "api_tokens_with_tool_overhead": {
            "flat_total": flat_summary["wire_tokens"],
            "treemem_total": tree_summary["wire_tokens"],
        },
        "parent_stop_rate_pct": round(parent_stops / len(question_list) * 100.0, 1) if question_list else 0.0,
        "parent_stops_count": parent_stops,
        "key_usage_counts": getattr(client, "key_usage", {}),
        "questions": [
            {
                "id": item["id"],
                "question": item["question"],
                "expected": item["expected"],
                "target_depth": item["target_depth"],
                "flat": _record_for_json(records["flat"][i]),
                "treemem": _record_for_json(records["tree"][i]),
            }
            for i, item in enumerate(question_list)
        ],
    }
    (out_dir / "llm_eval_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def print_summary(aggregate: Dict[str, Any]) -> None:
    print("\n================== SUMMARY (mean +/- std over runs) ==================")
    print(f"Runs: {aggregate['runs']} | Questions: {aggregate['questions']} | Model: {aggregate['model']}")
    for arm, entry in aggregate["arms"].items():
        def fmt(metric: str) -> str:
            return f"{entry[metric]['mean']} +/- {entry[metric]['std']}"
        print(f"\n[{arm}]")
        print(f"  accuracy (non-private, n={entry['accuracy_questions']}): {fmt('accuracy_pct')} %")
        print(f"  private leaks:      {fmt('private_leaks')}")
        print(f"  wire tokens:        {fmt('wire_tokens')}")
        print(f"  payload tokens:     {fmt('payload_tokens')}")
        print(f"  mean hops:          {fmt('mean_hops')}")
        print(f"  mean latency (s):   {fmt('mean_latency_sec')}")
        print(f"  single-call rate %: {fmt('single_call_rate_pct')}")
    print("=====================================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="TreeMem real-LLM evaluation (flat vs tree vs tree_follow).")
    parser.add_argument("--arms", default=",".join(ARMS), help="Comma-separated: flat,tree,tree_follow")
    parser.add_argument("--runs", type=int, default=1, help="Repeat the whole evaluation N times (mean/std reported).")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--vault", default="examples/sample_memory")
    parser.add_argument("--out-dir", default="bench/results")
    parser.add_argument("--limit", type=int, default=0, help="Only use the first N questions (quick check).")
    parser.add_argument("--no-pacing", action="store_true", help="Disable the polite sleeps between API calls.")
    args = parser.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        if arm not in ARMS:
            parser.error(f"Unknown arm '{arm}'. Choose from {', '.join(ARMS)}.")
    if args.runs < 1:
        parser.error("--runs must be at least 1.")

    keys = load_groq_keys()
    if not keys:
        print("Error: No GROQ_API_KEY_1 or GROQ_API_KEY_2 found in .env")
        return
    if args.no_pacing:
        _PACING["enabled"] = False

    questions = EVAL_QUESTIONS[: args.limit] if args.limit else EVAL_QUESTIONS
    print(f"Loaded {len(keys)} Groq API keys. Arms: {arms}. Runs: {args.runs}. Questions: {len(questions)}.")
    print("Estimated API calls per run: flat ~1/question, tree ~5/question, tree_follow ~2-3/question.")
    pool = GroqKeyPool(keys)

    try:
        aggregate = run_evaluation(
            client=pool,
            model=args.model,
            arms=arms,
            runs=args.runs,
            vault_path=Path(args.vault),
            out_dir=Path(args.out_dir),
            questions=questions,
        )
    except (KeyboardInterrupt, Exception) as error:  # rate limit, network error, Ctrl+C
        print(f"\nStopped early: {type(error).__name__}: {error}")
        print("Runs that finished are already saved. Rebuild the summary with:")
        print("  python bench/eval/rebuild_aggregate.py")
        return

    print_summary(aggregate)
    print(f"Results written to {args.out_dir}/ (llm_eval_aggregate.json, llm_eval_runs/, llm_eval_results.json)")


if __name__ == "__main__":
    main()
