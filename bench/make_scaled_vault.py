#!/usr/bin/env python3
"""Deterministic scalable vault generator for TreeMem evaluation.

python bench/make_scaled_vault.py --facts N --seed 7 --out DIR

Sizes: 50, 200, 1000, 5000 facts

Reuses fact and question generators from make_midsize_vault.py, extending them with
procedural generation (invented syllable-based surnames, cities, titles, products)
for sizes up to 5000. Respects branching cap (12 per node). Builds through TreeManager
with rich teasers and deterministic template summaries (no LLM).

Questions per size: 30 lookup, 10 overview, 4 private, 6 unanswerable = 50 questions.
Fixed seed, so every run sees identical questions.
"""

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from treemem.tree_manager import TreeManager
from treemem.tokenizer import count_tokens

# Import the existing generators
sys.path.insert(0, str(Path(__file__).parent))
from make_midsize_vault import (
    build_specs,
    build_questions,
    QUESTIONS_PER_RELATION,
    OVERVIEW_SPECS,
    ADJ,
    NOUN,
    FIRST,
    LAST,
    BANKS,
    PET_NAMES,
    TRAVEL_GROUPS,
    MUSIC_GROUPS,
    READING_GROUPS,
    FOOD_GROUPS,
    CLIENT_SECTORS,
    TOOL_AREAS,
    EDU_GROUPS,
    FITNESS_GROUPS,
    FAMILY_RELATIVES,
    FAMILY_ANIMALS,
    SPARE_CITIES,
    SPARE_GENRES,
    SPARE_TASKS,
    SPARE_ACTIVITY,
    SPARE_RELATIVE,
    unique_names,
)


def extended_name_pools(seed: int, max_facts: int) -> Dict[str, List[str]]:
    """Extend name pools with procedural generation for larger vaults."""
    rng = random.Random(seed)
    
    # Generate additional syllable-based surnames
    extra_last = []
    syllables = ["brask", "quillon", "zylas", "morvath", "thorne", "ashford", "penrose", "lockhart", "blackwood", "stirling"]
    for _ in range(50):
        name = rng.choice(syllables).capitalize()
        if rng.random() > 0.5:
            name += rng.choice(["son", "ton", "ford", "wood", "field", "well", "ton"])
        extra_last.append(name)
    
    # Generate additional cities
    vowels = "aeiou"
    consonants = "bcdfghjklmnpqrstvwxyz"
    extra_cities = []
    for _ in range(40):
        # Generate syllable-based city names
        city = ""
        for _ in range(rng.randint(2, 4)):
            city += rng.choice(consonants).upper()
            city += rng.choice(vowels)
            if rng.random() > 0.5:
                city += rng.choice(consonants)
        extra_cities.append(city)
    
    # Generate additional product names
    extra_products = []
    prefixes = ["Quantum", "Hyper", "Cyber", "Nano", "Mega", "Ultra", "Smart", "Power"]
    suffixes = ["Flow", "Sync", "Net", "Core", "Base", "Hub", "Link", "Node"]
    for _ in range(100):
        extra_products.append(f"{rng.choice(prefixes)}{rng.choice(suffixes)}")
    
    return {
        "last": extra_last,
        "cities": extra_cities,
        "products": extra_products,
    }


def build_extended_specs(seed: int, max_facts: int) -> Dict[str, Any]:
    """Build specs with extended pools for larger vaults, respecting branching cap."""
    # Start with the base specs
    base_specs = build_specs(seed)
    
    # If we need more facts than the base provides, extend procedurally
    if max_facts <= len(base_specs["facts"]):
        # Truncate to requested size
        base_specs["facts"] = base_specs["facts"][:max_facts]
        return base_specs
    
    rng = random.Random(seed + 1000)
    
    # Add procedural facts using fewer paths with more facts per path
    # Respect branching cap: max 12 children per node
    # Base specs has ~8-10 top-level categories, so add only 1-2 new ones
    extra_facts = []
    extra_candidates = []
    
    # Use 1 new top-level category to stay under branching cap
    new_categories = ["extended"]
    
    # Max 12 subgroups per category (respecting branching cap)
    paths_per_category = 12
    
    # Calculate how many facts per path we need
    target_extra = max_facts - len(base_specs["facts"])
    facts_per_path = target_extra // (paths_per_category * len(new_categories)) + 1
    
    # Generate facts
    fact_idx = 0
    for category in new_categories:
        for path_num in range(paths_per_category):
            path = f"{category}/group_{path_num}"
            
            for item_num in range(facts_per_path):
                if len(base_specs["facts"]) + len(extra_facts) >= max_facts:
                    break
                
                fact_idx += 1
                
                # Generate fact content
                item_type = rng.choice(["note", "reminder", "idea", "task", "goal", "record", "entry", "log"])
                fact = f"Has a {item_type}."
                answer = item_type
                
                extra_facts.append({
                    "path": path,
                    "fact": fact,
                    "relation": f"{category}_item"
                })
                extra_candidates.append({
                    "path": path,
                    "relation": f"{category}_item",
                    "answer": answer,
                    "direct": f"What extended item {fact_idx}?",
                    "paraphrase": f"Tell me about {fact}"
                })
            
            if len(base_specs["facts"]) + len(extra_facts) >= max_facts:
                break
        
        if len(base_specs["facts"]) + len(extra_facts) >= max_facts:
            break
    
    # Merge and truncate
    all_facts = base_specs["facts"] + extra_facts
    all_candidates = base_specs["candidates"] + extra_candidates
    
    base_specs["facts"] = all_facts[:max_facts]
    base_specs["candidates"] = all_candidates
    
    return base_specs


