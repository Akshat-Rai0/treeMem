"""Tests for bench/agent_eval/list_failures.py on v1 and v2 runs."""

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
from list_failures import get_failures


def test_list_failures_synthetic_v1_and_v2(tmp_path):
    vault_root = tmp_path / "vaults"
    gen.generate(50, 7, vault_root / "scaled_50", quiet=True, questions_v2=True)

    # Prepare v1 run
    root_v1 = tmp_path / "runs_v1"
    mb.make(50, ["treemem"], 10, 7, root=root_v1, vault_root=vault_root, protocol="v1")

    # Prepare v2 run
    root_v2 = tmp_path / "runs_v2"
    mb.make(50, ["treemem"], 10, 8, root=root_v2, vault_root=vault_root, protocol="v2")

    questions_v1 = json.loads(gen.questions_path(vault_root / "scaled_50").read_text())
    questions_v2 = json.loads(gen.questions_v2_path(vault_root / "scaled_50").read_text())

    # Write answers for v1: 10 correct, 20 abstained, 10 other wrong
    order_v1 = json.loads((root_v1 / "size_50" / "treemem" / "order.json").read_text())
    by_id_v1 = {q["id"]: q for q in questions_v1}
    ans_v1 = []
    for i, qid in enumerate(order_v1):
        q = by_id_v1[qid]
        if i < 10:
            ans_v1.append({"id": qid, "answer": " and ".join(q.get("keywords", ["x"]))})
        elif i < 30:
            ans_v1.append({"id": qid, "answer": mb.NOT_IN_MEMORY})
        else:
            ans_v1.append({"id": qid, "answer": "Completely wrong answer"})
    for n in range(5):
        batch = ans_v1[n * 10:(n + 1) * 10]
        (root_v1 / "size_50" / "treemem" / f"answers_batch_{n + 1:02d}.json").write_text(json.dumps(batch))

    res_v1 = get_failures(50, root=root_v1, vault_root=vault_root)
    assert res_v1["protocol"] == "v1"
    t_v1 = res_v1["arms"]["treemem"]
    assert len(t_v1["failures"]) > 0
    assert t_v1["counts"]["abstained"] > 0
    assert t_v1["counts"]["other"] > 0
    # Grounded should be None (n/a) in v1
    for f in t_v1["failures"]:
        assert f["grounded"] is None

    # Write answers for v2: mix of grounded, ungrounded, abstained
    order_v2 = json.loads((root_v2 / "size_50" / "treemem" / "order.json").read_text())
    by_id_v2 = {q["id"]: q for q in questions_v2}
    ans_v2 = []
    for i, qid in enumerate(order_v2):
        q = by_id_v2[qid]
        if i < 10:
            # Wrong: abstained
            ans_v2.append({"id": qid, "answer": mb.NOT_IN_MEMORY, "evidence": ""})
        elif i < 20:
            # Wrong: other, with grounded evidence
            ev = q.get("gold_facts", [""])[0] if q.get("gold_facts") else ""
            ans_v2.append({"id": qid, "answer": "Wrong answer text", "evidence": ev})
        elif i < 30:
            # Wrong: other, with ungrounded (fake) evidence
            ans_v2.append({"id": qid, "answer": "Wrong answer text", "evidence": "Fake line not in log"})
        else:
            # Correct
            ev = q.get("gold_facts", [""])[0] if q.get("gold_facts") else ""
            ans_v2.append({"id": qid, "answer": " and ".join(q.get("keywords", ["x"])), "evidence": ev})

    for n in range(5):
        batch = ans_v2[n * 10:(n + 1) * 10]
        (root_v2 / "size_50" / "treemem" / f"answers_batch_{n + 1:02d}.json").write_text(json.dumps(batch))

    res_v2 = get_failures(50, root=root_v2, vault_root=vault_root)
    assert res_v2["protocol"] == "v2"
    t_v2 = res_v2["arms"]["treemem"]
    assert len(t_v2["failures"]) > 0
    assert t_v2["counts"]["abstained"] > 0
    assert t_v2["counts"]["other"] > 0

    has_grounded = any(f["grounded"] is True for f in t_v2["failures"])
    has_ungrounded = any(f["grounded"] is False for f in t_v2["failures"])
    assert has_grounded
    assert has_ungrounded
