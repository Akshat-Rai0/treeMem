"""Offline check of the descent gate: no API calls, no keys.

For each evaluation question, run recall(path="/", query=..., follow=True) with the real gate and ask:
  "Does the text the agent receives from that ONE call contain the expected answer?"

A question that is NOT answerable from the first call but where the gate said "stop" is a PREMATURE STOP:
the agent would answer from an incomplete summary, as happened on q09 with gpt-oss-120b.

    python bench/gate_offline_eval.py
    python bench/gate_offline_eval.py --compare   # current gate vs the previous behaviour
"""

import argparse
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from treemem.descent_gate import DescentGate
from treemem.tree_manager import TreeManager

ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_questions(question_set: str = "dev"):
    """Return (questions, grade_answer). Sets: dev (the 12 eval questions), heldout, all."""
    run_eval = _load_module("run_eval_for_gate", ROOT / "bench" / "eval" / "run_eval.py")
    heldout = _load_module("gate_heldout", ROOT / "bench" / "eval" / "gate_heldout.py").GATE_HELDOUT
    if question_set == "dev":
        questions = run_eval.EVAL_QUESTIONS
    elif question_set == "heldout":
        questions = heldout
    else:
        questions = list(run_eval.EVAL_QUESTIONS) + list(heldout)
    return questions, run_eval.grade_answer


def returned_text(result: Dict[str, Any]) -> str:
    """Everything the agent sees from one guided recall call."""
    parts = [result.get("summary", "")]
    for child in result.get("children", []):
        parts.append(f"{child.get('label', '')} {child.get('teaser', '')}")
    for fact in result.get("facts", []):
        parts.append(fact.get("fact", ""))
    search = result.get("search")
    if search:
        parts.append(json.dumps(search.get("hits", [])))
    return "\n".join(parts)


def evaluate_gate(gate: DescentGate, questions: List[Dict[str, Any]], grade_answer: Any, vault: Path) -> Dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="gate_eval_")) / "vault"
    shutil.copytree(vault, work, ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"))
    manager = TreeManager(work)
    manager.descent_gate = gate

    rows = []
    for item in questions:
        result = manager.recall("/", query=item["question"], follow=True)
        text = returned_text(result)
        private = bool(item.get("private"))
        negative = bool(item.get("negative")) or item["id"].startswith("q12")
        leaked = any(f in text for f in item.get("forbidden", []))
        if private or negative:
            answerable = None
        else:
            answerable = grade_answer(text, item["keywords"])
        rows.append({
            "id": item["id"],
            "final_path": result["final_path"],
            "steps": result["steps"],
            "stopped_reason": result["stopped_reason"],
            "tokens": result["tokens"],
            "answerable": answerable,
            "leaked": leaked,
        })

    scored = [r for r in rows if r["answerable"] is not None]
    premature = [r for r in scored if not r["answerable"] and r["stopped_reason"] in ("stop", "leaf")]
    summary = {
        "answerable_from_first_call": sum(1 for r in scored if r["answerable"]),
        "scored_questions": len(scored),
        "premature_stops": [r["id"] for r in premature],
        "private_leaks": sum(1 for r in rows if r["leaked"]),
        "mean_steps": round(sum(r["steps"] for r in rows) / len(rows), 3),
        "total_returned_tokens": sum(r["tokens"] for r in rows),
    }
    return {"summary": summary, "rows": rows}


def print_report(title: str, report: Dict[str, Any]) -> None:
    summary = report["summary"]
    print(f"\n=== {title} ===")
    print(f"{'question':26s} {'final_path':22s} steps reason          tokens answerable")
    for row in report["rows"]:
        print(f"{row['id']:26s} {row['final_path']:22s} {row['steps']:>5d} {row['stopped_reason']:15s} {row['tokens']:>6d} {row['answerable']}")
    print(
        f"answerable from first call: {summary['answerable_from_first_call']}/{summary['scored_questions']} | "
        f"premature stops: {summary['premature_stops']} | private leaks: {summary['private_leaks']} | "
        f"mean steps: {summary['mean_steps']} | returned tokens: {summary['total_returned_tokens']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline descent-gate check (no API calls).")
    parser.add_argument("--vault", default="examples/sample_memory")
    parser.add_argument("--compare", action="store_true", help="Also run the legacy gate (before the premature-stop fix).")
    parser.add_argument("--set", default="dev", choices=["dev", "heldout", "all"], help="Which question set to use.")
    parser.add_argument("--quiet", action="store_true", help="Only print the summary lines.")
    args = parser.parse_args()

    questions, grade_answer = load_questions(args.set)
    vault = Path(args.vault)

    current = evaluate_gate(DescentGate(), questions, grade_answer, vault)
    print_report("current gate", current)

    if args.compare:
        previous = evaluate_gate(DescentGate.legacy(), questions, grade_answer, vault)
        print_report("legacy gate (before the fix)", previous)


if __name__ == "__main__":
    main()
