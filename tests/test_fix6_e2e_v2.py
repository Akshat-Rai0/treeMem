"""End-to-end test running the three v2 CLI commands on a size-50 vault."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_v2_end_to_end_cli(tmp_path):
    vault_root = tmp_path / "vaults"
    vault_dir = vault_root / "scaled_50"
    runs_dir = tmp_path / "runs_v2"

    # Command 1: make_scaled_vault
    cmd1 = [
        sys.executable,
        str(ROOT / "bench" / "make_scaled_vault.py"),
        "--facts", "50",
        "--seed", "7",
        "--out", str(vault_dir),
        "--questions-v2",
    ]
    res1 = subprocess.run(cmd1, cwd=str(ROOT), capture_output=True, text=True, env={"PYTHONPATH": f"src:{ROOT}/bench"})
    assert res1.returncode == 0, f"make_scaled_vault failed:\n{res1.stderr}"
    assert (vault_root / "scaled_50_questions_v2.json").exists()
    assert (vault_root / "scaled_50_manifest_v2.json").exists()

    # Command 2: make_batches
    cmd2 = [
        sys.executable,
        str(ROOT / "bench" / "agent_eval" / "make_batches.py"),
        "--size", "50",
        "--protocol", "v2",
        "--root", str(runs_dir),
        "--vault-root", str(vault_root),
    ]
    res2 = subprocess.run(cmd2, cwd=str(ROOT), capture_output=True, text=True, env={"PYTHONPATH": f"src:{ROOT}/bench:{ROOT}/bench/agent_eval"})
    assert res2.returncode == 0, f"make_batches failed:\n{res2.stderr}"
    assert (runs_dir / "size_50" / "manifest.json").exists()
    assert (runs_dir / "size_50" / "treemem" / "prompt_batch_01.txt").exists()

    # Create synthetic answers for treemem arm (batches 1-4)
    questions = json.loads((vault_root / "scaled_50_questions_v2.json").read_text())
    by_id = {q["id"]: q for q in questions}
    order = json.loads((runs_dir / "size_50" / "treemem" / "order.json").read_text())

    for n in range(4):
        batch_ids = order[n * 10:(n + 1) * 10]
        batch_payload = []
        for qid in batch_ids:
            q = by_id[qid]
            ans = " and ".join(q.get("keywords", ["ans"]))
            ev = "\n".join(q.get("gold_facts", []))
            batch_payload.append({"id": qid, "answer": ans, "evidence": ev})
        (runs_dir / "size_50" / "treemem" / f"answers_batch_{n + 1:02d}.json").write_text(json.dumps(batch_payload))

    # Command 3: grade_agent_answers
    cmd3 = [
        sys.executable,
        str(ROOT / "bench" / "agent_eval" / "grade_agent_answers.py"),
        "--size", "50",
        "--root", str(runs_dir),
        "--vault-root", str(vault_root),
    ]
    res3 = subprocess.run(cmd3, cwd=str(ROOT), capture_output=True, text=True, env={"PYTHONPATH": f"src:{ROOT}/bench:{ROOT}/bench/agent_eval"})
    assert res3.returncode == 0, f"grade_agent_answers failed:\n{res3.stderr}"
    assert (runs_dir / "size_50" / "summary.json").exists()
    assert (runs_dir / "size_50" / "summary.md").exists()

    summary = json.loads((runs_dir / "size_50" / "summary.json").read_text())
    assert summary["protocol"] == "v2"
    assert summary["arms"]["treemem"]["answerable"]["correct"] == 40
    assert summary["arms"]["treemem"]["grounding"]["grounded_correct"] == 40
    assert summary["arms"]["treemem"]["safety"] == "not run"
