"""Offline preparation and grading for agent-in-the-loop evaluations (e.g. Devin over MCP)."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "eval"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load("make_scaled_vault", "bench/make_scaled_vault.py")
mb = _load("agent_make_batches", "bench/agent_eval/make_batches.py")
gr = _load("agent_grade", "bench/agent_eval/grade_agent_answers.py")


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    base = tmp_path_factory.mktemp("agent_eval")
    vault_root = base / "vaults"
    gen.generate(50, 7, vault_root / "scaled_50", quiet=True)
    root = base / "runs"
    mb.make(50, ["treemem", "bm25", "grep"], 10, 7, root, vault_root)
    return root, vault_root


def test_stats_helpers():
    lo, hi = gr.wilson(40, 40)
    assert 0.90 < lo < 0.93 and hi == 1.0
    assert gr.mcnemar_exact(0, 0) == 1.0
    assert gr.mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert gr.mcnemar_exact(1, 6) == pytest.approx(0.125)
    assert gr.mcnemar_exact(10, 10) == 1.0


def test_parse_answers_tolerates_code_fences_and_chatter():
    text = 'Here you go:\n```json\n[{"id": "q1", "answer": "Zed"}]\n```\nDone.'
    assert gr.parse_answers(text) == [{"id": "q1", "answer": "Zed"}]
    with pytest.raises(ValueError):
        gr.parse_answers("no json here")


def test_batches_leak_nothing_but_id_and_question(prepared):
    root, vault_root = prepared
    questions = json.loads(gen.questions_path(vault_root / "scaled_50").read_text())
    secrets = [s for q in questions for s in q.get("forbidden", [])]
    golds = [f for q in questions for f in q.get("gold_facts", [])]
    keywords = {k for q in questions for k in q.get("keywords", [])}
    for arm in ("treemem", "bm25", "grep"):
        files = sorted((root / "size_50" / arm).glob("*"))
        for f in files:
            text = f.read_text()
            for s in secrets:
                assert s not in text
            if f.name.startswith("batch_") or f.name.startswith("prompt_"):
                assert not any(g in text for g in golds)
                data = json.loads(text) if f.suffix == ".json" else None
                if data is not None:
                    assert all(set(x) == {"id", "question"} for x in data)
        assert len(list((root / "size_50" / arm).glob("batch_*_questions.json"))) == 5
    assert keywords  # sanity: the keywords exist but never appear as separate fields


def test_orders_differ_between_arms_but_cover_all_questions(prepared):
    root, _ = prepared
    orders = {a: json.loads((root / "size_50" / a / "order.json").read_text()) for a in ("treemem", "bm25", "grep")}
    assert len({tuple(o) for o in orders.values()}) == 3
    assert all(sorted(o) == sorted(orders["treemem"]) for o in orders.values()) and len(orders["treemem"]) == 50


def test_prompts_contain_arm_specific_rules(prepared):
    root, _ = prepared
    assert "ONLY its `search` tool" in (root / "size_50" / "bm25" / "prompt_batch_01.txt").read_text()
    assert "memory_log.md" in (root / "size_50" / "grep" / "prompt_batch_01.txt").read_text()
    assert "never call remember" in (root / "size_50" / "treemem" / "prompt_batch_01.txt").read_text()
    ws = root / "size_50" / "grep_workspace" / "memory_log.md"
    assert ws.exists() and "fact:" in ws.read_text()


def _write_answers(root, vault_root, arm, answer_fn):
    questions = json.loads(gen.questions_path(vault_root / "scaled_50").read_text())
    by_id = {q["id"]: q for q in questions}
    order = json.loads((root / "size_50" / arm / "order.json").read_text())
    for n in range(5):
        ids = order[n * 10:(n + 1) * 10]
        payload = [{"id": i, "answer": answer_fn(by_id[i])} for i in ids]
        (root / "size_50" / arm / f"answers_batch_{n + 1:02d}.json").write_text("```json\n" + json.dumps(payload) + "\n```")


def _correct_answer(q):
    if q["private"]:
        return mb.PRIVATE_ANSWER
    if q["negative"]:
        return mb.NOT_IN_MEMORY
    return " and ".join(q["keywords"])


def _write_events(root, arm, event_types):
    ev = root / "size_50" / "vaults" / arm / ".events"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "2026-01-01.jsonl").write_text("".join(json.dumps({"type": t}) + "\n" for t in event_types))


def test_grading_end_to_end_with_audit_and_paired_test(prepared):
    root, vault_root = prepared

    def perfect(q):
        if q["private"]:
            return mb.PRIVATE_ANSWER
        if q["negative"]:
            return mb.NOT_IN_MEMORY
        return " and ".join(q["keywords"])

    def poor(q):                       # answers only half of the answerable ones, leaks one secret
        if q["private"]:
            return f"It is {q['forbidden'][0]}" if q["id"].endswith("00") else mb.PRIVATE_ANSWER
        if q["negative"]:
            return mb.NOT_IN_MEMORY
        return " and ".join(q["keywords"]) if int(q["id"].split("_")[-1]) % 2 == 0 else mb.NOT_IN_MEMORY

    _write_answers(root, vault_root, "treemem", perfect)
    _write_answers(root, vault_root, "bm25", poor)
    # treemem used one allowed read tool per answered question; bm25 touched a non-search tool
    tev = root / "size_50" / "vaults" / "treemem" / ".events"
    tev.mkdir(exist_ok=True)
    (tev / "2026-01-01.jsonl").write_text("".join(json.dumps({"type": "search"}) + "\n" for _ in range(50)))
    ev = root / "size_50" / "vaults" / "bm25" / ".events"
    ev.mkdir(exist_ok=True)
    (ev / "2026-01-01.jsonl").write_text(json.dumps({"type": "search"}) + "\n" + json.dumps({"type": "recall"}) + "\n")

    s = gr.grade(50, root, vault_root)
    t, b = s["arms"]["treemem"], s["arms"]["bm25"]
    assert t["answerable"]["correct"] == t["answerable"]["n"] == 40
    assert t["private_leaks"] == 0 and b["private_leaks"] == 1
    assert b["answerable"]["correct"] < 40 and b["wrong_but_said_not_in_memory"] > 0
    assert any("other tools" in v for v in b["audit"]["violations"])
    assert t["audit"]["violations"] == []
    pair = next(p for p in s["paired"] if {p["a"], p["b"]} == {"treemem", "bm25"})
    assert pair["only_b_correct"] == 0 and pair["only_a_correct"] > 0 and pair["difference_detected"] is True
    # grep arm has no answers: all answerable questions counted wrong, never skipped
    g = s["arms"]["grep"]
    assert g["answerable"]["correct"] == 0 and g["answerable"]["n"] == 40 and g["missing_answers"] == 50
    assert "| treemem |" in gr.to_markdown(s)


def test_mcp_audit_zero_events_marks_arm_invalid(prepared, tmp_path):
    _, vault_root = prepared
    root = tmp_path / "runs_zero_events"
    mb.make(50, ["treemem", "bm25"], 10, 7, root, vault_root)
    for arm in ("treemem", "bm25"):
        _write_answers(root, vault_root, arm, _correct_answer)

    s = gr.grade(50, root, vault_root)
    for arm in ("treemem", "bm25"):
        audit = s["arms"][arm]["audit"]
        assert audit["total_events"] == 0
        assert any("no MCP tool calls recorded on this vault copy" in v for v in audit["violations"])

    md = gr.to_markdown(s)
    for arm in ("treemem", "bm25"):
        row = next(line for line in md.splitlines() if line.startswith(f"| {arm} |"))
        assert "INVALID" in row


def test_mcp_audit_normal_counts_have_no_violations(prepared, tmp_path):
    _, vault_root = prepared
    root = tmp_path / "runs_normal_counts"
    mb.make(50, ["treemem", "bm25"], 10, 7, root, vault_root)
    for arm in ("treemem", "bm25"):
        _write_answers(root, vault_root, arm, _correct_answer)
        _write_events(root, arm, ["search"] * 50)

    s = gr.grade(50, root, vault_root)
    assert s["protocol"] == "v1"
    for arm in ("treemem", "bm25"):
        audit = s["arms"][arm]["audit"]
        assert audit["total_events"] == 50
        assert audit["tool_calls_per_question"] == 1.0
        assert audit["violations"] == []

    md = gr.to_markdown(s)
    assert "Protocol v2" not in md
    for arm in ("treemem", "bm25"):
        row = next(line for line in md.splitlines() if line.startswith(f"| {arm} |"))
        assert "| OK |" in row
        assert "INVALID" not in row and "VIOLATION" not in row


def test_mcp_audit_low_call_counts_violate(prepared, tmp_path):
    _, vault_root = prepared
    root = tmp_path / "runs_low_counts"
    mb.make(50, ["treemem", "bm25"], 10, 7, root, vault_root)
    _write_answers(root, vault_root, "treemem", _correct_answer)
    _write_events(root, "treemem", ["search"] * 49)
    _write_answers(root, vault_root, "bm25", _correct_answer)
    _write_events(root, "bm25", ["search"] * 44)

    s = gr.grade(50, root, vault_root)
    assert any("expected at least 1 per question" in v for v in s["arms"]["treemem"]["audit"]["violations"])
    assert any("expected at least 0.9 per question" in v for v in s["arms"]["bm25"]["audit"]["violations"])

    md = gr.to_markdown(s)
    for arm in ("treemem", "bm25"):
        row = next(line for line in md.splitlines() if line.startswith(f"| {arm} |"))
        assert "VIOLATION" in row
        assert "INVALID" not in row


def test_grading_refuses_when_questions_changed(prepared):
    root, vault_root = prepared
    qfile = gen.questions_path(vault_root / "scaled_50")
    original = qfile.read_text()
    try:
        qfile.write_text(original.replace("Which", "Whichever", 1))
        with pytest.raises(SystemExit):
            gr.grade(50, root, vault_root)
    finally:
        qfile.write_text(original)


def test_protocol_phrases_are_graded_as_intended(prepared):
    """The exact phrases the prompts mandate must be accepted by the committed grader."""
    _, vault_root = prepared
    questions = json.loads(gen.questions_path(vault_root / "scaled_50").read_text())
    neg = next(q for q in questions if q["negative"])
    priv = next(q for q in questions if q["private"])
    from run_eval import grade_question
    assert grade_question(neg, mb.NOT_IN_MEMORY)["correct"] is True
    assert grade_question(priv, mb.PRIVATE_ANSWER) == {"correct": True, "leaked": False}
    ans = next(q for q in questions if not (q["negative"] or q["private"]))
    assert grade_question(ans, mb.NOT_IN_MEMORY)["correct"] is False
    assert "{NOT_IN_MEMORY}" not in (_prompt_text())


def _prompt_text():
    return mb.build_prompt("treemem", 1, 5, [{"id": "q", "question": "x?"}])
