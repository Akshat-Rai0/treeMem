#!/usr/bin/env python3
"""Prepare an agent-in-the-loop accuracy evaluation (e.g. Devin connected to TreeMem over MCP).

    python bench/make_scaled_vault.py --facts 1000 --seed 7 --out bench/vaults/scaled_1000
    python bench/agent_eval/make_batches.py --size 1000

For each arm (treemem, bm25, grep) this writes, under bench/agent_eval/runs/size_<N>/<arm>/:
    batch_XX_questions.json   [{id, question}]  (no keywords, no gold facts, no flags)
    prompt_batch_XX.txt       a complete, ready-to-paste prompt for a FRESH agent session
    order.json                the shuffled question order for that arm
plus manifest.json (hashes of the questions file and the log), a private vault copy per MCP arm
(so each arm has its own event log) and the grep workspace (memory_log.md).

The question ORDER is shuffled per arm (seeded) so position effects do not line up across arms.
"""

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from make_scaled_vault import file_sha256, log_sha256, questions_path  # noqa: E402

ARMS = ["treemem", "bm25", "grep"]
DEFAULT_ROOT = HERE / "runs"
VAULT_ROOT = HERE.parent / "vaults"

NOT_IN_MEMORY = "No information in memory."   # must be accepted by the committed grader (see tests)
PRIVATE_ANSWER = "That information is private."

COMMON_RULES = f"""You are being evaluated as a personal assistant. Everything you know about the user comes ONLY from the memory source described below.
Evaluation rules (they matter more than being helpful):
- Never use the web, search engines, or any file or folder other than what is named below.
- If the memory does not contain the answer, answer exactly: {NOT_IN_MEMORY}
- If the tool says the information is private or withheld, answer exactly: {PRIVATE_ANSWER}
- Answer each question in one or two sentences with the specific fact(s) asked for. For "tell me about / what do you know about / summarize" questions, include every relevant fact you find.
- Do not guess. Do not use general knowledge about the world."""

ARM_RULES = {
    "treemem": """MEMORY SOURCE: the TreeMem MCP server connected to this session (tools: recall, expand, search, status).
- Use ONLY these TreeMem tools. Do not use a shell, a browser, or the filesystem at all.
- This is a read-only evaluation: never call remember, place, commit_summary, compress, auto_compress, split or rebuild, and never pass reveal=true.
- Suggested approach: recall the root ("/"), read the parent summaries, and descend only into the branches the question needs (recall with a path, or follow=true with a query).""",
    "bm25": """MEMORY SOURCE: the TreeMem MCP server connected to this session, but you may use ONLY its `search` tool (use limit 5; you may search several times with different queries).
- Do not call any other TreeMem tool (no recall, expand, status, remember, place, ...). Do not use a shell, a browser, or the filesystem at all.
- Never pass reveal=true.""",
    "grep": """MEMORY SOURCE: the single file memory_log.md in your current workspace folder.
- You may use shell tools (grep, cat, head, sed, etc.) ONLY on that file. Do not open any other file, do not list parent folders, do not use the web.
- Do not install anything and do not write any file.""",
}

OUTPUT_FORMAT = """When you have answered every question, reply with ONLY a JSON array, one object per question, in the same order:
[{"id": "<question id>", "answer": "<your answer>"}, ...]
No text before or after the JSON."""


def build_prompt(arm: str, batch_no: int, n_batches: int, questions: List[Dict[str, str]]) -> str:
    listing = json.dumps(questions, indent=2, ensure_ascii=False)
    return (
        f"{COMMON_RULES}\n\n{ARM_RULES[arm]}\n\n"
        f"This is batch {batch_no} of {n_batches}. Answer these {len(questions)} questions:\n\n{listing}\n\n{OUTPUT_FORMAT}\n"
    )


def make(size: int, arms: List[str], batch_size: int, seed: int, root: Path = DEFAULT_ROOT,
         vault_root: Path = VAULT_ROOT, prepare: bool = True) -> Dict[str, Any]:
    vault = vault_root / f"scaled_{size}"
    qfile = questions_path(vault)
    if not vault.exists() or not qfile.exists():
        raise FileNotFoundError(f"Missing {vault} or its questions. Run: python bench/make_scaled_vault.py --facts {size} --seed {seed} --out {vault}")
    questions = json.loads(qfile.read_text(encoding="utf-8"))
    out = root / f"size_{size}"
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "size": size, "seed": seed, "batch_size": batch_size, "arms": arms,
        "question_count": len(questions),
        "questions_sha256": file_sha256(qfile), "log_sha256": log_sha256(vault),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    for arm in arms:
        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm!r}")
        arm_dir = out / arm
        if arm_dir.exists():
            shutil.rmtree(arm_dir)
        arm_dir.mkdir(parents=True)
        order = [q["id"] for q in questions]
        random.Random(f"{seed}-{size}-{arm}").shuffle(order)
        (arm_dir / "order.json").write_text(json.dumps(order, indent=2), encoding="utf-8")
        by_id = {q["id"]: q for q in questions}
        batches = [order[i:i + batch_size] for i in range(0, len(order), batch_size)]
        for n, ids in enumerate(batches, start=1):
            visible = [{"id": i, "question": by_id[i]["question"]} for i in ids]   # nothing else leaves this script
            (arm_dir / f"batch_{n:02d}_questions.json").write_text(json.dumps(visible, indent=2, ensure_ascii=False), encoding="utf-8")
            (arm_dir / f"prompt_batch_{n:02d}.txt").write_text(build_prompt(arm, n, len(batches), visible), encoding="utf-8")

        if prepare and arm in ("treemem", "bm25"):
            target = out / "vaults" / arm
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(vault, target, ignore=shutil.ignore_patterns(".events", "__pycache__"))
        if prepare and arm == "grep":
            ws = out / "grep_workspace"
            ws.mkdir(exist_ok=True)
            text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((vault / "log").glob("*.md")))
            (ws / "memory_log.md").write_text(text, encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare batches and prompts for an agent-in-the-loop evaluation")
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--arms", nargs="+", default=ARMS, choices=ARMS)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--root", type=str, default=str(DEFAULT_ROOT))
    args = ap.parse_args()
    m = make(args.size, args.arms, args.batch_size, args.seed, Path(args.root))
    print(f"Prepared {len(args.arms)} arms x {-(-m['question_count'] // args.batch_size)} batches under {Path(args.root) / f'size_{args.size}'}")


if __name__ == "__main__":
    main()
