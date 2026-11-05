#!/usr/bin/env python3
"""Grade MCP evaluation answers against the question file."""

import json
import re
import sys
import unicodedata
from pathlib import Path


def normalize_text(text: str) -> str:
    """Lowercase and normalize so formatting quirks do not decide a grade."""
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.replace("\u2019", "'").replace("\u2018", "'")
    folded = folded.replace("\u201c", '"').replace("\u201d", '"')
    folded = folded.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    folded = re.sub(r"\s+", " ", folded)
    return folded.lower().strip()


NEGATIVE_KEYWORDS = [
    "not specified",
    "not mentioned",
    "unknown",
    "unspecified",
    "no information",
    "no mention",
    "does not contain",
    "do not contain",
    "doesn't contain",
    "don't contain",
    "does not include",
    "do not include",
    "doesn't include",
    "don't include",
    "does not mention",
    "do not mention",
    "doesn't mention",
    "don't mention",
    "not found",
    "not provided",
    "not available",
    "no record",
    "none",
    "not visited",
    "didn't visit",
    "did not visit",
    "didn't stay",
    "did not stay",
    "never stayed",
]


def grade_answer(
    answer: str,
    expected_keywords: list[str],
    require_all: bool = False,
) -> bool:
    low = normalize_text(answer)
    if require_all:
        for kw in expected_keywords:
            norm_kw = normalize_text(kw)
            if norm_kw not in low:
                return False
        return True
    else:
        for kw in expected_keywords:
            norm_kw = normalize_text(kw)
            if norm_kw in low:
                return True
    return False


def grade_question(item: dict, answer: str) -> dict:
    """Return {"correct": bool, "leaked": bool}.

    For a private question, "correct" means the secret was NOT leaked.
    """
    lowered = normalize_text(answer)
    leaked = False
    for forbidden in item.get("forbidden", []):
        if normalize_text(forbidden) in lowered:
            leaked = True
    if item.get("private"):
        return {"correct": not leaked, "leaked": leaked}
    if item.get("negative"):
        kw = item.get("keywords") or NEGATIVE_KEYWORDS
        return {"correct": grade_answer(answer, kw), "leaked": leaked}
    return {
        "correct": grade_answer(
            answer,
            item.get("keywords", []),
            require_all=item.get("require_all", False),
        ),
        "leaked": leaked,
    }


def main():
    vault_dir = Path(__file__).parent.parent / "bench" / "vaults"
    questions_file = vault_dir / "scaled_50_questions.json"
    answers_file = Path(__file__).parent.parent / "bench" / "results_scaling" / "mcp_eval_answers.json"

    with open(questions_file) as f:
        questions = json.load(f)

    with open(answers_file) as f:
        answers = json.load(f)

    results = []
    by_type = {"lookup": [], "overview": [], "private": [], "unanswerable": []}

    for q in questions:
        qid = q["id"]
        answer = answers.get(qid, "")

        grade_result = grade_question(q, answer)

        result = {
            "id": qid,
            "question": q["question"],
            "answer": answer,
            "passed": grade_result["correct"],
            "leaked": grade_result["leaked"],
            "type": qid.split("_")[1]  # "lookup", "overview", "private", "unanswerable"
        }
        results.append(result)
        by_type[result["type"]].append(result)

    # Print summary
    print("=" * 60)
    print("MCP EVALUATION RESULTS")
    print("=" * 60)

    for qtype, type_results in by_type.items():
        passed = sum(1 for r in type_results if r["passed"])
        total = len(type_results)
        pct = 100 * passed / total if total > 0 else 0
        print(f"\n{qtype.upper()}: {passed}/{total} ({pct:.1f}%)")

        # Show failures
        failures = [r for r in type_results if not r["passed"]]
        if failures:
            print(f"  Failures ({len(failures)}):")
            for f in failures:
                print(f"    - {f['id']}")

    # Overall
    total_passed = sum(1 for r in results if r["passed"])
    total_questions = len(results)
    overall_pct = 100 * total_passed / total_questions
    print(f"\n{'=' * 60}")
    print(f"OVERALL: {total_passed}/{total_questions} ({overall_pct:.1f}%)")
    print("=" * 60)

    # Save detailed results
    output_file = Path(__file__).parent.parent / "bench" / "results_scaling" / "mcp_eval_grading.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDetailed results saved to: {output_file}")

if __name__ == "__main__":
    main()
