#!/usr/bin/env python3
"""Sanity checks before running the full scaling benchmark.

Run: python bench/sanity_check.py

Checks:
a) Oracle arm: gold facts in prompt, expected 95%+ accuracy
b) Sample vault reproduction: compare with existing results
c) Flat arm size 50: diagnose accuracy issues
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent / "eval"))

from run_eval import load_groq_keys, GroqKeyPool, timed_chat
from run_eval import grade_question, normalize_text

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b"


def oracle_arm_check(vault_dir: Path, model: str) -> Dict[str, Any]:
    """Check: put gold facts in prompt, ask question, expect 95%+ accuracy."""
    print(f"\n{'='*60}")
    print("ORACLE ARM CHECK")
    print(f"{'='*60}")
    print(f"Vault: {vault_dir.name}")
    
    # Load questions
    questions_file = vault_dir.parent / f"{vault_dir.name}_questions.json"
    with open(questions_file) as f:
        questions = json.load(f)
    
    # Filter to answerable lookup and overview questions
    answerable = [q for q in questions if not q.get("private") and not q.get("negative")]
    
    print(f"Answerable questions: {len(answerable)}")
    
    # Load facts from vault
    # For oracle, we need to get the actual facts from the tree
    from treemem.tree_manager import TreeManager
    mgr = TreeManager(vault_dir)
    
    # Build fact lookup
    all_paths = mgr.health_checker.get_all_node_paths()
    fact_map = {}
    for path in all_paths:
        node = mgr.store.read_node(path)
        if node and node.facts:
            for fact in node.facts:
                fact_text = fact.get("fact", "")
                # Map keywords from questions to facts
                for q in answerable:
                    for kw in q.get("keywords", []):
                        if normalize_text(kw) in normalize_text(fact_text):
                            if q['id'] not in fact_map:
                                fact_map[q['id']] = []
                            fact_map[q['id']].append(fact_text)
    
    # Load Groq keys
    keys = load_groq_keys()
    if not keys:
        print("ERROR: No Groq API keys found")
        return {"ok": False, "error": "No API keys"}
    
    client = GroqKeyPool(keys)
    
    results = []
    failures = []
    
    for q in answerable:
        qid = q['id']
        question = q['question']
        keywords = q.get("keywords", [])
        
        # Get gold facts
        gold_facts = fact_map.get(qid, [])
        
        if not gold_facts:
            print(f"  WARNING: No gold facts found for {qid}")
            continue
        
        # Build oracle prompt
        facts_text = "\n".join([f"- {f}" for f in gold_facts])
        system_prompt = f"""You are an assistant answering questions based on the following facts:

{facts_text}