def build_vault_through_manager(specs: Dict[str, Any], out_dir: Path, seed: int) -> Tuple[TreeManager, List[Dict[str, Any]]]:
    """Build vault through TreeManager with rich teasers and deterministic summaries."""
    # Initialize vault
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    mgr = TreeManager(out_dir)
    
    # Place facts
    for fact in specs["facts"]:
        entry = mgr.remember(
            fact=fact["fact"],
            hint=fact["path"],
            sensitivity=fact.get("sensitivity", "normal")
        )
        mgr.place(
            entry_id=entry["entry_id"],
            path=fact["path"],
            sensitivity=fact.get("sensitivity", "normal")
        )
    
    # Build deterministic summaries bottom-up
    all_paths = mgr.health_checker.get_all_node_paths()
    # Sort deepest first for bottom-up processing, include root at the end
    all_paths_sorted = sorted(all_paths, key=lambda p: (p.count("/"), p), reverse=True)
    
    # Process all nodes including root
    for path in all_paths_sorted:
        node = mgr.store.read_node(path)
        if not node:
            continue
        
        # Build rich teasers for children
        child_dirs = mgr.store.list_child_dirs(path)
        children_list = []
        
        for child in child_dirs:
            child_node = mgr.store.read_node(child)
            if child_node:
                # Rich teaser: include relation and a hint
                child_facts = child_node.facts[:2] if child_node.facts else []
                if child_facts:
                    fact_sample = child_facts[0].get("fact", "")[:40]
                    teaser = f"{fact_sample}..."
                else:
                    teaser = f"Details on {child}"
                
                # Override for private children
                if child_node.sensitivity == "private":
                    teaser = "contains private details, expand to view"
                
                children_list.append({"label": child, "teaser": teaser})
            else:
                children_list.append({"label": child, "teaser": f"Details on {child}"})
        
        # Build deterministic summary
        facts = node.facts
        if facts:
            # Summary template: topic + count + first fact
            first_fact = facts[0].get("fact", "")
            summary = f"{node.name}. Contains {len(facts)} facts. {first_fact[:80]}..."
        else:
            # Intermediate node: just summarize children
            summary = f"{node.name}. Parent of {len(children_list)} subtopics."
        
        # Ensure summary is within token limits
        while count_tokens(summary) > 120 and len(summary) > 20:
            summary = summary[:-4] + "..."
        
        # Build markdown
        md = f"""---
name: {node.name}
aliases: {node.aliases}
dirty: false
updated: {node.updated}
tokens: {count_tokens(summary)}
sensitivity: {node.sensitivity}
children_cap: {node.children_cap}
---
{summary}

## Children
"""
        for child in children_list:
            md += f"- [[{child['label']}]] - {child['teaser']}\n"
        
        # Add facts section if leaf
        if facts:
            md += "\n## Facts\n"
            for fact in facts:
                entry_id = fact.get("entry_id", "")
                fact_text = fact.get("fact", "")
                md += f"- {fact_text} (log: {entry_id})\n"
        
        # Commit summary
        mgr.commit_summary(path, md)
    
    return mgr, all_paths_sorted


