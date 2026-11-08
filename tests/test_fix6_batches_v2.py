"""Tests for WP2: v2 prompts, batches, and manifests."""

import json
from pathlib import Path

import pytest

import make_scaled_vault as gen
import make_batches as mb


@pytest.fixture(scope="module")
def prepared_v2(tmp_path_factory):
    base = tmp_path_factory.mktemp("agent_eval_v2")
    vault_root = base / "vaults"
    gen.generate(50, 7, vault_root / "scaled_50", quiet=True, questions_v2=True)
    root = base / "runs_v2"
    manifest = mb.make(50, ["treemem", "bm25", "grep"], batch_size=10, seed=8,
                       root=root, vault_root=vault_root, protocol="v2")
    return root, vault_root, manifest


def test_v2_manifest_properties(prepared_v2):
    root, vault_root, manifest = prepared_v2
    mfile = root / "size_50" / "manifest.json"
    assert mfile.exists()
    data = json.loads(mfile.read_text(encoding="utf-8"))
    assert data["protocol"] == "v2"
    assert data["evidence_required"] is True
    assert "questions_file" in data
    assert "questions_sha256" in data
    assert data["seed"] == 8


def test_v2_prompts_contain_minimum_effort_and_evidence_rule(prepared_v2):
    root, _, _ = prepared_v2
    for arm in ("treemem", "bm25", "grep"):
        prompt = (root / "size_50" / arm / "prompt_batch_01.txt").read_text(encoding="utf-8")
        assert "You may answer `No information in memory.` ONLY after" in prompt
        assert "Evidence = the memory text you relied on, copied exactly" in prompt
        assert "evidence" in prompt
        assert '{"id": "<question id>", "answer": "<your answer>", "evidence": "<memory text>"}' in prompt
        # Arm-specific tips
        if arm == "treemem":
            assert "Use both recall (descent) and search" in prompt
        elif arm == "bm25":
            assert "Search several times with different distinctive words (limit 5 each)" in prompt
        elif arm == "grep":
            assert "Use grep -i -n with a distinctive word" in prompt


def test_v2_batches_hold_answerable_and_safety_separately(prepared_v2):
    root, vault_root, _ = prepared_v2
    qfile = gen.questions_v2_path(vault_root / "scaled_50")
    questions = json.loads(qfile.read_text(encoding="utf-8"))
    answerable_ids = {q["id"] for q in questions if not (q["private"] or q["negative"])}
    safety_ids = {q["id"] for q in questions if q["private"] or q["negative"]}

    assert len(answerable_ids) == 40
    assert len(safety_ids) == 10

    for arm in ("treemem", "bm25", "grep"):
        arm_dir = root / "size_50" / arm

        # Batches 01 to 04: answerable
        b1_to_b4_ids = []
        for n in range(1, 5):
            batch_data = json.loads((arm_dir / f"batch_{n:02d}_questions.json").read_text(encoding="utf-8"))
            assert len(batch_data) == 10
            b_ids = [item["id"] for item in batch_data]
            b1_to_b4_ids.extend(b_ids)

        assert set(b1_to_b4_ids) == answerable_ids
        assert len(b1_to_b4_ids) == 40

        # Batch 05: safety
        b5_data = json.loads((arm_dir / "batch_05_questions.json").read_text(encoding="utf-8"))
        assert len(b5_data) == 10
        b5_ids = [item["id"] for item in b5_data]
        assert set(b5_ids) == safety_ids


def test_no_keywords_gold_facts_or_flags_in_batch_or_prompt(prepared_v2):
    root, vault_root, _ = prepared_v2
    qfile = gen.questions_v2_path(vault_root / "scaled_50")
    questions = json.loads(qfile.read_text(encoding="utf-8"))
    secrets = [s for q in questions for s in q.get("forbidden", [])]
    golds = [f for q in questions for f in q.get("gold_facts", [])]
    keywords = {k for q in questions for k in q.get("keywords", [])}

    for arm in ("treemem", "bm25", "grep"):
        for f in (root / "size_50" / arm).glob("*"):
            text = f.read_text(encoding="utf-8")
            for s in secrets:
                assert s not in text
            if f.name.startswith("batch_") or f.name.startswith("prompt_"):
                for g in golds:
                    assert g not in text
                if f.suffix == ".json":
                    data = json.loads(text)
                    for item in data:
                        assert set(item) == {"id", "question"}
                        assert "keywords" not in item
                        assert "gold_facts" not in item
                        assert "flags" not in item
                        assert "private" not in item
                        assert "negative" not in item
                        assert "composite" not in item


def test_v1_make_behavior_unchanged(tmp_path):
    vault_root = tmp_path / "vaults"
    gen.generate(50, 7, vault_root / "scaled_50", quiet=True)
    root = tmp_path / "runs"
    manifest = mb.make(50, ["treemem", "bm25", "grep"], 10, 7, root, vault_root)

    # v1 manifest does NOT have "protocol": "v2"
    assert "protocol" not in manifest
    assert "evidence_required" not in manifest

    # v1 prompt does NOT have minimum effort rule
    prompt = (root / "size_50" / "treemem" / "prompt_batch_01.txt").read_text(encoding="utf-8")
    assert "You may answer `No information in memory.` ONLY after" not in prompt
    assert '[{"id": "<question id>", "answer": "<your answer>"}, ...]' in prompt
