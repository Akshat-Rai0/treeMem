#!/usr/bin/env python3
"""Grade an agent-in-the-loop evaluation OFFLINE with the committed grader (bench/eval/run_eval.py).

    python bench/agent_eval/grade_agent_answers.py --size 1000

Reads  bench/agent_eval/runs/size_<N>/<arm>/answers_batch_XX.json  (the JSON array the agent printed;
code fences and surrounding text are tolerated), grades against the full question file and writes
summary.json and summary.md next to manifest.json.

Pre-registered rules (fixed before any result exists):
* PRIMARY metric: accuracy on ANSWERABLE questions (lookup + overview). A missing answer counts as wrong.
* Unanswerable: correct if the answer says the information is absent (harness negative phrases).
* Private: reported as leaks (secret in the answer). Private questions are NOT part of the accuracy
  comparison, because a grep-the-file arm has no privacy mechanism by construction.
* Arms are compared on the SAME questions with an exact McNemar test. A difference is called
  "detected" only if p < 0.05; otherwise the report says "not detected".
* Wilson 95% intervals. With about 40 answerable questions only differences of roughly 15 points or more can be detected.
* Audit: MCP arms must not have written to the vault, and the bm25 arm may only have used `search`.
"""

import argparse
import json
import re
import sys
from math import comb, sqrt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(HERE.parent.parent / "src"))

from make_scaled_vault import log_sha256, questions_path  # noqa: E402
from run_eval import NEGATIVE_KEYWORDS, grade_answer, grade_question  # noqa: E402

WRITE_EVENT_TYPES = {"remember", "place", "summary", "split", "rebuild", "compress", "auto_compress"}
BM25_ALLOWED = {"search"}


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(only_a: int, only_b: int) -> float:
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def parse_answers(text: str) -> List[Dict[str, Any]]:
    """Extract the JSON array of {id, answer} from an agent reply."""
    candidates = [text.strip()]
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except Exception:
            continue
        if isinstance(data, list) and all(isinstance(x, dict) and "id" in x and "answer" in x for x in data):
            return data
    raise ValueError("no JSON array of {id, answer} objects found")


def qtype(q: Dict[str, Any]) -> str:
    if q.get("private"):
        return "private"
    if q.get("negative"):
        return "unanswerable"
    return "overview" if q.get("require_all") else "lookup"


def load_arm_answers(arm_dir: Path) -> Tuple[Dict[str, str], List[str]]:
    answers: Dict[str, str] = {}
    problems: List[str] = []
    for f in sorted(arm_dir.glob("answers_batch_*.json")):
        try:
            for item in parse_answers(f.read_text(encoding="utf-8")):
                if item["id"] in answers:
                    problems.append(f"duplicate answer for {item['id']} in {f.name}")
                answers[item["id"]] = str(item["answer"])
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{f.name}: {exc}")
    return answers, problems


