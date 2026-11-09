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

from make_scaled_vault import file_sha256, log_sha256, questions_path, questions_v2_path  # noqa: E402
from run_eval import NEGATIVE_KEYWORDS, grade_answer, grade_question  # noqa: E402
from treemem.log_writer import LogWriter  # noqa: E402

DEFAULT_ROOT = HERE / "runs"
DEFAULT_ROOT_V2 = HERE / "runs_v2"

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
    if q.get("composite"):
        return "composite"
    return "overview" if q.get("require_all") else "lookup"


def normalize_evidence_text(text: str) -> str:
    """Normalize text: lowercase, collapse whitespace, strip surrounding quotes and list bullets."""
    t = text.lower().strip()
    t = re.sub(r"^[\s*\-•]+", "", t)
    t = re.sub(r"^\d+[\.\)]\s*", "", t)
    t = t.strip("\"'“”‘’`")
    t = re.sub(r"\s+", " ", t).strip()
    return t


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


def load_arm_records(arm_dir: Path) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    records: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    for f in sorted(arm_dir.glob("answers_batch_*.json")):
        try:
            for item in parse_answers(f.read_text(encoding="utf-8")):
                qid = item["id"]
                if qid in records:
                    problems.append(f"duplicate answer for {qid} in {f.name}")
                records[qid] = {
                    "answer": str(item["answer"]),
                    "evidence": str(item.get("evidence", "")),
                }
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{f.name}: {exc}")
    return records, problems


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


