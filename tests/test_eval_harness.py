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