def audit_events(vault_dir: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    ev = vault_dir / ".events"
    if ev.exists():
        for f in sorted(ev.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        t = json.loads(line).get("type", "?")
                    except Exception:
                        continue
                    counts[t] = counts.get(t, 0) + 1
    return counts


def grade(size: int, root: Path, vault_root: Path) -> Dict[str, Any]:
    out = root / f"size_{size}"
    manifest = json.loads((out / "manifest.json").read_text())
    qfile = questions_path(vault_root / f"scaled_{size}")
    questions = json.loads(qfile.read_text(encoding="utf-8"))
    from make_scaled_vault import file_sha256
    if file_sha256(qfile) != manifest["questions_sha256"]:
        raise SystemExit("ERROR: the questions file changed since the batches were prepared; results would be invalid")
    by_id = {q["id"]: q for q in questions}

    arms = [a for a in manifest["arms"] if (out / a).exists()]
    per_arm: Dict[str, Any] = {}
    outcomes: Dict[str, Dict[str, bool]] = {}
    for arm in arms:
        answers, problems = load_arm_answers(out / arm)
        unknown = sorted(set(answers) - set(by_id))
        if unknown:
            problems.append(f"unknown question ids: {unknown[:5]}")
        types: Dict[str, Dict[str, int]] = {}
        answerable_ok: Dict[str, bool] = {}
        wrong_abstained = wrong_other = missing = leaks = 0
        for q in questions:
            t = qtype(q)
            slot = types.setdefault(t, {"n": 0, "correct": 0, "missing": 0})
            slot["n"] += 1
            if q["id"] not in answers:
                slot["missing"] += 1
                missing += 1
                if t in ("lookup", "overview"):
                    answerable_ok[q["id"]] = False
                    wrong_other += 1
                continue
            ans = answers[q["id"]]
            g = grade_question(q, ans)
            slot["correct"] += int(g["correct"])
            if t == "private" and g["leaked"]:
                leaks += 1
            if t in ("lookup", "overview"):
                answerable_ok[q["id"]] = bool(g["correct"])
                if not g["correct"]:
                    if grade_answer(ans, NEGATIVE_KEYWORDS):
                        wrong_abstained += 1
                    else:
                        wrong_other += 1
        n = len(answerable_ok)
        k = sum(answerable_ok.values())
        lo, hi = wilson(k, n)
        entry: Dict[str, Any] = {
            "answerable": {"n": n, "correct": k, "rate": round(k / n, 4) if n else 0.0, "wilson95": [round(lo, 4), round(hi, 4)]},
            "wrong_but_said_not_in_memory": wrong_abstained,
            "wrong_with_other_answer_or_missing": wrong_other,
            "missing_answers": missing,
            "private_leaks": leaks,
            "per_type": types,
            "problems": problems,
        }
        if arm in ("treemem", "bm25"):
            vault = out / "vaults" / arm
            counts = audit_events(vault)
            violations = []
            if log_sha256(vault) != manifest["log_sha256"]:
                violations.append("vault log changed during the run")
            if arm == "bm25" and set(counts) - BM25_ALLOWED:
                violations.append(f"bm25 arm used other tools: {sorted(set(counts) - BM25_ALLOWED)}")
            if arm == "treemem" and set(counts) & WRITE_EVENT_TYPES:
                violations.append(f"treemem arm wrote to memory: {sorted(set(counts) & WRITE_EVENT_TYPES)}")
            entry["audit"] = {"event_counts": counts, "violations": violations}
        per_arm[arm] = entry
        outcomes[arm] = answerable_ok

    paired = []
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            ids = sorted(set(outcomes[a]) & set(outcomes[b]))
            only_a = sum(1 for x in ids if outcomes[a][x] and not outcomes[b][x])
            only_b = sum(1 for x in ids if outcomes[b][x] and not outcomes[a][x])
            p = mcnemar_exact(only_a, only_b)
            paired.append({"a": a, "b": b, "n": len(ids), "only_a_correct": only_a, "only_b_correct": only_b,
                           "both_correct": sum(1 for x in ids if outcomes[a][x] and outcomes[b][x]),
                           "neither_correct": sum(1 for x in ids if not outcomes[a][x] and not outcomes[b][x]),
                           "p_exact": round(p, 4), "difference_detected": p < 0.05})
    return {"size": size, "questions_sha256": manifest["questions_sha256"], "arms": per_arm, "paired": paired}


def to_markdown(s: Dict[str, Any]) -> str:
    lines = [f"# Agent-in-the-loop accuracy, size {s['size']}", "",
             "| Arm | Answerable correct | Rate | 95% CI | Wrong: said not in memory | Wrong: other/missing | Private leaks | Audit |",
             "|---|---|---|---|---|---|---|---|"]
    for arm, e in s["arms"].items():
        a = e["answerable"]
        audit = "n/a" if "audit" not in e else ("OK" if not e["audit"]["violations"] else "VIOLATION: " + "; ".join(e["audit"]["violations"]))
        lines.append(f"| {arm} | {a['correct']}/{a['n']} | {a['rate']:.1%} | {a['wilson95'][0]:.1%} to {a['wilson95'][1]:.1%} | "
                     f"{e['wrong_but_said_not_in_memory']} | {e['wrong_with_other_answer_or_missing']} | {e['private_leaks']} | {audit} |")
    lines += ["", "## Paired comparisons (same questions, exact McNemar)", "",
              "| A | B | only A right | only B right | p | detected |", "|---|---|---|---|---|---|"]
    for p in s["paired"]:
        lines.append(f"| {p['a']} | {p['b']} | {p['only_a_correct']} | {p['only_b_correct']} | {p['p_exact']} | {'yes' if p['difference_detected'] else 'no'} |")
    lines += ["", "## Per question type", ""]
    for arm, e in s["arms"].items():
        parts = ", ".join(f"{t}: {v['correct']}/{v['n']}" for t, v in sorted(e["per_type"].items()))
        lines.append(f"- {arm}: {parts}")
        for pr in e["problems"]:
            lines.append(f"  - PROBLEM: {pr}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Grade an agent-in-the-loop evaluation offline")
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--root", default=str(HERE / "runs"))
    ap.add_argument("--vault-root", default=str(HERE.parent / "vaults"))
    args = ap.parse_args()
    s = grade(args.size, Path(args.root), Path(args.vault_root))
    out = Path(args.root) / f"size_{args.size}"
    (out / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(to_markdown(s), encoding="utf-8")
    print(to_markdown(s))


if __name__ == "__main__":
    main()
