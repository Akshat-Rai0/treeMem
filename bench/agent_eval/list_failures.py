#!/usr/bin/env python3
"""List failed answerable questions and agent answers from an agent-in-the-loop evaluation run.

Usage:
    python bench/agent_eval/list_failures.py 1000 [--root bench/agent_eval/runs_v2]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from grade_agent_answers import load_arm_records, normalize_evidence_text, qtype  # noqa: E402
from make_scaled_vault import questions_path, questions_v2_path  # noqa: E402
from run_eval import NEGATIVE_KEYWORDS, grade_answer, grade_question  # noqa: E402
from treemem.log_writer import LogWriter  # noqa: E402

DEFAULT_ROOT = HERE / "runs"
DEFAULT_ROOT_V2 = HERE / "runs_v2"


def get_failures(size: int, root: Path = DEFAULT_ROOT, vault_root: Path = HERE.parent / "vaults") -> Dict[str, Any]:
    run_dir = root / f"size_{size}"
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    manifest_file = run_dir / "manifest.json"
    manifest: Dict[str, Any] = {}
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    is_v2 = manifest.get("protocol") == "v2"

    if manifest.get("questions_file"):
        qfile = Path(manifest["questions_file"])
    elif is_v2:
        qfile = questions_v2_path(vault_root / f"scaled_{size}")
    else:
        qfile = questions_path(vault_root / f"scaled_{size}")

    if not qfile.exists():
        raise FileNotFoundError(f"Questions file not found: {qfile}")

    questions = json.loads(qfile.read_text(encoding="utf-8"))
    arms = manifest.get("arms", ["treemem", "bm25", "grep"])

    norm_facts: List[str] = []
    vault_dir = vault_root / f"scaled_{size}"
    if vault_dir.exists():
        lw = LogWriter(vault_dir)
        norm_facts = [normalize_evidence_text(e["fact"]) for e in lw.read_all_entries() if "fact" in e]

    out_arms: Dict[str, Any] = {}

    for arm in arms:
        arm_dir = run_dir / arm
        if not arm_dir.exists():
            continue

        records, _ = load_arm_records(arm_dir)
        failures: List[Dict[str, Any]] = []
        reason_counts = {"abstained": 0, "other": 0}

        for q in questions:
            t = qtype(q)
            if t not in ("lookup", "composite", "overview"):
                continue

            qid = q["id"]
            if qid not in records:
                reason = "other"
                reason_counts[reason] += 1
                failures.append({
                    "id": qid,
                    "type": t,
                    "question": q.get("question", ""),
                    "keywords": q.get("keywords", []),
                    "gold_facts": q.get("gold_facts", []),
                    "answer": "<no answer provided>",
                    "evidence": "",
                    "grounded": False,
                    "reason": reason,
                })
                continue

            rec = records[qid]
            ans = rec["answer"]
            ev = rec["evidence"]
            g = grade_question(q, ans)

            if not g["correct"]:
                if grade_answer(ans, NEGATIVE_KEYWORDS):
                    reason = "abstained"
                else:
                    reason = "other"
                reason_counts[reason] += 1

                is_grounded = False
                if is_v2:
                    ev_lines = [normalize_evidence_text(line) for line in ev.splitlines() if normalize_evidence_text(line)]
                    if ev_lines and all(any(el in f for f in norm_facts) for el in ev_lines):
                        is_grounded = True
                else:
                    is_grounded = None

                failures.append({
                    "id": qid,
                    "type": t,
                    "question": q.get("question", ""),
                    "keywords": q.get("keywords", []),
                    "gold_facts": q.get("gold_facts", []),
                    "answer": ans,
                    "evidence": ev,
                    "grounded": is_grounded,
                    "reason": reason,
                })

        out_arms[arm] = {
            "failures": failures,
            "counts": reason_counts,
        }

    return {"size": size, "protocol": "v2" if is_v2 else "v1", "arms": out_arms}


def list_failures(size: int, root: Path = DEFAULT_ROOT, vault_root: Path = HERE.parent / "vaults") -> None:
    res = get_failures(size, root, vault_root)

    print("=" * 80)
    print(f"FAILURE REPORT FOR AGENT EVALUATION (Size: {size}, Protocol: {res['protocol']})")
    print("=" * 80)

    for arm, data in res["arms"].items():
        failures = data["failures"]
        counts = data["counts"]

        print(f"\nArm: {arm.upper()} | Total Wrong Answerable: {len(failures)}")
        print("-" * 80)

        if not failures:
            print("  No failures found for this arm!")
        else:
            for i, f in enumerate(failures, start=1):
                print(f"[{i:02d}] ID: {f['id']}  (Type: {f['type']})")
                print(f"     Reason:    {f['reason']}")
                print(f"     Question:  {f['question']}")
                print(f"     Keywords:  {f['keywords']}")
                print(f"     Gold Fact: {f['gold_facts']}")
                print(f"     Answer:    {f['answer']}")
                print(f"     Evidence:  {f['evidence']}")
                grounded_str = "n/a" if f["grounded"] is None else ("Yes" if f["grounded"] else "No")
                print(f"     Grounded:  {grounded_str}")
                print()

        print(f"Summary for {arm}: Abstained: {counts['abstained']}, Other: {counts['other']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="List failure details from an agent evaluation run")
    parser.add_argument("size", type=int, nargs="?", default=1000, help="Vault size (default: 1000)")
    parser.add_argument("--root", default=None, help="Path to runs directory")
    parser.add_argument("--vault-root", default=str(HERE.parent / "vaults"), help="Path to vaults directory")
    args = parser.parse_args()

    if args.root is None:
        v2_path = DEFAULT_ROOT_V2 / f"size_{args.size}"
        if v2_path.exists():
            root = DEFAULT_ROOT_V2
        else:
            root = DEFAULT_ROOT
    else:
        root = Path(args.root)

    list_failures(args.size, root, Path(args.vault_root))


if __name__ == "__main__":
    main()
