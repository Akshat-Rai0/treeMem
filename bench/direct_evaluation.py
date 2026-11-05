#!/usr/bin/env python3
"""Direct TreeMem evaluation without MCP overhead.

Tests three approaches:
1. TreeManager direct calls (recall, search, expand)
2. Simulated agent behavior
3. Oracle prompts (gold facts in prompt)
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from treemem.tree_manager import TreeManager

# Import grader
sys.path.insert(0, str(Path(__file__).parent / "eval"))
from run_eval import grade_question

# Load questions
questions_file = Path(__file__).parent / "vaults" / "scaled_50_questions.json"
with open(questions_file) as f:
    questions = json.load(f)

# Initialize TreeManager
vault_dir = Path(__file__).parent / "vaults" / "scaled_50"
mgr = TreeManager(vault_dir)

print(f"Loaded {len(questions)} questions")
print(f"Vault: {vault_dir}")

# Results storage
results = {
    "treemanager_direct": [],
    "simulated_agent": [],
    "oracle": []
}

# Group by question type
lookup = [q for q in questions if not q.get("private") and not q.get("negative") and not q.get("require_all")]
overview = [q for q in questions if q.get("require_all")]
private = [q for q in questions if q.get("private")]
unanswerable = [q for q in questions if q.get("negative")]

print(f"\nQuestion breakdown:")
print(f"  Lookup: {len(lookup)}")
print(f"  Overview: {len(overview)}")
print(f"  Private: {len(private)}")
print(f"  Unanswerable: {len(unanswerable)}")

# Approach 1: TreeManager direct calls
print("\n" + "="*60)
print("APPROACH 1: TreeManager Direct Calls")
print("="*60)

for q in lookup[:5]:  # Test first 5 lookup questions
    question = q['question']
    qid = q['id']
    
    # Try recall with follow
    try:
        recall_result = mgr.recall(path="/", query=question, follow=True, max_depth=3)
        answer = f"Recall returned path: {recall_result.get('path', 'N/A')}"
        if recall_result.get('summary'):
            answer += f", summary: {recall_result['summary'][:100]}..."
    except Exception as e:
        answer = f"Error: {str(e)}"
    
    grade = grade_question(q, answer)
    
    results["treemanager_direct"].append({
        "question_id": qid,
        "question": question,
        "answer": answer,
        "correct": grade["correct"],
        "leaked": grade["leaked"]
    })
    
    print(f"\n{qid}: {grade['correct']} - {answer[:80]}...")

# Approach 2: Simulated agent (use search)
print("\n" + "="*60)
print("APPROACH 2: Simulated Agent (BM25 Search)")
print("="*60)

for q in lookup[:5]:
    question = q['question']
    qid = q['id']
    
    try:
        search_result = mgr.search(query=question, limit=5)
        hits = search_result.get('hits', [])
        if hits:
            answer = f"Found {len(hits)} hits. First hit: {hits[0].get('fact', '')[:80]}..."
        else:
            answer = f"No hits found"
    except Exception as e:
        answer = f"Error: {str(e)}"
    
    grade = grade_question(q, answer)
    
    results["simulated_agent"].append({
        "question_id": qid,
        "question": question,
        "answer": answer,
        "correct": grade["correct"],
        "leaked": grade["leaked"]
    })
    
    print(f"\n{qid}: {grade['correct']} - {answer[:80]}...")

# Approach 3: Oracle prompts
print("\n" + "="*60)
print("APPROACH 3: Oracle Prompts (Gold Facts)")
print("="*60)

for q in lookup[:5]:
    question = q['question']
    qid = q['id']
    gold_facts = q.get('gold_facts', [])
    
    # Simulate oracle answer (perfect knowledge)
    if gold_facts:
        answer = gold_facts[0]  # Oracle knows the answer
    else:
        answer = "Information not available"
    
    grade = grade_question(q, answer)
    
    results["oracle"].append({
        "question_id": qid,
        "question": question,
        "answer": answer,
        "correct": grade["correct"],
        "leaked": grade["leaked"]
    })
    
    print(f"\n{qid}: {grade['correct']} - {answer[:80]}...")

# Summary
print("\n" + "="*60)
print("SUMMARY")
print("="*60)

for approach in ["treemanager_direct", "simulated_agent", "oracle"]:
    correct = sum(1 for r in results[approach] if r['correct'])
    total = len(results[approach])
    accuracy = correct / total * 100 if total > 0 else 0
    print(f"\n{approach}:")
    print(f"  Total: {total}")
    print(f"  Correct: {correct}")
    print(f"  Accuracy: {accuracy:.1f}%")

# Save results
output_file = Path(__file__).parent / "results_scaling" / "mcp_eval_results.json"
output_file.parent.mkdir(parents=True, exist_ok=True)
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nResults saved to: {output_file}")