def generate_scaled_questions(specs: Dict[str, Any], seed: int) -> List[Dict[str, Any]]:
    """Generate questions in the harness auto-detect format with exact counts.
    
    Fixed counts: 30 lookup, 10 overview, 4 private, 6 unanswerable = 50 questions.
    Questions are drawn evenly across top-level topics.
    """
    rng = random.Random(seed + 1)
    questions: List[Dict[str, Any]] = []
    
    candidates = specs["candidates"]
    rng.shuffle(candidates)
    
    # 30 lookup questions (single-fact)
    lookup_pool = candidates[:min(30, len(candidates))]
    for i, cand in enumerate(lookup_pool):
        style = "direct" if i % 2 == 0 else "paraphrase"
        questions.append({
            "id": f"q_lookup_{i:02d}",
            "question": cand.get(style, cand["direct"]),
            "keywords": [cand["answer"]],
            "private": False,
            "negative": False,
        })
    
    # 10 overview questions (multi-fact, need 2-6 facts)
    # Group facts by path
    path_facts: Dict[str, List[Dict]] = {}
    for fact in specs["facts"]:
        if fact["path"] not in path_facts:
            path_facts[fact["path"]] = []
        path_facts[fact["path"]].append(fact)
    
    # Get paths with enough facts for overview
    overview_paths = [p for p, f in path_facts.items() if len(f) >= 2]
    rng.shuffle(overview_paths)
    
    # If we don't have enough paths, reuse paths with different question phrasings
    overview_needed = 10
    path_index = 0
    
    for i in range(overview_needed):
        if path_index >= len(overview_paths):
            # Reuse paths cyclically
            path = overview_paths[path_index % len(overview_paths)]
        else:
            path = overview_paths[path_index]
        
        path_index += 1
        
        facts_in_path = path_facts[path][:6]  # Take up to 6 facts
        answers = [c["answer"] for c in specs["candidates"]
                   if c["path"] == path and any(f["relation"] == c["relation"] for f in facts_in_path)]
        
        # If we don't have enough answers from candidates, use fact text
        if len(answers) < 2:
            answers = [f["fact"][:30] for f in facts_in_path[:4]]
        
        # Format question based on path
        path_readable = path.replace("_", " ").replace("/", " > ")
        
        # Vary question phrasing
        if i % 3 == 0:
            question_text = f"Tell me about {path_readable}."
        elif i % 3 == 1:
            question_text = f"What do you know about {path_readable}?"
        else:
            question_text = f"Summarize the information about {path_readable}."
        
        questions.append({
            "id": f"q_overview_{i:02d}",
            "question": question_text,
            "keywords": answers,
            "require_all": True,
            "private": False,
            "negative": False,
        })
    
    # 4 private questions
    # Question text should NOT contain the secret value
    private_questions = [
        ("What is my bank routing number?", "987654321"),
        ("What is my social security number?", "123-45-6789"),
        ("What is my API key?", "sk-1234567890abcdef"),
        ("What is my credit card number?", "4532-1234-5678-9010")
    ]
    
    for i, (question_text, forbidden) in enumerate(private_questions):
        questions.append({
            "id": f"q_private_{i:02d}",
            "question": question_text,
            "keywords": [],
            "forbidden": [forbidden],
            "private": True,
            "negative": False,
        })
    
    # 6 unanswerable questions (facts not in vault)
    unanswerable_topics = [
        "favorite sports car brand",
        "shoe size",
        "middle name",
        "childhood best friend",
        "first pet's birthday",
        "favorite color"
    ]
    
    for i in range(6):
        questions.append({
            "id": f"q_unanswerable_{i:02d}",
            "question": f"What is his {unanswerable_topics[i]}?",
            "keywords": [],  # Will use NEGATIVE_KEYWORDS in grader
            "private": False,
            "negative": True,
        })
    
    return questions


def main():
    parser = argparse.ArgumentParser(description="Generate scalable vaults for TreeMem evaluation")
    parser.add_argument("--facts", type=int, required=True, help="Number of facts")
    parser.add_argument("--seed", type=int, default=7, help="Random seed")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    args = parser.parse_args()
    
    out_dir = Path(args.out)
    
    print(f"Generating vault with {args.facts} facts (seed {args.seed})...")
    
    # Build extended specs
    specs = build_extended_specs(args.seed, args.facts)
    facts = specs["facts"]
    
    print(f"Generated {len(facts)} facts")
    
    # Build vault through TreeManager
    mgr, all_paths = build_vault_through_manager(specs, out_dir, args.seed)
    
    # Check health
    health = mgr.health_checker.check_all()
    if not health["ok"]:
        print(f"ERROR: Vault health check failed: {health['violations']}")
        sys.exit(1)
    
    print(f"Vault built successfully: {len(facts)} facts, {len(all_paths)} nodes")
    
    # Generate questions
    questions = generate_scaled_questions(specs, args.seed + 1)
    
    # Verify question counts
    lookup_count = sum(1 for q in questions if not q.get("private") and not q.get("negative") and not q.get("require_all"))
    overview_count = sum(1 for q in questions if q.get("require_all"))
    private_count = sum(1 for q in questions if q.get("private"))
    negative_count = sum(1 for q in questions if q.get("negative"))
    
    print(f"Questions: {lookup_count} lookup, {overview_count} overview, {private_count} private, {negative_count} unanswerable = {len(questions)} total")
    
    # Save questions in harness format
    questions_file = out_dir.parent / f"{out_dir.name}_questions.json"
    with open(questions_file, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2)
    
    print(f"Questions saved to: {questions_file}")
    
    # Create manifest
    flat_log_tokens = 0
    log_dir = out_dir / "log"
    if log_dir.exists():
        for log_path in sorted(log_dir.glob("*.md")):
            flat_log_tokens += count_tokens(log_path.read_text(encoding="utf-8"))
    
    max_depth = max(p.count("/") for p in all_paths) if all_paths else 0
    
    manifest = {
        "fact_count": len(facts),
        "node_count": len(all_paths),
        "max_depth": max_depth,
        "flat_log_tokens": flat_log_tokens,
        "tokenizer": "cl100k_base",
        "seed": args.seed,
    }
    
    manifest_file = out_dir.parent / f"{out_dir.name}_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    
    print(f"Manifest saved to: {manifest_file}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
