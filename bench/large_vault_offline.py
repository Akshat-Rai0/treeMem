"""Offline retrieval benchmark on the mid-size vault (no API calls, no keys).

For each question it measures what each strategy would put in front of the model:

  flat           the whole log (always contains the answer, but its size grows with the vault)
  bm25_top5      one-shot retrieval of the 5 best matching facts (a standard RAG baseline)
  tree_follow    ONE recall(path="/", query, follow=True) call, with the real gate

and whether the returned text contains the expected answer ("answerable"). This does NOT measure whether a
language model would then answer correctly; it measures retrieval and routing only.

Estimated wire tokens add the fixed per-call cost measured in the committed real-LLM runs (system prompt and tool
schemas re-sent on every call). That part is a model, labelled as such in the output.

    python bench/large_vault_offline.py            # prints the report and writes bench/results_offline/large_vault_offline.json
"""

import argparse
import glob
import importlib.util
import json
import statistics
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from treemem.descent_gate import DescentGate
from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FLAT_OVERHEAD = 165     # measured: flat wire tokens minus memory payload (about 159 to 165)
DEFAULT_CALL_OVERHEAD = 1400    # measured: single-call guided questions, wire tokens minus payload (about 1,360 to 1,460)
EXTRA_CALL_PAYLOAD = 100        # assumed size of one extra expand result


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measured_overheads() -> Dict[str, Any]:
    """Derive per-call overheads from committed real-LLM run files if they exist, else use the defaults."""
    flat_values: List[int] = []
    call_values: List[int] = []
    for run_file in glob.glob(str(ROOT / "bench" / "results*" / "llm_eval_runs" / "run_*.json")):
        try:
            data = json.loads(Path(run_file).read_text(encoding="utf-8"))
        except Exception:
            continue
        for question in data.get("questions", []):
            flat = question.get("flat")
            if flat and not flat.get("leaked"):
                flat_values.append(flat["api_total_tokens"] - flat["payload_tokens"])
            follow = question.get("tree_follow")
            if follow and follow.get("hops") == 1:
                call_values.append(follow["api_total_tokens"] - follow["payload_tokens"])
    return {
        "flat_overhead": round(statistics.median(flat_values)) if flat_values else DEFAULT_FLAT_OVERHEAD,
        "call_overhead": round(statistics.median(call_values)) if call_values else DEFAULT_CALL_OVERHEAD,
        "flat_samples": len(flat_values),
        "call_samples": len(call_values),
    }


def returned_text(result: Dict[str, Any]) -> str:
    parts = [result.get("summary", "")]
    for child in result.get("children", []):
        parts.append(f"{child.get('label', '')} {child.get('teaser', '')}")
    for fact in result.get("facts", []):
        parts.append(fact.get("fact", ""))
    search = result.get("search")
    if search:
        parts.append(json.dumps(search.get("hits", [])))
    return "\n".join(parts)


def contains_answer(text: str, keywords: List[str], require_all: bool = False) -> bool:
    lowered = text.lower()
    found = [keyword.lower() in lowered for keyword in keywords]
    if not found:
        return False
    return all(found) if require_all else any(found)


def evaluate_vault(
    manager: TreeManager,
    questions: List[Dict[str, Any]],
    label: str,
    overheads: Dict[str, Any],
) -> Dict[str, Any]:
    log_text = "".join(Path(f).read_text(encoding="utf-8") for f in sorted(glob.glob(str(manager.root_dir / "log" / "*.md"))))
    flat_tokens = count_tokens(log_text)
    fact_count = sum(1 for line in log_text.splitlines() if "fact:" in line)

    rows: List[Dict[str, Any]] = []
    for item in questions:
        question = item["question"]
        private = bool(item.get("private"))
        negative = bool(item.get("negative")) or item["id"].startswith("q12")
        keywords = item.get("keywords", [])
        forbidden = item.get("forbidden", [])
        require_all = bool(item.get("require_all"))
        overview = require_all

        bm25 = manager.search(question, limit=5)
        bm25_text = json.dumps(bm25["hits"])
        bm25_tokens = count_tokens(bm25_text)

        follow = manager.recall("/", query=question, follow=True)
        follow_text = returned_text(follow)

        row = {
            "id": item["id"],
            "kind": "private" if private else ("negative" if negative else ("overview" if overview else "normal")),
            "style": item.get("style", ""),
            "tree_tokens": follow["tokens"],
            "tree_steps": follow["steps"],
            "tree_reason": follow["stopped_reason"],
            "tree_final_path": follow["final_path"],
            "bm25_tokens": bm25_tokens,
            "leaked_tree": any(f in follow_text for f in forbidden),
            "leaked_bm25": any(f in bm25_text for f in forbidden),
        }
        if not private and not negative:
            row["tree_answerable"] = contains_answer(follow_text, keywords, require_all)
            row["bm25_answerable"] = contains_answer(bm25_text, keywords, require_all)
        rows.append(row)

    lookups = [r for r in rows if r["kind"] == "normal"]
    overviews = [r for r in rows if r["kind"] == "overview"]
    normal = lookups + overviews
    premature = [r["id"] for r in normal if not r["tree_answerable"] and r["tree_reason"] in ("stop", "leaf")]
    flat_overhead = overheads["flat_overhead"]
    call_overhead = overheads["call_overhead"]

    def tree_wire(row: Dict[str, Any]) -> int:
        wire = call_overhead + row["tree_tokens"]
        if not row["tree_answerable"]:
            wire += call_overhead + EXTRA_CALL_PAYLOAD   # assume the agent needs one more call
        return wire

    summary = {
        "label": label,
        "facts": fact_count,
        "questions_normal": len(normal),
        "lookup_questions": len(lookups),
        "overview_questions": len(overviews),
        "bm25_lookup_answerable": sum(1 for r in lookups if r["bm25_answerable"]),
        "tree_lookup_answerable": sum(1 for r in lookups if r["tree_answerable"]),
        "bm25_overview_complete": sum(1 for r in overviews if r["bm25_answerable"]),
        "tree_overview_complete": sum(1 for r in overviews if r["tree_answerable"]),
        "flat_log_tokens": flat_tokens,
        "flat_wire_estimate": flat_overhead + flat_tokens,
        "bm25_answerable": sum(1 for r in normal if r["bm25_answerable"]),
        "bm25_mean_tokens": round(statistics.mean(r["bm25_tokens"] for r in normal), 1) if normal else 0.0,
        "bm25_wire_estimate": round(flat_overhead + statistics.mean(r["bm25_tokens"] for r in normal)) if normal else 0,
        "tree_answerable": sum(1 for r in normal if r["tree_answerable"]),
        "tree_premature_stops": premature,
        "tree_mean_tokens": round(statistics.mean(r["tree_tokens"] for r in normal), 1) if normal else 0.0,
        "tree_mean_steps": round(statistics.mean(r["tree_steps"] for r in normal), 2) if normal else 0.0,
        "tree_wire_estimate": round(statistics.mean(tree_wire(r) for r in normal)) if normal else 0,
        "private_leaks_tree": sum(1 for r in rows if r["leaked_tree"]),
        "private_leaks_bm25": sum(1 for r in rows if r["leaked_bm25"]),
    }
    return {"summary": summary, "rows": rows}