def grade(size: int, root: Path, vault_root: Path,
          compare_with: Optional[Path] = None) -> Dict[str, Any]:
    out = root / f"size_{size}"
    manifest = json.loads((out / "manifest.json").read_text())
    is_v2 = manifest.get("protocol") == "v2"

    if manifest.get("questions_file"):
        qfile = Path(manifest["questions_file"])
    elif is_v2:
        qfile = questions_v2_path(vault_root / f"scaled_{size}")
    else:
        qfile = questions_path(vault_root / f"scaled_{size}")

    questions = json.loads(qfile.read_text(encoding="utf-8"))
    if file_sha256(qfile) != manifest["questions_sha256"]:
        raise SystemExit("ERROR: the questions file changed since the batches were prepared; results would be invalid")
    by_id = {q["id"]: q for q in questions}

    # Prepare normalized facts corpus for v2 evidence grounding
    norm_facts: List[str] = []
    if is_v2:
        vault_dir = vault_root / f"scaled_{size}"
        lw = LogWriter(vault_dir)
        entries = lw.read_all_entries()
        norm_facts = [normalize_evidence_text(e["fact"]) for e in entries if "fact" in e]

    arms = [a for a in manifest["arms"] if (out / a).exists()]
    per_arm: Dict[str, Any] = {}
    outcomes: Dict[str, Dict[str, bool]] = {}

    safety_ids = [q["id"] for q in questions if qtype(q) in ("private", "unanswerable")]

    for arm in arms:
        records, problems = load_arm_records(out / arm)
        answers = {qid: r["answer"] for qid, r in records.items()}
        unknown = sorted(set(answers) - set(by_id))
        if unknown:
            problems.append(f"unknown question ids: {unknown[:5]}")

        # Safety batch check for v2: if all 10 safety ids are missing for an arm, report 'safety: not run'
        safety_run = any(qid in answers for qid in safety_ids)

        types: Dict[str, Dict[str, int]] = {}
        answerable_ok: Dict[str, bool] = {}
        lookup_ok: Dict[str, bool] = {}
        composite_ok: Dict[str, bool] = {}

        grounded_correct = 0
        ungrounded_correct = 0
        missing_evidence = 0
        fabricated_evidence = 0

        wrong_abstained = wrong_other = missing = leaks = 0

        for q in questions:
            t = qtype(q)
            is_ans = t in ("lookup", "composite", "overview")

            if q["id"] not in answers:
                if is_v2 and not safety_run and t in ("private", "unanswerable"):
                    # Safety batch was not run: do not count as failures or missing
                    continue
                slot = types.setdefault(t, {"n": 0, "correct": 0, "missing": 0})
                slot["n"] += 1
                slot["missing"] += 1
                missing += 1
                if is_ans:
                    answerable_ok[q["id"]] = False
                    if t == "lookup":
                        lookup_ok[q["id"]] = False
                    elif t == "composite":
                        composite_ok[q["id"]] = False
                    wrong_other += 1
                continue

            slot = types.setdefault(t, {"n": 0, "correct": 0, "missing": 0})
            slot["n"] += 1
            rec = records[q["id"]]
            ans = rec["answer"]
            ev = rec["evidence"]
            g = grade_question(q, ans)
            slot["correct"] += int(g["correct"])

            if t == "private" and g["leaked"]:
                leaks += 1

            if is_ans:
                corr = bool(g["correct"])
                answerable_ok[q["id"]] = corr
                if t == "lookup":
                    lookup_ok[q["id"]] = corr
                elif t == "composite":
                    composite_ok[q["id"]] = corr

                if not corr:
                    if grade_answer(ans, NEGATIVE_KEYWORDS):
                        wrong_abstained += 1
                    else:
                        wrong_other += 1

                if is_v2:
                    ev_lines = [normalize_evidence_text(line) for line in ev.splitlines() if normalize_evidence_text(line)]
                    if not ev_lines:
                        if not grade_answer(ans, NEGATIVE_KEYWORDS):
                            missing_evidence += 1
                        is_grounded = False
                    else:
                        has_fabrication = False
                        for eline in ev_lines:
                            if not any(eline in f for f in norm_facts):
                                has_fabrication = True
                                break
                        if has_fabrication:
                            fabricated_evidence += 1
                            is_grounded = False
                        else:
                            is_grounded = True

                    if corr:
                        if is_grounded:
                            grounded_correct += 1
                        else:
                            ungrounded_correct += 1

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

        if is_v2:
            entry["lookup"] = {
                "n": len(lookup_ok),
                "correct": sum(lookup_ok.values()),
                "rate": round(sum(lookup_ok.values()) / len(lookup_ok), 4) if lookup_ok else 0.0,
            }
            entry["composite"] = {
                "n": len(composite_ok),
                "correct": sum(composite_ok.values()),
                "rate": round(sum(composite_ok.values()) / len(composite_ok), 4) if composite_ok else 0.0,
            }
            entry["grounding"] = {
                "grounded_correct": grounded_correct,
                "ungrounded_correct": ungrounded_correct,
                "missing_evidence": missing_evidence,
                "fabricated_evidence": fabricated_evidence,
            }
            entry["safety"] = "not run" if not safety_run else "run"

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
            total_events = sum(counts.values())
            answered_count = len([qid for qid in answers if qid in by_id])
            raw_calls_per_q = total_events / answered_count if answered_count else 0.0
            calls_per_q = round(raw_calls_per_q, 2)
            if total_events == 0:
                violations.append("no MCP tool calls recorded on this vault copy (server not used or pointed at another vault)")
            min_calls_per_q = {"treemem": 1.0, "bm25": 0.9}[arm]
            if answered_count and raw_calls_per_q < min_calls_per_q:
                violations.append(f"{arm} arm recorded {total_events} tool calls for {answered_count} answered questions (expected at least {min_calls_per_q:g} per question)")
            entry["audit"] = {
                "event_counts": counts,
                "total_events": total_events,
                "tool_calls_per_question": calls_per_q,
                "violations": violations,
            }

        per_arm[arm] = entry
        outcomes[arm] = answerable_ok

    paired = []
    p_threshold = 0.0167 if is_v2 else 0.05
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            ids = sorted(set(outcomes[a]) & set(outcomes[b]))
            only_a = sum(1 for x in ids if outcomes[a][x] and not outcomes[b][x])
            only_b = sum(1 for x in ids if outcomes[b][x] and not outcomes[a][x])
            p = mcnemar_exact(only_a, only_b)
            paired.append({
                "a": a, "b": b, "n": len(ids),
                "only_a_correct": only_a, "only_b_correct": only_b,
                "both_correct": sum(1 for x in ids if outcomes[a][x] and outcomes[b][x]),
                "neither_correct": sum(1 for x in ids if not outcomes[a][x] and not outcomes[b][x]),
                "p_exact": round(p, 4),
                "p_uncorrected": round(p, 4),
                "threshold": p_threshold,
                "difference_detected": p < p_threshold,
            })

    result: Dict[str, Any] = {
        "size": size,
        "protocol": manifest.get("protocol", "v1"),
        "questions_sha256": manifest["questions_sha256"],
        "arms": per_arm,
        "paired": paired,
    }

    if compare_with is not None:
        other_run_dir = Path(compare_with) / f"size_{size}"
        if other_run_dir.exists():
            comparison: Dict[str, Any] = {}
            lookup_qs = [q for q in questions if qtype(q) == "lookup"]
            for arm in arms:
                other_arm_dir = other_run_dir / arm
                if other_arm_dir.exists():
                    other_ans, _ = load_arm_answers(other_arm_dir)
                    only_new = only_old = both = neither = 0
                    for q in lookup_qs:
                        qid = q["id"]
                        new_ok = outcomes[arm].get(qid, False)
                        old_ok = False
                        if qid in other_ans:
                            old_ok = bool(grade_question(q, other_ans[qid])["correct"])
                        if new_ok and not old_ok:
                            only_new += 1
                        elif old_ok and not new_ok:
                            only_old += 1
                        elif new_ok and old_ok:
                            both += 1
                        else:
                            neither += 1
                    p = mcnemar_exact(only_new, only_old)
                    comparison[arm] = {
                        "n": len(lookup_qs),
                        "only_new_correct": only_new,
                        "only_old_correct": only_old,
                        "both_correct": both,
                        "neither_correct": neither,
                        "p_exact": round(p, 4),
                    }
            result["compare_with"] = comparison

    return result