Answer factually and concisely based only on these facts."""
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "temperature": 0.0,
            "max_tokens": 150,
        }
        
        try:
            resp, _ = timed_chat(client, payload)
            answer = resp["choices"][0]["message"]["content"].strip()
            
            # Grade
            grade = grade_question(q, answer)
            
            results.append({
                "question_id": qid,
                "question": question,
                "gold_facts": gold_facts,
                "answer": answer,
                "correct": grade["correct"],
                "keywords": keywords,
            })
            
            if not grade["correct"]:
                failures.append({
                    "question_id": qid,
                    "question": question,
                    "gold_facts": gold_facts,
                    "answer": answer,
                    "keywords": keywords,
                })
        except Exception as e:
            print(f"  ERROR on {qid}: {e}")
            failures.append({
                "question_id": qid,
                "question": question,
                "error": str(e),
            })
    
    # Calculate accuracy
    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = correct / total * 100 if total > 0 else 0
    
    print(f"\nOracle accuracy: {accuracy:.1f}% ({correct}/{total})")
    
    if accuracy < 95:
        print(f"\n{'!'*60}")
        print(f"FAIL: Oracle accuracy {accuracy:.1f}% < 95%")
        print(f"{'!'*60}")
        print("\nFailing questions:")
        for f in failures:
            print(f"\n  ID: {f['question_id']}")
            print(f"  Question: {f['question']}")
            print(f"  Keywords: {f.get('keywords', [])}")
            print(f"  Gold facts: {f.get('gold_facts', [])}")
            print(f"  Answer: {f.get('answer', f.get('error', 'N/A'))}")
        
        return {
            "ok": False,
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
            "failures": failures,
        }
    else:
        print(f"PASS: Oracle accuracy {accuracy:.1f}% >= 95%")
        return {
            "ok": True,
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
        }


def sample_vault_reproduction() -> Dict[str, Any]:
    """Check: run sample vault eval and compare with existing results."""
    print(f"\n{'='*60}")
    print("SAMPLE VAULT REPRODUCTION CHECK")
    print(f"{'='*60}")
    
    # Check if sample vault exists
    sample_vault = Path("examples/sample_memory")
    if not sample_vault.exists():
        print(f"SKIP: Sample vault not found at {sample_vault}")
        return {"ok": True, "skipped": True}
    
    # Check if existing results exist
    existing_results = Path("bench/results/llm_eval_aggregate.json")
    if not existing_results.exists():
        print(f"SKIP: Existing results not found at {existing_results}")
        return {"ok": True, "skipped": True}
    
    # Run evaluation
    out_dir = Path("bench/results_sanity")
    cmd = [
        sys.executable,
        "bench/eval/run_eval.py",
        "--vault", str(sample_vault),
        "--arms", "flat,tree_follow",
        "--runs", "1",
        "--out-dir", str(out_dir),
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ERROR: Evaluation failed")
        print(result.stderr)
        return {"ok": False, "error": result.stderr}
    
    # Load and compare results
    new_results_file = out_dir / "llm_eval_aggregate.json"
    if not new_results_file.exists():
        print(f"ERROR: New results not found")
        return {"ok": False, "error": "No new results"}
    
    with open(existing_results) as f:
        existing = json.load(f)
    with open(new_results_file) as f:
        new = json.load(f)
    
    # Compare per-question pass rates
    print("\nComparing results...")
    differences = []
    
    # This is a simplified comparison - adjust based on actual structure
    old_rates = existing.get("per_question_pass_rate", {})
    new_rates = new.get("per_question_pass_rate", {})
    for qid in sorted(set(old_rates) | set(new_rates)):
        old_rate = old_rates.get(qid, 0)
        new_rate = new_rates.get(qid, 0)
        
        if abs(old_rate - new_rate) > 0.1:  # More than 10% difference
            differences.append({
                "question_id": qid,
                "old_rate": old_rate,
                "new_rate": new_rate,
            })
    
    if differences:
        print(f"\n{'!'*60}")
        print(f"FAIL: {len(differences)} questions differ")
        print(f"{'!'*60}")
        for diff in differences:
            print(f"\n  {diff['question_id']}: {diff['old_rate']:.1f}% -> {diff['new_rate']:.1f}%")
        
        return {
            "ok": False,
            "differences": differences,
        }
    else:
        print("PASS: Results match")
        return {"ok": True}


def flat_arm_diagnosis(vault_dir: Path) -> Dict[str, Any]:
    """Check: diagnose flat arm accuracy at size 50."""
    print(f"\n{'='*60}")
    print("FLAT ARM SIZE 50 DIAGNOSIS")
    print(f"{'='*60}")
    
    # Load progress, retaining the latest record for each episode key.
    progress_file = Path("bench/results_scaling/progress.jsonl")
    if not progress_file.exists():
        print("SKIP: No progress file found")
        return {"ok": True, "skipped": True}
    
    with open(progress_file) as f:
        data = [json.loads(line) for line in f]
    latest = {}
    for record in data:
        key = (record["size"], record["arm"], record["run"], record["question_id"])
        latest[key] = record
    data = list(latest.values())
    
    # Get flat arm at size 50
    flat_50 = [d for d in data if d['size'] == 50 and d['arm'] == 'flat']
    
    if not flat_50:
        print("SKIP: No flat arm data at size 50")
        return {"ok": True, "skipped": True}

    questions_file = vault_dir.parent / f"{vault_dir.name}_questions.json"
    with open(questions_file) as f:
        questions = {q["id"]: q for q in json.load(f)}

    # Calculate accuracy
    correct = sum(1 for d in flat_50 if d.get('correct', False))
    total = len(flat_50)
    accuracy = correct / total * 100 if total > 0 else 0
    
    print(f"Flat arm size 50: {accuracy:.1f}% accuracy ({correct}/{total})")
    
    # Print 10 incorrect episodes
    incorrect = [d for d in flat_50 if not d.get('correct', False)]
    print(f"\nFirst 10 incorrect episodes:")
    
    for i, d in enumerate(incorrect[:10]):
        q = questions.get(d["question_id"], {})
        print(f"\n  {i+1}. Question ID: {d['question_id']}")
        print(f"     Question: {q.get('question', '<missing>')}")
        print(f"     Gold answer/keywords: {q.get('keywords', [])}")
        print(f"     Question type: {d.get('question_type', 'unknown')}")
        print(f"     Answer: {d.get('answer', '')[:100]}...")
        print(f"     Grader decision: {d.get('correct', False)}")
    
    print(f"\nWith expected keywords:")
    for i, d in enumerate(incorrect[:10]):
        qid = d['question_id']
        if qid in questions:
            q = questions[qid]
            print(f"\n  {i+1}. {qid}")
            print(f"     Question: {q['question']}")
            print(f"     Keywords: {q.get('keywords', [])}")
            print(f"     Answer: {d.get('answer', '')[:150]}...")
    
    return {
        "ok": True,
        "accuracy": accuracy,
        "correct": correct,
        "total": total,
        "incorrect_count": len(incorrect),
    }


def rerun_flat_50() -> Dict[str, Any]:
    """Run one fresh flat-arm size-50 evaluation after the diagnosis."""
    out_dir = Path("bench/results_sanity_flat50")
    cmd = [
        sys.executable,
        "bench/eval/run_eval.py",
        "--vault", "bench/vaults/scaled_50",
        "--arms", "flat",
        "--runs", "1",
        "--out-dir", str(out_dir),
    ]
    print(f"\nRerunning flat size 50: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent, text=True)
    if result.returncode != 0:
        return {"ok": False, "error": f"exit status {result.returncode}"}
    aggregate = out_dir / "llm_eval_aggregate.json"
    if not aggregate.exists():
        return {"ok": False, "error": f"missing {aggregate}"}
    with aggregate.open() as f:
        data = json.load(f)
    rate = data.get("per_question_pass_rate", {})
    values = list(rate.values())
    accuracy = sum(values) / len(values) * 100 if values else 0.0
    print(f"New flat size-50 accuracy: {accuracy:.1f}%")
    return {"ok": True, "accuracy": accuracy, "aggregate": str(aggregate)}


def main():
    parser = argparse.ArgumentParser(description="Sanity checks before scaling benchmark")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--skip-oracle", action="store_true", help="Skip oracle check")
    parser.add_argument("--skip-sample", action="store_true", help="Skip sample vault check")
    parser.add_argument("--skip-flat", action="store_true", help="Skip flat arm diagnosis")
    args = parser.parse_args()
    
    results = {}
    
    # Oracle check
    if not args.skip_oracle:
        for size in [50, 200]:
            vault_dir = Path(f"bench/vaults/scaled_{size}")
            if vault_dir.exists():
                result = oracle_arm_check(vault_dir, args.model)
                results[f"oracle_{size}"] = result
                if not result.get("ok") and not result.get("skipped"):
                    print(f"\nFAIL: Oracle check for size {size}")
                    sys.exit(1)
    
    # Sample vault check
    if not args.skip_sample:
        result = sample_vault_reproduction()
        results["sample_vault"] = result
        if not result.get("ok") and not result.get("skipped"):
            print(f"\nFAIL: Sample vault reproduction")
            sys.exit(1)
    
    # Flat arm diagnosis
    if not args.skip_flat:
        vault_dir = Path("bench/vaults/scaled_50")
        if vault_dir.exists():
            result = flat_arm_diagnosis(vault_dir)
            results["flat_50"] = result
            rerun = rerun_flat_50()
            results["flat_50_rerun"] = rerun
            if not rerun.get("ok"):
                print(f"\nFAIL: Flat size-50 rerun: {rerun.get('error')}")
                sys.exit(1)
    
    print(f"\n{'='*60}")
    print("SANITY CHECK COMPLETE")
    print(f"{'='*60}")
    
    # Save results
    results_file = Path("bench/results_scaling/sanity_check_results.json")
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Results saved to: {results_file}")


if __name__ == "__main__":
    main()
