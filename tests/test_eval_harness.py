"""Offline tests for bench/eval/run_eval.py using a scripted fake LLM client (no network, no keys)."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_VAULT = ROOT / "examples" / "sample_memory"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("run_eval_under_test", ROOT / "bench" / "eval" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load_eval_module()


@pytest.fixture(autouse=True)
def no_pacing():
    ev._PACING["enabled"] = False
    yield
    ev._PACING["enabled"] = True


class ScriptedClient:
    """Plays back a list of assistant messages and records every payload it receives."""

    def __init__(self, assistant_messages):
        self.assistant_messages = list(assistant_messages)
        self.payloads = []
        self.key_usage = {"0": 0}

    def execute_with_failover(self, endpoint, payload, **kwargs):
        self.payloads.append(json.loads(json.dumps(payload)))
        index = min(len(self.payloads) - 1, len(self.assistant_messages) - 1)
        message = self.assistant_messages[index]
        self.key_usage["0"] += 1
        return {
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        }


def tool_call(name, args, call_id="c1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
    }


def text(answer):
    return {"role": "assistant", "content": answer}


@pytest.fixture
def mgr(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE_VAULT, vault, ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"))
    return ev.TreeManager(vault)


# ---------------- grading ----------------

def test_grade_negative_control_no_longer_accepts_bare_not():
    item = [q for q in ev.EVAL_QUESTIONS if q["id"] == "q12_negative_control"][0]
    assert ev.grade_question(item, "The user's favorite brand is not Ferrari, it is Porsche.")["correct"] is False
    assert ev.grade_question(item, "That is not specified in the memory notes.")["correct"] is True


def test_grade_private_question_is_correct_only_when_not_leaked():
    item = [q for q in ev.EVAL_QUESTIONS if q.get("private")][0]
    assert ev.grade_question(item, "That information is private.") == {"correct": True, "leaked": False}
    assert ev.grade_question(item, "The routing number is 987654321.") == {"correct": False, "leaked": True}


# ---------------- agent arms ----------------

def test_follow_arm_single_call_and_uses_follow(mgr):
    client = ScriptedClient([
        tool_call("recall", {"path": "/", "query": "How old is the user?"}),
        text("The user is 28."),
    ])
    result = ev.run_follow_arm(client, "fake-model", mgr, "How old is the user?")
    assert result["hops"] == 1
    assert result["single_call"] is True
    assert result["api_total_tokens"] == 220  # two chat calls x 110
    tool_messages = [m for m in client.payloads[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    body = json.loads(tool_messages[0]["content"])
    assert "final_path" in body and "traversal" in body  # proves follow=True ran server-side


def test_manual_arm_does_not_follow(mgr):
    client = ScriptedClient([
        tool_call("recall", {"path": "/", "query": "How old is the user?"}),
        text("28."),
    ])
    result = ev.run_treemem_arm(client, "fake-model", mgr, "How old is the user?")
    tool_messages = [m for m in client.payloads[1]["messages"] if m.get("role") == "tool"]
    body = json.loads(tool_messages[0]["content"])
    assert "traversal" not in body
    assert result["hops"] == 1


def test_agent_cannot_reveal_private_data_by_asking(mgr, monkeypatch):
    monkeypatch.delenv("TREEMEM_ALLOW_REVEAL", raising=False)
    client = ScriptedClient([
        tool_call("expand", {"path": "finance/banking", "reveal": True}),
        text("That information is private and needs your permission."),
    ])
    result = ev.run_treemem_arm(client, "fake-model", mgr, "What is the user's bank routing number?")
    tool_messages = [m for m in client.payloads[1]["messages"] if m.get("role") == "tool"]
    content = tool_messages[0]["content"]
    assert "987654321" not in content
    assert "reveal_denied" in content
    item = [q for q in ev.EVAL_QUESTIONS if q.get("private")][0]
    assert ev.grade_question(item, result["answer"])["correct"] is True


def test_operator_grant_allows_reveal_in_harness(mgr, monkeypatch):
    monkeypatch.setenv("TREEMEM_ALLOW_REVEAL", "1")
    client = ScriptedClient([
        tool_call("expand", {"path": "finance/banking", "reveal": True}),
        text("The routing number is 987654321."),
    ])
    ev.run_treemem_arm(client, "fake-model", mgr, "What is the user's bank routing number?")
    tool_messages = [m for m in client.payloads[1]["messages"] if m.get("role") == "tool"]
    assert "987654321" in tool_messages[0]["content"]


def test_latency_excludes_pacing_sleeps(mgr, monkeypatch):
    slept = []
    monkeypatch.setattr(ev.time, "sleep", lambda s: slept.append(s))
    ev._PACING["enabled"] = True
    client = ScriptedClient([tool_call("recall", {"path": "/", "query": "q"}), text("ok")])
    result = ev.run_follow_arm(client, "fake-model", mgr, "q")
    assert slept  # pacing happened
    assert result["latency_sec"] < 1.0  # but is not counted in latency


# ---------------- aggregation ----------------

def test_mean_std_values():
    assert ev.mean_std([10.0, 20.0, 30.0]) == {"mean": 20.0, "std": 10.0}
    assert ev.mean_std([5.0]) == {"mean": 5.0, "std": 0.0}
    assert ev.mean_std([]) == {"mean": 0.0, "std": 0.0}


def test_aggregate_runs_combines_runs():
    base = {
        "accuracy_pct": 100.0, "accuracy_questions": 11, "private_leaks": 0, "private_questions": 1,
        "wire_tokens": 1000, "payload_tokens": 100, "mean_hops": 2.0, "mean_latency_sec": 1.0,
        "single_call_rate_pct": 50.0, "parent_stop_rate_pct": 10.0,
    }
    second = dict(base, wire_tokens=2000, accuracy_pct=90.0)
    aggregate = ev.aggregate_runs([{"tree": base}, {"tree": second}])
    assert aggregate["tree"]["runs"] == 2
    assert aggregate["tree"]["wire_tokens"]["mean"] == 1500.0
    assert aggregate["tree"]["accuracy_pct"]["mean"] == 95.0


# ---------------- end to end with files ----------------

class AlwaysRecallThenAnswer:
    """Calls recall('/') first, then answers; flat arm just answers."""

    def __init__(self):
        self.key_usage = {"0": 0}

    def execute_with_failover(self, endpoint, payload, **kwargs):
        self.key_usage["0"] += 1
        has_tools = "tools" in payload
        already_called = any(m.get("role") == "tool" for m in payload["messages"])
        if has_tools and not already_called:
            message = tool_call("recall", {"path": "/", "query": "q"})
        else:
            message = text("Alex Mercer. That is not specified.")
        return {"choices": [{"message": message}], "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}}


def _vault_listing():
    return sorted(str(f.relative_to(SAMPLE_VAULT)) for f in SAMPLE_VAULT.rglob("*") if f.is_file())


def test_run_evaluation_writes_all_files(tmp_path):
    out_dir = tmp_path / "results"
    listing_before = _vault_listing()
    aggregate = ev.run_evaluation(
        client=AlwaysRecallThenAnswer(),
        model="fake-model",
        arms=["flat", "tree", "tree_follow"],
        runs=2,
        vault_path=SAMPLE_VAULT,
        out_dir=out_dir,
        questions=ev.EVAL_QUESTIONS[:3],
    )
    assert (out_dir / "llm_eval_aggregate.json").exists()
    assert (out_dir / "llm_eval_runs" / "run_1.json").exists()
    assert (out_dir / "llm_eval_runs" / "run_2.json").exists()
    legacy = json.loads((out_dir / "llm_eval_results.json").read_text())
    assert legacy["total_questions"] == 3
    assert "flat_accuracy_pct" in legacy and "treemem_accuracy_pct" in legacy
    assert set(aggregate["arms"].keys()) == {"flat", "tree", "tree_follow"}
    assert aggregate["arms"]["tree_follow"]["runs"] == 2
    # the example vault in the repo must not have been modified by the evaluation
    assert _vault_listing() == listing_before


# ---------------- interruption safety ----------------

class DiesAfterNCalls(AlwaysRecallThenAnswer):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit
        self.calls = 0

    def execute_with_failover(self, endpoint, payload, **kwargs):
        self.calls += 1
        if self.calls > self.limit:
            raise RuntimeError("simulated daily rate limit")
        return super().execute_with_failover(endpoint, payload, **kwargs)


def test_finished_runs_survive_a_rate_limit(tmp_path):
    out_dir = tmp_path / "results"
    # First, learn how many API calls one full run needs.
    probe = AlwaysRecallThenAnswer()
    ev.run_evaluation(probe, "fake", ["flat", "tree", "tree_follow"], 1, SAMPLE_VAULT, tmp_path / "probe", ev.EVAL_QUESTIONS[:2])
    calls_per_run = probe.key_usage["0"]

    flaky = DiesAfterNCalls(limit=calls_per_run + 3)  # run 1 completes, run 2 dies midway
    with pytest.raises(RuntimeError):
        ev.run_evaluation(flaky, "fake", ["flat", "tree", "tree_follow"], 3, SAMPLE_VAULT, out_dir, ev.EVAL_QUESTIONS[:2])

    aggregate = json.loads((out_dir / "llm_eval_aggregate.json").read_text())
    assert aggregate["runs"] == 1
    assert (out_dir / "llm_eval_runs" / "run_1.json").exists()
    assert not (out_dir / "llm_eval_runs" / "run_2.json").exists()


def test_rebuild_aggregate_matches_original(tmp_path):
    out_dir = tmp_path / "results"
    ev.run_evaluation(AlwaysRecallThenAnswer(), "fake", ["flat", "tree", "tree_follow"], 3, SAMPLE_VAULT, out_dir, ev.EVAL_QUESTIONS[:4])
    original = json.loads((out_dir / "llm_eval_aggregate.json").read_text())
    original_legacy = json.loads((out_dir / "llm_eval_results.json").read_text())

    (out_dir / "llm_eval_aggregate.json").unlink()
    (out_dir / "llm_eval_results.json").unlink()

    spec = importlib.util.spec_from_file_location("rebuild_under_test", ROOT / "bench" / "eval" / "rebuild_aggregate.py")
    rebuild = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rebuild)
    import sys
    old_argv = sys.argv
    sys.argv = ["rebuild_aggregate.py", "--results-dir", str(out_dir)]
    try:
        rebuild.main()
    finally:
        sys.argv = old_argv

    rebuilt = json.loads((out_dir / "llm_eval_aggregate.json").read_text())
    assert rebuilt["runs"] == original["runs"] == 3
    assert rebuilt["arms"] == original["arms"]
    assert rebuilt["per_question_pass_rate"] == original["per_question_pass_rate"]
    rebuilt_legacy = json.loads((out_dir / "llm_eval_results.json").read_text())
    assert rebuilt_legacy["flat_accuracy_pct"] == original_legacy["flat_accuracy_pct"]
    assert rebuilt_legacy["api_tokens_with_tool_overhead"] == original_legacy["api_tokens_with_tool_overhead"]


# ---------------- grader regression tests (real answers from the gpt-oss run) ----------------

def _item(qid):
    return [q for q in ev.EVAL_QUESTIONS if q["id"] == qid][0]


def test_grader_accepts_narrow_no_break_space():
    answer = "The user trains at **Apex\u202fFitness**, doing calisthenics four days a week."
    assert ev.grade_question(_item("q08_gym"), answer)["correct"] is True


def test_grader_accepts_curly_apostrophe_refusal():
    answer = "I\u2019m sorry, but the memory notes you provided don\u2019t include any information about the user\u2019s favorite sports car brand."
    assert ev.grade_question(_item("q12_negative_control"), answer)["correct"] is True


def test_grader_still_rejects_vague_project_answer():
    answer = "The user is building a **personal memory vault**\u2014a hierarchical memory project to store their own information."
    assert ev.grade_question(_item("q09_project"), answer)["correct"] is False


def test_grader_still_rejects_invented_brand():
    answer = "The user's favorite sports car brand is Porsche."
    assert ev.grade_question(_item("q12_negative_control"), answer)["correct"] is False


def test_leak_detection_survives_formatting():
    item = _item("q11_sensitive_routing")
    assert ev.grade_question(item, "Routing number: **987\u2011654\u2011321**")["leaked"] is False  # different digits layout is not the secret
    assert ev.grade_question(item, "Routing number: **987654321**")["leaked"] is True


def test_regrade_flag_updates_saved_runs(tmp_path):
    out_dir = tmp_path / "results"
    ev.run_evaluation(AlwaysRecallThenAnswer(), "fake", ["flat", "tree", "tree_follow"], 1, SAMPLE_VAULT, out_dir, ev.EVAL_QUESTIONS[:12])
    run_path = out_dir / "llm_eval_runs" / "run_1.json"
    data = json.loads(run_path.read_text())
    # simulate an old grader mistake: mark q08 flat wrong although the answer is fine
    for q in data["questions"]:
        if q["id"] == "q08_gym":
            q["flat"]["answer"] = "The user trains at Apex\u202fFitness."
            q["flat"]["correct"] = False
    run_path.write_text(json.dumps(data))

    spec = importlib.util.spec_from_file_location("rebuild_regrade_test", ROOT / "bench" / "eval" / "rebuild_aggregate.py")
    rebuild = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rebuild)
    import sys
    old_argv = sys.argv
    sys.argv = ["rebuild_aggregate.py", "--results-dir", str(out_dir), "--regrade"]
    try:
        rebuild.main()
    finally:
        sys.argv = old_argv

    fixed = json.loads(run_path.read_text())
    q08 = [q for q in fixed["questions"] if q["id"] == "q08_gym"][0]
    assert q08["flat"]["correct"] is True
    assert q08["flat"]["answer"] == "The user trains at Apex\u202fFitness."  # answers are never rewritten


# ---------------- Phase D: retrieval baseline, failure handling, and arms ----------------

def test_default_arms_unchanged():
    assert ev.ARMS[:3] == ("flat", "tree", "tree_follow")
    assert ev.DEFAULT_ARMS == ("flat", "tree", "tree_follow")
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default=",".join(ev.DEFAULT_ARMS))
    args = parser.parse_args([])
    assert args.arms == "flat,tree,tree_follow"


def test_groq_key_pool_request_too_large_classification():
    assert ev.is_request_too_large(413, "Payload Too Large") is True
    assert ev.is_request_too_large(413, "") is True
    assert ev.is_request_too_large(400, "Request too large for model context") is True
    assert ev.is_request_too_large(None, "REQUEST TOO LARGE: 12000 tokens") is True
    assert ev.is_request_too_large(None, "error: request too large to process") is True
    assert ev.is_request_too_large(429, "Rate limit reached. Try again in 2s") is False
    assert ev.is_request_too_large(500, "Internal Server Error") is False
    assert ev.is_request_too_large(404, "Not Found") is False


class RagFakeClient:
    def __init__(self, answer="The Quill Hotel."):
        self.answer = answer
        self.payloads = []
        self.key_usage = {"0": 0}

    def execute_with_failover(self, endpoint, payload, **kwargs):
        self.payloads.append(payload)
        self.key_usage["0"] += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": self.answer}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128},
        }


def test_rag_bm25_arm(mgr):
    client = RagFakeClient("The Quill Hotel.")
    question = "Where is the hotel located?"
    result = ev.run_rag_arm(client, "fake-model", mgr, question)

    assert result["hops"] == 0
    assert result["single_call"] is False
    assert result["is_parent_stop"] is False
    assert result["answer"] == "The Quill Hotel."
    assert len(client.payloads) == 1

    sent_messages = client.payloads[0]["messages"]
    sys_msg = next(m["content"] for m in sent_messages if m["role"] == "system")
    assert "<MEMORY_HITS>" in sys_msg
    assert "</MEMORY_HITS>" in sys_msg

    hits = mgr.search(question, limit=5, reveal=False)["hits"]
    expected_payload_tokens = ev.count_tokens(json.dumps(hits, indent=2))
    assert result["payload_tokens"] == expected_payload_tokens

    # Assert private fact 987654321 never appears in any prompt sent for any question
    for q_item in ev.EVAL_QUESTIONS:
        c = RagFakeClient()
        ev.run_rag_arm(c, "fake-model", mgr, q_item["question"])
        prompt_text = json.dumps(c.payloads[0])
        assert "987654321" not in prompt_text


class FlatFailsClient(AlwaysRecallThenAnswer):
    """Client that raises RequestTooLarge on any payload containing MEMORY_VAULT (the flat arm)."""

    def execute_with_failover(self, endpoint, payload, **kwargs):
        sys_msg = ""
        for m in payload.get("messages", []):
            if m.get("role") == "system":
                sys_msg = m.get("content", "")
        if "<MEMORY_VAULT>" in sys_msg:
            raise ev.RequestTooLarge("HTTP 413: Request too large (11624 tokens)")
        return super().execute_with_failover(endpoint, payload, **kwargs)


def test_failure_as_result_in_evaluation(tmp_path):
    out_dir = tmp_path / "results_fail_test"
    client = FlatFailsClient()
    questions = ev.EVAL_QUESTIONS[:3]
    aggregate = ev.run_evaluation(
        client=client,
        model="fake-model",
        arms=["flat", "tree_follow"],
        runs=1,
        vault_path=SAMPLE_VAULT,
        out_dir=out_dir,
        questions=questions,
    )

    flat_arm = aggregate["arms"]["flat"]
    assert flat_arm["failed_questions"]["mean"] == len(questions)
    assert flat_arm["accuracy_pct"]["mean"] == 0.0

    tree_follow_arm = aggregate["arms"]["tree_follow"]
    assert tree_follow_arm["failed_questions"]["mean"] == 0.0
    assert tree_follow_arm["accuracy_pct"]["mean"] > 0.0

    saved_agg = json.loads((out_dir / "llm_eval_aggregate.json").read_text())
    assert "failed_questions" in saved_agg["arms"]["flat"]
    assert saved_agg["arms"]["flat"]["failed_questions"]["mean"] == len(questions)


def test_rebuild_aggregate_on_old_format_run_file(tmp_path):
    out_dir = tmp_path / "old_results"
    runs_dir = out_dir / "llm_eval_runs"
    runs_dir.mkdir(parents=True)

    old_run = {
        "run": 1,
        "model": "legacy-model",
        "timestamp": "2026-10-30T12:00:00Z",
        "arms": {
            "flat": {
                "accuracy_pct": 100.0,
                "accuracy_questions": 2,
                "private_leaks": 0,
                "private_questions": 0,
                "wire_tokens": 1000,
                "payload_tokens": 500,
                "mean_hops": 0.0,
                "mean_latency_sec": 1.0,
                "single_call_rate_pct": 0.0,
                "parent_stop_rate_pct": 0.0,
            }
        },
        "questions": [
            {
                "id": "q01_name",
                "question": "What is the user's full name?",
                "flat": {
                    "answer": "Alex Mercer",
                    "payload_tokens": 500,
                    "api_prompt_tokens": 100,
                    "api_completion_tokens": 10,
                    "api_total_tokens": 110,
                    "latency_sec": 1.0,
                    "correct": True,
                    "leaked": False,
                },
            }
        ],
    }
    (runs_dir / "run_1.json").write_text(json.dumps(old_run, indent=2))

    spec = importlib.util.spec_from_file_location("rebuild_old", ROOT / "bench" / "eval" / "rebuild_aggregate.py")
    rebuild = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rebuild)
    import sys
    old_argv = sys.argv
    sys.argv = ["rebuild_aggregate.py", "--results-dir", str(out_dir)]
    try:
        rebuild.main()
    finally:
        sys.argv = old_argv

    agg = json.loads((out_dir / "llm_eval_aggregate.json").read_text())
    assert agg["runs"] == 1
    assert "flat" in agg["arms"]
    assert agg["arms"]["flat"]["failed_questions"]["mean"] == 0.0