def to_markdown(s: Dict[str, Any]) -> str:
    is_v2 = s.get("protocol") == "v2"
    if is_v2:
        lines = [
            f"# Agent-in-the-loop accuracy, size {s['size']} (Protocol v2)",
            "",
            "| Arm | Answerable correct | Rate | 95% CI | Grounded correct | Ungrounded correct | Missing evidence | Fabricated evidence | Wrong: said not in memory | Wrong: other | Safety | Audit |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for arm, e in s["arms"].items():
            a = e["answerable"]
            g = e.get("grounding", {})
            safety = e.get("safety", "n/a")
            if safety == "run":
                safety = f"{e['private_leaks']} leaks"
            audit = "n/a"
            if "audit" in e:
                if e["audit"]["total_events"] == 0:
                    audit = "INVALID"
                elif e["audit"]["violations"]:
                    audit = "VIOLATION: " + "; ".join(e["audit"]["violations"])
                else:
                    audit = f"OK ({e['audit']['total_events']} events, {e['audit']['tool_calls_per_question']} calls/q)"
            lines.append(
                f"| {arm} | {a['correct']}/{a['n']} | {a['rate']:.1%} | {a['wilson95'][0]:.1%} to {a['wilson95'][1]:.1%} | "
                f"{g.get('grounded_correct', 0)} | {g.get('ungrounded_correct', 0)} | {g.get('missing_evidence', 0)} | {g.get('fabricated_evidence', 0)} | "
                f"{e['wrong_but_said_not_in_memory']} | {e['wrong_with_other_answer_or_missing']} | {safety} | {audit} |"
            )
        lines += [
            "",
            "## Paired comparisons (same questions, exact McNemar, Bonferroni threshold p < 0.0167)",
            "",
            "| A | B | only A right | only B right | p | detected |",
            "|---|---|---|---|---|---|",
        ]
        for p in s["paired"]:
            lines.append(
                f"| {p['a']} | {p['b']} | {p['only_a_correct']} | {p['only_b_correct']} | {p['p_exact']} | {'yes' if p['difference_detected'] else 'no'} |"
            )
        lines += ["", "## Per question type", ""]
        for arm, e in s["arms"].items():
            parts = ", ".join(f"{t}: {v['correct']}/{v['n']}" for t, v in sorted(e["per_type"].items()))
            lines.append(f"- {arm}: {parts}")
            if "lookup" in e and "composite" in e:
                lines.append(f"  - lookup: {e['lookup']['correct']}/{e['lookup']['n']} ({e['lookup']['rate']:.1%})")
                lines.append(f"  - composite: {e['composite']['correct']}/{e['composite']['n']} ({e['composite']['rate']:.1%})")
            for pr in e["problems"]:
                lines.append(f"  - PROBLEM: {pr}")

        if "compare_with" in s:
            lines += [
                "",
                "## Comparison with baseline run (30 common lookups)",
                "",
                "| Arm | Only new right | Only old right | Both right | Neither right | p |",
                "|---|---|---|---|---|---|",
            ]
            for arm, c in s["compare_with"].items():
                lines.append(
                    f"| {arm} | {c['only_new_correct']} | {c['only_old_correct']} | {c['both_correct']} | {c['neither_correct']} | {c['p_exact']} |"
                )
        return "\n".join(lines) + "\n"
    else:
        lines = [f"# Agent-in-the-loop accuracy, size {s['size']}", "",
                 "| Arm | Answerable correct | Rate | 95% CI | Wrong: said not in memory | Wrong: other/missing | Private leaks | Audit |",
                 "|---|---|---|---|---|---|---|---|"]
        for arm, e in s["arms"].items():
            a = e["answerable"]
            if "audit" not in e:
                audit = "n/a"
            elif e["audit"]["total_events"] == 0:
                audit = "INVALID"
            elif e["audit"]["violations"]:
                audit = "VIOLATION: " + "; ".join(e["audit"]["violations"])
            else:
                audit = "OK"
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
    ap.add_argument("--root", default=None)
    ap.add_argument("--vault-root", default=str(HERE.parent / "vaults"))
    ap.add_argument("--compare-with", default=None, help="Path to other runs root for comparing v1 lookups")
    args = ap.parse_args()

    vault_root = Path(args.vault_root)
    if args.root is None:
        v2_manifest = Path(DEFAULT_ROOT_V2) / f"size_{args.size}" / "manifest.json"
        if v2_manifest.exists():
            root = Path(DEFAULT_ROOT_V2)
        else:
            root = Path(DEFAULT_ROOT)
    else:
        root = Path(args.root)

    compare_root = Path(args.compare_with) if args.compare_with else None
    s = grade(args.size, root, vault_root, compare_with=compare_root)
    out = root / f"size_{args.size}"
    (out / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(to_markdown(s), encoding="utf-8")
    print(to_markdown(s))


if __name__ == "__main__":
    main()
