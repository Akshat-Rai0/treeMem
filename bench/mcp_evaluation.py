#!/usr/bin/env python3
"""MCP Accuracy Evaluation for TreeMem.

This script coordinates evaluation of TreeMem via MCP by:
1. Loading questions from scaled_50_questions.json
2. Running three evaluation approaches
3. Grading results using the existing grader
4. Reporting accuracy metrics
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bench" / "eval"))
from run_eval import grade_question

# Load questions
questions_file = Path(__file__).parent.parent / "bench/vaults/scaled_50_questions.json"
with open(questions_file) as f:
    questions = json.load(f)

print(f"Loaded {len(questions)} questions from scaled_50")

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

print("\n" + "="*60)
print("INSTRUCTIONS FOR MCP EVALUATION")
print("="*60)
print("\n1. Approach 1: Manual MCP Calls")
print("   For each question, ask Devin to:")
print("   - Call recall(path='/', query='<question>', follow=True)")
print("   - If needed, call expand(path='<returned_path>')")
print("   - If needed, call search(query='<question>', limit=5)")
print("   - Capture the answer")
print("\n2. Approach 2: Agent Mode")
print("   For each question, ask Devin to:")
print("   - Use available MCP tools to answer the question")
print("   - Choose which tools to call autonomously")
print("   - Capture the answer")
print("\n3. Approach 3: Oracle Prompts")
print("   For each question:")
print("   - Extract gold_facts from questions.json")
print("   - Provide facts in prompt to Devin")
print("   - Ask the question")
print("   - Capture the answer")
print("\n" + "="*60)
print("GRADING")
print("="*60)
print("\nFor each answer, grade_question() will check:")
print("- Lookup/Overview: answer contains expected keywords")
print("- Private: answer does NOT contain forbidden text")
print("- Unanswerable: answer contains refusal keywords")
print("\n" + "="*60)
print("SAMPLE QUESTIONS")
print("="*60)

print("\nLookup questions (first 3):")
for q in lookup[:3]:
    print(f"\n  {q['id']}: {q['question']}")
    print(f"    Keywords: {q.get('keywords', [])}")
    print(f"    Gold facts: {q.get('gold_facts', [])}")

print("\nOverview questions (first 2):")
for q in overview[:2]:
    print(f"\n  {q['id']}: {q['question']}")
    print(f"    Keywords: {q.get('keywords', [])}")

print("\nPrivate questions:")
for q in private:
    print(f"\n  {q['id']}: {q['question']}")
    print(f"    Forbidden: {q.get('forbidden', [])}")

print("\nUnanswerable questions (first 2):")
for q in unanswerable[:2]:
    print(f"\n  {q['id']}: {q['question']}")

print("\n" + "="*60)
print("SAVE THIS OUTPUT AND PROVIDE ANSWERS TO GRADE")
print("="*60)
