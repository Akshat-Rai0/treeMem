"""Runner guarantees: hashes on every row, no mixing of question sets, transient failures are retried."""
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
rs = _load("run_scaling", "bench/run_scaling.py")


class FakePool:
    def __init__(self, keys):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "vaults"
    gen.generate(50, 7, root / "scaled_50", quiet=True)
    results = tmp_path / "results"
    monkeypatch.setattr(rs, "VAULT_ROOT", root)
    monkeypatch.setattr(rs, "RESULT_DIR", results)
    monkeypatch.setattr(rs, "PROGRESS_FILE", results / "progress.jsonl")
    monkeypatch.setattr(rs, "INVALIDATED_FILE", results / "invalidated.jsonl")
    monkeypatch.setattr(rs, "PLAN_FILE", tmp_path / "plan.md")
    monkeypatch.setattr(rs, "load_groq_keys", lambda: ["k"])
    monkeypatch.setattr(rs, "GroqKeyPool", FakePool)
    monkeypatch.setattr(rs, "_pace", lambda *_: None)
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **k: None)
    state = {"calls": 0, "fail_first": 0}

    def fake_chat(client, payload):
        state["calls"] += 1
        if state["fail_first"] > 0:
            state["fail_first"] -= 1
            raise RuntimeError("HTTP 500 upstream")
        return ({"choices": [{"message": {"content": "I do not know."}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}, 0.01)

    monkeypatch.setattr(rs, "timed_chat", fake_chat)
    return state, results


def _rows(results):
    p = results / "progress.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def test_every_row_carries_current_hashes(env):
    state, results = env
    rs.run_scaling(sizes=[50], arms=["rag_bm25"], runs=1, smoke_only=True)
    rows = _rows(results)
    assert rows
    fp = rs.vault_fingerprint(50)
    for r in rows:
        assert r["questions_sha"] == fp["questions_sha"] and r["vault_sha"] == fp["vault_sha"]
        assert r["generator"] == gen.GENERATOR_VERSION


def test_stale_rows_stop_the_run_and_can_be_invalidated(env):
    state, results = env
    results.mkdir(parents=True, exist_ok=True)
    stale = {"size": 50, "arm": "flat", "run": 1, "question_id": "q_lookup_00", "outcome": "ok",
             "questions_sha": "old", "vault_sha": "old", "correct": False}
    unhashed = {"size": 50, "arm": "flat", "run": 1, "question_id": "q_lookup_01", "outcome": "ok", "correct": False}
    (results / "progress.jsonl").write_text(json.dumps(stale) + "\n" + json.dumps(unhashed) + "\n")
    with pytest.raises(SystemExit) as exc:
        rs.run_scaling(sizes=[50], arms=["rag_bm25"], runs=1, smoke_only=True)
    assert exc.value.code == 2
    assert state["calls"] == 0
    rs.run_scaling(sizes=[50], arms=["rag_bm25"], runs=1, smoke_only=True, invalidate_stale=True)
    moved = [json.loads(l) for l in (results / "invalidated.jsonl").read_text().splitlines()]
    assert len(moved) == 2 and all("invalidation_reason" in m for m in moved)
    assert all(r["arm"] != "flat" for r in _rows(results))


def test_transient_failures_are_retried_not_frozen(env):
    state, results = env
    state["fail_first"] = 3                      # first three smoke episodes fail with HTTP 500
    rs.run_scaling(sizes=[50], arms=["rag_bm25"], runs=1, smoke_only=True)
    first = _rows(results)
    assert [r["outcome"] for r in first] == ["api_error"] * 3
    rs.run_scaling(sizes=[50], arms=["rag_bm25"], runs=1, smoke_only=True)   # resume
    outcomes = [r["outcome"] for r in _rows(results)]
    assert outcomes.count("ok") == 3             # the three failed episodes were rerun


def test_one_manager_per_size_arm_run_not_per_episode(env, monkeypatch):
    state, results = env
    built = {"n": 0}
    real = rs.PreparedVault.__init__

    def counting(self, vault_dir):
        built["n"] += 1
        real(self, vault_dir)

    monkeypatch.setattr(rs.PreparedVault, "__init__", counting)
    rs.run_scaling(sizes=[50], arms=["rag_bm25", "tree_follow"], runs=1, smoke_only=True)
    assert built["n"] == 2                       # 2 arms x 3 smoke questions -> 2 vault copies, not 6
