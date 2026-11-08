"""Tests for WP3: Grade v2 with evidence grounding, safety handling, and comparisons."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "eval"))
sys.path.insert(0, str(ROOT / "bench" / "agent_eval"))

import make_scaled_vault as gen
import make_batches as mb
import grade_agent_answers as gr


@pytest.fixture
def v2_env(tmp_path):
    vault_root = tmp_path / "vaults"
    gen.generate(50, 7, vault_root / "scaled_50", quiet=True, questions_v2=True)
    root = tmp_path / "runs_v2"
    mb.make(50, ["treemem", "bm25", "grep"], 10, 8, root=root,
            vault_root=vault_root, protocol="v2")
    return root, vault_root


def _write_arm_answers(root, arm, answers_dict, num_batches=5):
    order = json.loads((root / "size_50" / arm / "order.json").read_text())
    for n in range(num_batches):
        ids = order[n * 10:(n + 1) * 10]
        payload = []
        for i in ids:
            rec = answers_dict.get(i, {"answer": mb.NOT_IN_MEMORY, "evidence": ""})
            payload.append({"id": i, "answer": rec["answer"], "evidence": rec.get("evidence", "")})
        (root / "size_50" / arm / f"answers_batch_{n + 1:02d}.json").write_text(json.dumps(payload))


def test_perfect_and_abstaining_and_grounding(v2_env):
    root, vault_root = v2_env
    questions = json.loads(gen.questions_v2_path(vault_root / "scaled_50").read_text())

    # Perfect arm with exact gold facts as evidence
    perfect_answers = {}
    for q in questions:
        if q["private"]:
            perfect_answers[q["id"]] = {"answer": mb.PRIVATE_ANSWER, "evidence": ""}
        elif q["negative"]:
            perfect_answers[q["id"]] = {"answer": mb.NOT_IN_MEMORY, "evidence": ""}
        else:
            ans = " and ".join(q["keywords"])
            ev = "\n".join(q.get("gold_facts", []))
            perfect_answers[q["id"]] = {"answer": ans, "evidence": ev}

    # Abstaining arm (quits on all answerable questions)
    abstaining_answers = {}
    for q in questions:
        abstaining_answers[q["id"]] = {"answer": mb.NOT_IN_MEMORY, "evidence": ""}

    _write_arm_answers(root, "treemem", perfect_answers)
    _write_arm_answers(root, "bm25", abstaining_answers)

    res = gr.grade(50, root, vault_root)

    t = res["arms"]["treemem"]
    assert t["answerable"]["correct"] == 40
    assert t["answerable"]["n"] == 40
    assert t["lookup"]["correct"] == 30
    assert t["composite"]["correct"] == 10
    assert t["grounding"]["grounded_correct"] == 40
    assert t["grounding"]["ungrounded_correct"] == 0
    assert t["grounding"]["missing_evidence"] == 0
    assert t["grounding"]["fabricated_evidence"] == 0

    b = res["arms"]["bm25"]
    assert b["answerable"]["correct"] == 0
    assert b["wrong_but_said_not_in_memory"] == 40


def test_fabricated_evidence_and_missing_evidence(v2_env):
    root, vault_root = v2_env
    questions = json.loads(gen.questions_v2_path(vault_root / "scaled_50").read_text())

    answers = {}
    for idx, q in enumerate(questions):
        if q["private"]:
            answers[q["id"]] = {"answer": mb.PRIVATE_ANSWER, "evidence": ""}
        elif q["negative"]:
            answers[q["id"]] = {"answer": mb.NOT_IN_MEMORY, "evidence": ""}
        else:
            ans = " and ".join(q["keywords"])
            # First 20: fabricated evidence line
            if idx < 20:
                ev = "Totally fake fabricated line that never appears in the log."
            # Next 20: missing evidence
            else:
                ev = ""
            answers[q["id"]] = {"answer": ans, "evidence": ev}

    _write_arm_answers(root, "treemem", answers)
    res = gr.grade(50, root, vault_root)
    t = res["arms"]["treemem"]

    assert t["answerable"]["correct"] == 40
    assert t["grounding"]["grounded_correct"] == 0
    assert t["grounding"]["ungrounded_correct"] == 40
    assert t["grounding"]["fabricated_evidence"] == 20
    assert t["grounding"]["missing_evidence"] == 20


def test_safety_batch_absent(v2_env):
    root, vault_root = v2_env
    questions = json.loads(gen.questions_v2_path(vault_root / "scaled_50").read_text())

    # Only supply batches 1-4 (40 answerable questions)
    answers = {}
    for q in questions:
        if not (q["private"] or q["negative"]):
            answers[q["id"]] = {"answer": " and ".join(q["keywords"]), "evidence": "\n".join(q.get("gold_facts", []))}

    _write_arm_answers(root, "treemem", answers, num_batches=4)
    res = gr.grade(50, root, vault_root)
    t = res["arms"]["treemem"]

    assert t["safety"] == "not run"
    assert t["missing_answers"] == 0
    assert t["answerable"]["correct"] == 40


def test_bonferroni_threshold_flips_p_031_to_not_detected(v2_env):
    root, vault_root = v2_env
    questions = json.loads(gen.questions_v2_path(vault_root / "scaled_50").read_text())
    answerable_qs = [q for q in questions if not (q["private"] or q["negative"])]

    # Exactly 6 discordant questions: only_a = 6, only_b = 0
    # mcnemar_exact(6, 0) == 2 * (1/64) = 0.03125
    # p = 0.03125 < 0.05 (v1 detected), but p = 0.03125 >= 0.0167 (v2 NOT detected)
    treemem_answers = {}
    bm25_answers = {}

    for i, q in enumerate(answerable_qs):
        corr_ans = " and ".join(q["keywords"])
        gold_ev = "\n".join(q.get("gold_facts", []))
        if i < 6:
            # treemem right, bm25 wrong
            treemem_answers[q["id"]] = {"answer": corr_ans, "evidence": gold_ev}
            bm25_answers[q["id"]] = {"answer": mb.NOT_IN_MEMORY, "evidence": ""}
        else:
            # both right
            treemem_answers[q["id"]] = {"answer": corr_ans, "evidence": gold_ev}
            bm25_answers[q["id"]] = {"answer": corr_ans, "evidence": gold_ev}

    _write_arm_answers(root, "treemem", treemem_answers, num_batches=4)
    _write_arm_answers(root, "bm25", bm25_answers, num_batches=4)

    res = gr.grade(50, root, vault_root)
    pair = next(p for p in res["paired"] if {p["a"], p["b"]} == {"treemem", "bm25"})

    assert pair["only_a_correct"] == 6
    assert pair["only_b_correct"] == 0
    assert pair["p_exact"] == pytest.approx(0.0312, abs=0.001)
    # Under v2 Bonferroni (alpha = 0.0167), this must NOT be detected!
    assert pair["difference_detected"] is False


def test_compare_with_on_synthetic_runs(tmp_path):
    vault_root = tmp_path / "vaults"
    gen.generate(50, 7, vault_root / "scaled_50", quiet=True, questions_v2=True)

    root_v1 = tmp_path / "runs_old"
    root_v2 = tmp_path / "runs_new"

    mb.make(50, ["treemem"], 10, 7, root=root_v1, vault_root=vault_root, protocol="v1")
    mb.make(50, ["treemem"], 10, 8, root=root_v2, vault_root=vault_root, protocol="v2")

    questions = json.loads(gen.questions_v2_path(vault_root / "scaled_50").read_text())
    lookups = [q for q in questions if gr.qtype(q) == "lookup"]
    assert len(lookups) == 30

    # Old run answers 10 correctly (first 10)
    old_answers = {}
    for i, q in enumerate(lookups):
        if i < 10:
            old_answers[q["id"]] = {"answer": " and ".join(q["keywords"])}
        else:
            old_answers[q["id"]] = {"answer": mb.NOT_IN_MEMORY}

    # New run answers 15 correctly (first 5, and 10 to 20)
    # Common (both): first 5 -> 5
    # Only old: 5 to 10 -> 5
    # Only new: 10 to 20 -> 10
    # Neither: 20 to 30 -> 10
    new_answers = {}
    for i, q in enumerate(lookups):
        if i < 5 or (10 <= i < 20):
            new_answers[q["id"]] = {"answer": " and ".join(q["keywords"]), "evidence": "\n".join(q.get("gold_facts", []))}
        else:
            new_answers[q["id"]] = {"answer": mb.NOT_IN_MEMORY, "evidence": ""}

    _write_arm_answers(root_v1, "treemem", old_answers, num_batches=5)
    _write_arm_answers(root_v2, "treemem", new_answers, num_batches=5)

    res = gr.grade(50, root_v2, vault_root, compare_with=root_v1)
    assert "compare_with" in res
    comp = res["compare_with"]["treemem"]
    assert comp["n"] == 30
    assert comp["only_new_correct"] == 10
    assert comp["only_old_correct"] == 5
    assert comp["both_correct"] == 5
    assert comp["neither_correct"] == 10
    assert comp["p_exact"] == pytest.approx(gr.mcnemar_exact(10, 5), abs=1e-4)
