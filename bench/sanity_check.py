#!/usr/bin/env python3
"""Sanity gate: run this BEFORE the full scaling benchmark.

    python bench/sanity_check.py                    # sizes 50 and 200
    python bench/sanity_check.py --sizes 50 200 1000

Two checks per size, using the same model and grader as the benchmark:

1. ORACLE: put exactly the gold fact(s) of each answerable question (lookup and overview)
   in the prompt. A working question set and grader must score at least 95%. If not, the
   questions, the keywords or the grader are broken, and no benchmark number can be trusted.
2. FLAT, size 50 only: the whole log is in the prompt, so every fact is available. It must
   score at least 90% on answerable questions. Far below that means the vault does not
   contain what the questions ask about.

Writes bench/results_scaling/sanity.json. Exit code 0 only if every check passes.
Transient API failures are retried (up to 6 attempts, 30 s apart) and are never graded as wrong answers.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "eval"))

from make_scaled_vault import file_sha256, questions_path  # noqa: E402
from run_eval import GroqKeyPool, grade_question, load_groq_keys, timed_chat  # noqa: E402

DEFAULT_MODEL = "qwen/qwen3.8-27b"
VAULT_ROOT = Path(__file__).parent / "vaults"
OUT = ROOT / "bench" / "results_scaling" / "sanity.json"
ORACLE_MIN = 0.95
FLAT_MIN = 0.90


def ask(client: Any, model: str, system: str, question: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
        "temperature": 0.0,
        "max_tokens": 150,
    }
    last: Exception = RuntimeError("no attempt")
    for attempt in range(6):
        try:
            resp, _ = timed_chat(client, payload)
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(30)
    raise RuntimeError(f"gave up after 6 attempts: {last}")


def answerable(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [q for q in questions if not q.get("private") and not q.get("negative")]


def oracle_check(client: Any, model: str, size: int) -> Dict[str, Any]:
    vault = VAULT_ROOT / f"scaled_{size}"
    questions = json.loads(questions_path(vault).read_text())
    rows = []
    for q in answerable(questions):
        facts = "\n".join(f"- {f}" for f in q["gold_facts"])
        system = f"Answer factually and concisely using only these facts:\n{facts}"
        answer = ask(client, model, system, q["question"])
        rows.append({"id": q["id"], "question": q["question"], "keywords": q["keywords"],
                     "gold_facts": q["gold_facts"], "answer": answer,
                     "correct": grade_question(q, answer)["correct"]})
    correct = sum(r["correct"] for r in rows)
    rate = correct / len(rows) if rows else 0.0
    return {"check": "oracle", "size": size, "questions_sha": file_sha256(questions_path(vault)),
            "n": len(rows), "correct": correct, "rate": round(rate, 4), "threshold": ORACLE_MIN,
            "passed": rate >= ORACLE_MIN, "failures": [r for r in rows if not r["correct"]]}


def flat_check(client: Any, model: str, size: int = 50) -> Dict[str, Any]:
    vault = VAULT_ROOT / f"scaled_{size}"
    questions = json.loads(questions_path(vault).read_text())
    log = "\n".join(p.read_text(encoding="utf-8") for p in sorted((vault / "log").glob("*.md")))
    system = ("You are an assistant answering questions from the user's personal memory log.\n"
              "Answer factually, accurately, and concisely based strictly on the memory notes.\n\n"
              f"<MEMORY_VAULT>\n{log.strip()}\n</MEMORY_VAULT>")
    rows = []
    for q in answerable(questions):
        answer = ask(client, model, system, q["question"])
        rows.append({"id": q["id"], "question": q["question"], "keywords": q["keywords"],
                     "answer": answer, "correct": grade_question(q, answer)["correct"]})
    correct = sum(r["correct"] for r in rows)
    rate = correct / len(rows) if rows else 0.0
    return {"check": "flat", "size": size, "questions_sha": file_sha256(questions_path(vault)),
            "n": len(rows), "correct": correct, "rate": round(rate, 4), "threshold": FLAT_MIN,
            "passed": rate >= FLAT_MIN, "failures": [r for r in rows if not r["correct"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sanity gate before the scaling benchmark")
    parser.add_argument("--sizes", type=int, nargs="+", default=[50, 200])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    keys = load_groq_keys()
    if not keys:
        print("ERROR: no GROQ_API_KEY* entries in .env")
        sys.exit(1)
    client = GroqKeyPool(keys)

    results: List[Dict[str, Any]] = []
    for size in args.sizes:
        print(f"[oracle] size {size} ...", flush=True)
        results.append(oracle_check(client, args.model, size))
        print(f"   {results[-1]['correct']}/{results[-1]['n']} correct (need {ORACLE_MIN:.0%})", flush=True)
    if 50 in args.sizes:
        print("[flat] size 50 ...", flush=True)
        results.append(flat_check(client, args.model, 50))
        print(f"   {results[-1]['correct']}/{results[-1]['n']} correct (need {FLAT_MIN:.0%})", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"model": args.model, "results": results,
                               "passed": all(r["passed"] for r in results)}, indent=2), encoding="utf-8")
    for r in results:
        for f in r["failures"][:5]:
            print(f"  FAIL [{r['check']} {r['size']}] {f['question']!r} -> {f['answer'][:100]!r}")
    ok = all(r["passed"] for r in results)
    print("SANITY GATE:", "PASSED" if ok else "FAILED", f"(details in {OUT})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