def build_midsize(seed: int, teaser_style: str = "rich") -> Dict[str, Any]:
    midsize = _load("make_midsize_vault_for_eval", ROOT / "bench" / "make_midsize_vault.py")
    work = Path(tempfile.mkdtemp(prefix="midsize_vault_")) / "vault"
    built = midsize.build_vault(work, seed, teaser_style)
    return {"manager": built["manager"], "questions": built["questions"]}


def build_sample() -> Dict[str, Any]:
    import shutil

    gate_eval = _load("gate_offline_eval_for_large", ROOT / "bench" / "gate_offline_eval.py")
    questions, _grade = gate_eval.load_questions("all")
    work = Path(tempfile.mkdtemp(prefix="sample_vault_")) / "vault"
    shutil.copytree(ROOT / "examples" / "sample_memory", work, ignore=shutil.ignore_patterns(".locks", ".events", "__pycache__", ".DS_Store"))
    return {"manager": TreeManager(work), "questions": questions}


def print_report(result: Dict[str, Any]) -> None:
    s = result["summary"]
    print(f"\n=== {s['label']} ({s['facts']} facts; {s['lookup_questions']} lookups + {s['overview_questions']} overviews) ===")
    print(f"flat:        log {s['flat_log_tokens']} tokens | est. wire {s['flat_wire_estimate']}")
    print(
        f"bm25 top-5:  lookups {s['bm25_lookup_answerable']}/{s['lookup_questions']}, overviews complete {s['bm25_overview_complete']}/{s['overview_questions']} "
        f"| mean {s['bm25_mean_tokens']} tokens | est. wire {s['bm25_wire_estimate']}"
    )
    print(
        f"tree follow: lookups {s['tree_lookup_answerable']}/{s['lookup_questions']}, overviews complete {s['tree_overview_complete']}/{s['overview_questions']} "
        f"| mean {s['tree_mean_tokens']} tokens | mean steps {s['tree_mean_steps']} | est. wire {s['tree_wire_estimate']}"
    )
    print(f"tree premature stops: {s['tree_premature_stops']}")
    print(f"private leaks: tree {s['private_leaks_tree']}, bm25 {s['private_leaks_bm25']}")


def run(seed: int = 7) -> Dict[str, Any]:
    overheads = measured_overheads()
    sample = build_sample()
    midsize_rich = build_midsize(seed, "rich")
    midsize_minimal = build_midsize(seed, "minimal")
    results = {
        "seed": seed,
        "scikit_learn_installed": DescentGate._semantic_enabled(),
        "overheads": overheads,
        "assumptions": {
            "extra_call_payload_tokens": EXTRA_CALL_PAYLOAD,
            "note": "Wire estimates are a model: measured per-call overhead plus returned tokens, plus one extra call when the first call does not contain the answer.",
        },
        "vaults": [
            evaluate_vault(sample["manager"], sample["questions"], "sample vault", overheads)["summary"],
            evaluate_vault(midsize_minimal["manager"], midsize_minimal["questions"], "mid-size vault, minimal teasers", overheads)["summary"],
            evaluate_vault(midsize_rich["manager"], midsize_rich["questions"], "mid-size vault, rich teasers", overheads)["summary"],
        ],
    }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline large-vault retrieval benchmark.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="bench/results_offline/large_vault_offline.json")
    args = parser.parse_args()

    results = run(args.seed)
    for vault in results["vaults"]:
        print_report({"summary": vault})
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
