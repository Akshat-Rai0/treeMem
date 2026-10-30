"""Rebuild llm_eval_aggregate.json (and llm_eval_results.json) from the saved per-run files.

Use this after a rate limit or crash interrupted run_eval.py, or after copying run_k.json files in
by hand. No API calls, no keys needed.

    python bench/eval/rebuild_aggregate.py
    python bench/eval/rebuild_aggregate.py --results-dir bench/results
"""

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent


def load_eval_module():
    spec = importlib.util.spec_from_file_location("run_eval_module", HERE / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_number(path: Path) -> int:
    match = re.search(r"run_(\d+)\.json$", path.name)
    return int(match.group(1)) if match else 0


def records_from_run(run_data: Dict[str, Any], question_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Turn a saved run file back into the {arm: [ {item, result, grade} ]} shape the harness uses."""
    arm_names = list(run_data["arms"].keys())
    records: Dict[str, List[Dict[str, Any]]] = {arm: [] for arm in arm_names}
    for question_entry in run_data["questions"]:
        item = question_by_id[question_entry["id"]]
        for arm in arm_names:
            saved = dict(question_entry[arm])
            grade = {"correct": saved.pop("correct"), "leaked": saved.pop("leaked", False)}
            records[arm].append({"item": item, "result": saved, "grade": grade})
    return records


def regrade_records(ev: Any, records: Dict[str, List[Dict[str, Any]]]) -> int:
    """Grade every saved answer again with the current grader. Returns how many grades changed."""
    changed = 0
    for arm_records in records.values():
        for record in arm_records:
            new_grade = ev.grade_question(record["item"], record["result"]["answer"])
            if new_grade != record["grade"]:
                changed += 1
            record["grade"] = new_grade
    return changed


def rewrite_run_data(ev: Any, run_data: Dict[str, Any], records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Put the new grades and summaries back into the run file structure."""
    updated = dict(run_data)
    updated["arms"] = {arm: ev.summarize_arm_run(records[arm]) for arm in records}
    new_questions = []
    for index, question_entry in enumerate(run_data["questions"]):
        entry = dict(question_entry)
        for arm in records:
            arm_entry = dict(entry[arm])
            arm_entry["correct"] = records[arm][index]["grade"]["correct"]
            arm_entry["leaked"] = records[arm][index]["grade"]["leaked"]
            entry[arm] = arm_entry
        new_questions.append(entry)
    updated["questions"] = new_questions
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild aggregate JSON from saved run files.")
    parser.add_argument("--results-dir", default="bench/results")
    parser.add_argument(
        "--regrade",
        action="store_true",
        help="Re-grade every saved answer with the CURRENT grader and rewrite the run files "
             "(answers and token counts are untouched; only correct/leaked and the summaries change).",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    run_files = sorted((results_dir / "llm_eval_runs").glob("run_*.json"), key=run_number)
    if not run_files:
        print(f"No run files found in {results_dir / 'llm_eval_runs'}")
        return

    ev = load_eval_module()
    question_by_id = {item["id"]: item for item in ev.EVAL_QUESTIONS}

    per_run_arm_summaries: List[Dict[str, Dict[str, Any]]] = []
    all_runs_records: List[Dict[str, List[Dict[str, Any]]]] = []
    last_data: Dict[str, Any] = {}
    for run_file in run_files:
        run_data = json.loads(run_file.read_text(encoding="utf-8"))
        records = records_from_run(run_data, question_by_id)
        if args.regrade:
            changed = regrade_records(ev, records)
            run_data = rewrite_run_data(ev, run_data, records)
            run_file.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
            print(f"Re-graded {run_file.name}: {changed} grade(s) changed.")
        per_run_arm_summaries.append({arm: ev.summarize_arm_run(records[arm]) for arm in records})
        all_runs_records.append(records)
        last_data = run_data

    class _NoClient:
        key_usage: Dict[str, int] = {}

    aggregate = ev.build_aggregate(
        model=last_data["model"],
        runs_done=len(run_files),
        question_count=len(last_data["questions"]),
        per_run_arm_summaries=per_run_arm_summaries,
        all_runs_records=all_runs_records,
        client=_NoClient(),
    )
    (results_dir / "llm_eval_aggregate.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")

    last_records = all_runs_records[-1]
    if "flat" in last_records and "tree" in last_records:
        question_list = [question_by_id[q["id"]] for q in last_data["questions"]]
        ev.write_legacy_single_run_file(results_dir, last_data["model"], question_list, last_records, _NoClient())

    print(f"Rebuilt aggregate from {len(run_files)} run file(s) in {results_dir}.")
    ev.print_summary(aggregate)


if __name__ == "__main__":
    main()
