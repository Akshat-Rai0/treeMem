#!/usr/bin/env python3
"""Deterministic scalable vault generator for TreeMem evaluation (generator v2).

    python bench/make_scaled_vault.py --facts 200 --seed 7 --out bench/vaults/scaled_200
    python bench/make_scaled_vault.py --all --seed 7            # sizes 50, 200, 1000, 5000

What a vault of N facts contains
--------------------------------
* 4 private facts (bank account numbers, node ``finance/accounts`` is private). They count
  toward N. The private questions ask for exactly these numbers, so a leak is observable.
* N - 4 public facts, chosen so that EVERY size covers many topics:
    - first the natural pool from ``make_midsize_vault.build_specs`` (9 topics, 57 leaf groups),
      taken round-robin across topics, at most 5 facts per group (a group may reach 6);
    - when the pool runs out, procedural facts (unique invented words, three templates)
      spread over three extra top-level topics, four levels deep, at most 6 facts per leaf and
      never more than 12 children per node.
* 50 questions: lookup + overview = 40, private = 4, unanswerable = 6. Overview questions
  need 2-6 facts each (one whole leaf). If fewer than 10 leaves qualify, there are fewer
  overview questions and more lookups; the manifest records the real counts.

Every answer keyword is a single unique token (or a unique multi-word name from the natural
pool), so "answer appears in exactly one fact" is checked by the tests.

The manifest stores sha256 hashes of the questions file and of the log; the runner stamps
them on every episode so results from a different question set can never be mixed in.
"""

import argparse
import hashlib
import json
import math
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from treemem.tokenizer import count_tokens  # noqa: E402
from treemem.tree_manager import TreeManager  # noqa: E402
from make_midsize_vault import FIRST, build_specs  # noqa: E402

GENERATOR_VERSION = "scaled_vault_v2"
SIZES = [50, 200, 1000, 5000]
PRIVATE_FACTS = 4
GROUP_CAP = 5            # natural-pool facts taken per group (a group may reach 6)
LEAF_MAX = 6             # procedural facts per leaf (also the overview upper bound)
OVERVIEW_TARGET = 10
TOTAL_QUESTIONS = 50

CATEGORIES = ["contacts", "projects", "collection"]
GROUPS = {
    "contacts": ["engineering", "design", "legal", "finance_team", "sales", "support",
                 "research", "operations", "marketing", "security", "people_ops", "facilities"],
    "projects": ["web", "mobile", "data", "infra", "ml", "hardware",
                 "internal", "consulting", "migration", "audit", "pilot", "archive"],
    "collection": ["lamps", "clocks", "maps", "tools", "rare_books", "ceramics",
                   "textiles", "instruments", "prints", "stamps", "coins", "tea_sets"],
}
SUBS = ["north", "south", "east", "west", "central", "harbor",
        "hills", "valley", "lakeside", "downtown", "uptown", "coast"]
LEAVES = [f"tier_{i}" for i in range(1, 13)]
ROLES = ["analyst", "engineer", "manager", "designer", "auditor", "coordinator", "advisor", "architect"]
KINDS = ["lamp", "clock", "map", "vase", "print", "kettle", "compass", "ledger"]
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


# ----------------------------------------------------------------------------
# hashing helpers (also imported by run_scaling.py)
# ----------------------------------------------------------------------------

def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def log_sha256(vault_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted((Path(vault_dir) / "log").glob("*.md")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def questions_path(vault_dir: Path) -> Path:
    return vault_dir.parent / f"{vault_dir.name}_questions.json"


def manifest_path(vault_dir: Path) -> Path:
    return vault_dir.parent / f"{vault_dir.name}_manifest.json"


def questions_v2_path(vault_dir: Path) -> Path:
    return vault_dir.parent / f"{vault_dir.name}_questions_v2.json"


def manifest_v2_path(vault_dir: Path) -> Path:
    return vault_dir.parent / f"{vault_dir.name}_manifest_v2.json"


# ----------------------------------------------------------------------------
# fact selection
# ----------------------------------------------------------------------------

def _round_robin(groups_by_topic: Dict[str, List[str]]) -> List[str]:
    """Interleave paths topic by topic (topics sorted, paths in given order)."""
    order: List[str] = []
    topics = sorted(groups_by_topic)
    index = 0
    while any(index < len(groups_by_topic[t]) for t in topics):
        for t in topics:
            if index < len(groups_by_topic[t]):
                order.append(groups_by_topic[t][index])
        index += 1
    return order


def select_natural(specs: Dict[str, Any], n_public: int, rng: random.Random) -> Tuple[List[Dict], List[Dict]]:
    """Pick up to n_public public facts from the natural pool, spread across topics."""
    public = [f for f in specs["facts"] if not f.get("private")]
    cands = [c for c in specs["candidates"]]
    assert len(public) == len(cands), "natural pool: candidates must pair 1:1 with public facts"
    pairs_by_path: Dict[str, List[Tuple[Dict, Dict]]] = {}
    for fact, cand in zip(public, cands):
        assert cand["answer"] in fact["fact"], "candidate answer must occur in its fact"
        pairs_by_path.setdefault(fact["path"], []).append((fact, cand))

    by_topic: Dict[str, List[str]] = {}
    for path in sorted(pairs_by_path):
        by_topic.setdefault(path.split("/")[0], []).append(path)
    for topic in by_topic:
        rng.shuffle(by_topic[topic])
    order = _round_robin(by_topic)

    take: Dict[str, int] = {}
    remaining = n_public
    for path in order:
        if remaining <= 0:
            break
        k = min(GROUP_CAP, len(pairs_by_path[path]), remaining)
        take[path] = k
        remaining -= k
    # A trailing group with a single fact is useless for overview questions: fold it
    # into earlier groups that still have room (up to 6 per group).
    for path in list(take):
        if take[path] == 1 and len(take) > 1:
            for other in take:
                if other != path and take[other] < min(LEAF_MAX, len(pairs_by_path[other])):
                    take[other] += 1
                    del take[path]
                    break
    # Distribute any leftover (when every group is at the cap but the pool still has room).
    if remaining > 0:
        for path in take:
            while remaining > 0 and take[path] < min(LEAF_MAX, len(pairs_by_path[path])):
                take[path] += 1
                remaining -= 1

    facts: List[Dict] = []
    cands_out: List[Dict] = []
    for path in order:
        if path in take:
            for fact, cand in pairs_by_path[path][: take[path]]:
                facts.append(dict(fact))
                cands_out.append(dict(cand))
    return facts, cands_out


class Namer:
    """Unique, fixed-length (3 syllables = 6 letters) invented words.

    Fixed length means one word can never be a substring of another, so
    "answer appears in exactly one fact" is well defined.
    """

    CONSONANTS = "bdfgklmnprstvz"
    VOWELS = "aeiou"

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set = set()

    def word(self) -> str:
        while True:
            w = "".join(self.rng.choice(self.CONSONANTS) + self.rng.choice(self.VOWELS) for _ in range(3)).capitalize()
            if w not in self.used:
                self.used.add(w)
                return w


def procedural_facts(n: int, rng: random.Random, taken_words: set) -> Tuple[List[Dict], List[Dict]]:
    """n procedural public facts in balanced leaves of at most LEAF_MAX facts."""
    if n <= 0:
        return [], []
    namer = Namer(rng)
    namer.used |= taken_words
    leaf_count = math.ceil(n / LEAF_MAX)
    k = max(1, math.ceil(round((leaf_count / len(CATEGORIES)) ** (1 / 3), 6)))
    if k > 12 or len(CATEGORIES) * k ** 3 < leaf_count:
        raise ValueError(f"cannot place {n} procedural facts within the branching cap of 12")
    base, extra = divmod(n, leaf_count)
    facts: List[Dict] = []
    cands: List[Dict] = []
    for i in range(leaf_count):
        cat_i = i % len(CATEGORIES)
        rest = i // len(CATEGORIES)
        leaf_i = rest % k
        rest //= k
        sub_i = rest % k
        group_i = rest // k
        cat = CATEGORIES[cat_i]
        path = f"{cat}/{GROUPS[cat][group_i]}/{SUBS[sub_i]}/{LEAVES[leaf_i]}"
        size = base + (1 if i < extra else 0)
        for _ in range(size):
            if cat == "contacts":
                person = f"{rng.choice(FIRST)} {namer.word()}"
                company = namer.word()
                role = rng.choice(ROLES)
                fact = f"{person} works at {company} as a {role}."
                cand = {"relation": "contact", "answer": company,
                        "direct": f"Where does {person} work?",
                        "paraphrase": f"Which company employs {person}?"}
            elif cat == "projects":
                code = namer.word()
                client = namer.word()
                when = f"{rng.choice(MONTHS)} {rng.randint(2016, 2025)}"
                fact = f"Project {code} was delivered to the client {client} in {when}."
                cand = {"relation": "project_client", "answer": client,
                        "direct": f"Which client was project {code} delivered to?",
                        "paraphrase": f"Who was the customer for project {code}?"}
            else:
                item = namer.word()
                maker = namer.word()
                kind = rng.choice(KINDS)
                city = rng.choice(["Lisbon", "Kyoto", "Oslo", "Lima", "Cairo", "Hanoi"])
                fact = f"He bought the {item} {kind} from the maker {maker} in {city}."
                cand = {"relation": "collection_maker", "answer": maker,
                        "direct": f"Who made the {item} {kind}?",
                        "paraphrase": f"Which maker produced the {item} {kind}?"}
            cand["path"] = path
            facts.append({"path": path, "fact": fact, "relation": cand["relation"]})
            cands.append(cand)
    return facts, cands


def build_extended_specs(seed: int, n_facts: int) -> Dict[str, Any]:
    """Facts, candidates, private questions and negatives for a vault of n_facts facts."""
    if n_facts < PRIVATE_FACTS + 10:
        raise ValueError("n_facts must be at least 14")
    base = build_specs(seed)
    rng = random.Random(seed * 7919 + n_facts)

    private_facts = [f for f in base["facts"] if f.get("private")][:PRIVATE_FACTS]
    private_questions = base["private_questions"][:PRIVATE_FACTS]
    assert len(private_facts) == PRIVATE_FACTS and len(private_questions) == PRIVATE_FACTS

    n_public = n_facts - PRIVATE_FACTS
    natural_facts, natural_cands = select_natural(base, n_public, rng)
    rest = n_public - len(natural_facts)
    taken = {w for c in natural_cands for w in c["answer"].split()}
    proc_facts, proc_cands = procedural_facts(rest, rng, taken)

    return {
        "facts": natural_facts + proc_facts + [dict(f) for f in private_facts],
        "candidates": natural_cands + proc_cands,
        "private_questions": private_questions,
        "negatives": base["negatives"][:6],
        "seed": seed,
    }


# ----------------------------------------------------------------------------
# building the vault through the real TreeManager
# ----------------------------------------------------------------------------

def build_vault_through_manager(specs: Dict[str, Any], out_dir: Path) -> Tuple[TreeManager, List[str]]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mgr = TreeManager(out_dir)

    for fact in specs["facts"]:
        sensitivity = "private" if fact.get("private") else "normal"
        entry = mgr.remember(fact=fact["fact"], hint=fact["path"], sensitivity=sensitivity)
        mgr.place(entry_id=entry["entry_id"], path=fact["path"], sensitivity=sensitivity)

    all_paths = mgr.health_checker.get_all_node_paths()
    bottom_up = sorted(all_paths, key=lambda p: (p.count("/") + (1 if p else 0), p), reverse=True)
    summaries: Dict[str, str] = {}
    for path in bottom_up:
        node = mgr.store.read_node(path)
        if node is None:
            continue
        child_names = mgr.store.list_child_dirs(path)
        if node.facts and node.sensitivity == "private":
            summary = f"{node.name}. Contains {len(node.facts)} private facts."
        elif node.facts:
            first = node.facts[0].get("fact", "")
            summary = f"{node.name or 'root'}. Contains {len(node.facts)} facts. {first[:80]}"
        elif child_names:
            summary = f"{node.name or 'root'}. Subtopics: {', '.join(child_names)}."
        else:
            summary = f"{node.name or 'root'}."
        while count_tokens(summary) > 120 and len(summary) > 20:
            summary = summary[:-4]
        summaries[path] = summary

        lines = [summary, "", "## Children"]
        for child in child_names:
            child_path = f"{path}/{child}" if path else child
            teaser = summaries.get(child_path, f"Details on {child}")[:70]
            lines.append(f"- [[{child}]] - {teaser}")
        text = "---\nname: {}\n---\n{}\n".format(node.name or "root", "\n".join(lines))
        res = mgr.commit_summary(path, text)
        if not res.get("ok"):
            raise RuntimeError(f"commit_summary failed for '{path}': {res}")
    return mgr, all_paths


# ----------------------------------------------------------------------------
# questions
# ----------------------------------------------------------------------------

def humanize(path: str) -> str:
    return path.replace("_", " ").replace("/", " > ")


def generate_questions(specs: Dict[str, Any], seed: int) -> List[Dict[str, Any]]:
    rng = random.Random(seed * 104729 + len(specs["facts"]))
    public_facts = [f for f in specs["facts"] if not f.get("private")]
    fact_by_answer: Dict[str, Dict] = {}
    for fact, cand in zip(public_facts, specs["candidates"]):
        fact_by_answer[cand["answer"]] = fact

    # An answer is usable only if it occurs in exactly one fact of THIS vault (the natural
    # pool has names such as "Copper Anchor" that are a prefix of another venue's name).
    corpus = [f["fact"].lower() for f in specs["facts"]]
    ambiguous = {
        cand["answer"] for cand in specs["candidates"]
        if len(cand["answer"]) < 5 or sum(1 for text in corpus if cand["answer"].lower() in text) != 1
    }

    facts_by_path: Dict[str, List[Tuple[Dict, Dict]]] = {}
    for fact, cand in zip(public_facts, specs["candidates"]):
        facts_by_path.setdefault(fact["path"], []).append((fact, cand))

    def by_topic(paths: List[str]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for p in sorted(paths):
            out.setdefault(p.split("/")[0], []).append(p)
        for t in out:
            rng.shuffle(out[t])
        return out

    # overview: whole leaves with 2..6 facts, interleaved across topics
    eligible = [
        p for p, pairs in facts_by_path.items()
        if 2 <= len(pairs) <= LEAF_MAX and not any(cand["answer"] in ambiguous for _, cand in pairs)
    ]
    overview_paths = _round_robin(by_topic(eligible))[:OVERVIEW_TARGET]
    questions: List[Dict[str, Any]] = []
    n_lookup = TOTAL_QUESTIONS - len(specs["private_questions"]) - len(specs["negatives"]) - len(overview_paths)

    # lookup: interleave topics, one candidate at a time
    cands_by_topic: Dict[str, List[Tuple[Dict, Dict]]] = {}
    for fact, cand in zip(public_facts, specs["candidates"]):
        if cand["answer"] in ambiguous:
            continue
        cands_by_topic.setdefault(fact["path"].split("/")[0], []).append((fact, cand))
    for t in cands_by_topic:
        rng.shuffle(cands_by_topic[t])
    picked: List[Tuple[Dict, Dict]] = []
    cursor = 0
    topics = sorted(cands_by_topic)
    while len(picked) < n_lookup and any(cursor < len(cands_by_topic[t]) for t in topics):
        for t in topics:
            if cursor < len(cands_by_topic[t]) and len(picked) < n_lookup:
                picked.append(cands_by_topic[t][cursor])
        cursor += 1
    for i, (fact, cand) in enumerate(picked):
        style = "direct" if i % 2 == 0 else "paraphrase"
        questions.append({
            "id": f"q_lookup_{i:02d}",
            "question": cand[style],
            "keywords": [cand["answer"]],
            "private": False,
            "negative": False,
            "path": fact["path"],
            "gold_facts": [fact["fact"]],
        })

    for i, path in enumerate(overview_paths):
        pairs = facts_by_path[path]
        readable = humanize(path)
        phrase = [f"Tell me about {readable}.", f"What do you know about {readable}?",
                  f"Summarize the information about {readable}."][i % 3]
        questions.append({
            "id": f"q_overview_{i:02d}",
            "question": phrase,
            "keywords": [cand["answer"] for _, cand in pairs],
            "require_all": True,
            "private": False,
            "negative": False,
            "path": path,
            "gold_facts": [fact["fact"] for fact, _ in pairs],
        })

    for i, item in enumerate(specs["private_questions"]):
        style = "direct" if i % 2 == 0 else "paraphrase"
        questions.append({
            "id": f"q_private_{i:02d}",
            "question": item[style],
            "keywords": [],
            "forbidden": list(item["forbidden"]),
            "private": True,
            "negative": False,
        })

    for i, item in enumerate(specs["negatives"]):
        style = "direct" if i % 2 == 0 else "paraphrase"
        questions.append({
            "id": f"q_unanswerable_{i:02d}",
            "question": item[style],
            "keywords": [],
            "private": False,
            "negative": True,
        })
    return questions


def generate_questions_v2(
    specs: Dict[str, Any], seed: int, v1_questions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return v2 question list: v1 lookups, privates, unanswerables unchanged + 10 composites replacing overviews."""
    n_facts = len(specs["facts"])
    rng = random.Random(f"{seed}-composite-{n_facts}")

    public_facts = [f for f in specs["facts"] if not f.get("private")]
    corpus = [f["fact"].lower() for f in specs["facts"]]
    v1_lookup_gold = {
        gf for q in v1_questions
        if not (q["private"] or q["negative"] or q.get("require_all"))
        for gf in q.get("gold_facts", [])
    }

    pairs_by_path: Dict[str, List[Tuple[Dict, Dict]]] = {}
    for fact, cand in zip(public_facts, specs["candidates"]):
        pairs_by_path.setdefault(fact["path"], []).append((fact, cand))

    def _get_eligible(path: str, exclude_gold: bool = True) -> List[Tuple[Dict, Dict]]:
        res = []
        for fact, cand in pairs_by_path.get(path, []):
            ans = cand["answer"]
            if len(ans) < 5:
                continue
            if sum(1 for t in corpus if ans.lower() in t) != 1:
                continue
            if exclude_gold and fact["fact"] in v1_lookup_gold:
                continue
            res.append((fact, cand))
        return res

    leaves_by_topic: Dict[str, List[str]] = {}
    for path in sorted(pairs_by_path):
        if len(pairs_by_path[path]) >= 3 and len(_get_eligible(path, exclude_gold=True)) >= 3:
            topic = path.split("/")[0]
            leaves_by_topic.setdefault(topic, []).append(path)

    for topic in leaves_by_topic:
        rng.shuffle(leaves_by_topic[topic])
    rr_leaves = _round_robin(leaves_by_topic)

    chosen_leaves: List[Tuple[str, List[Tuple[Dict, Dict]]]] = []
    for path in rr_leaves:
        if len(chosen_leaves) == OVERVIEW_TARGET:
            break
        eligible = _get_eligible(path, exclude_gold=True)
        if len(eligible) >= 3:
            chosen_leaves.append((path, eligible[:3]))

    # Fallback if a small vault (e.g. size 50) has too few non-lookup facts
    if len(chosen_leaves) < OVERVIEW_TARGET:
        used_paths = {p for p, _ in chosen_leaves}
        fallback_by_topic: Dict[str, List[str]] = {}
        for path in sorted(pairs_by_path):
            if path not in used_paths and len(pairs_by_path[path]) >= 3 and len(_get_eligible(path, exclude_gold=False)) >= 3:
                topic = path.split("/")[0]
                fallback_by_topic.setdefault(topic, []).append(path)
        for topic in fallback_by_topic:
            rng.shuffle(fallback_by_topic[topic])
        for path in _round_robin(fallback_by_topic):
            if len(chosen_leaves) == OVERVIEW_TARGET:
                break
            eligible = _get_eligible(path, exclude_gold=False)
            if len(eligible) >= 3:
                chosen_leaves.append((path, eligible[:3]))

    composites: List[Dict[str, Any]] = []
    for idx, (path, chosen) in enumerate(chosen_leaves):
        fact1, cand1 = chosen[0]
        fact2, cand2 = chosen[1]
        fact3, cand3 = chosen[2]
        c1d = cand1["direct"]
        c2p = cand2["paraphrase"]
        c3d = cand3["direct"]
        text = f"Answer all three questions. (1) {c1d} (2) {c2p} (3) {c3d}"

        assert ">" not in text, f"composite text contains '>': {text}"
        assert "tier_" not in text, f"composite text contains 'tier_': {text}"
        for seg in path.split("/")[1:-1]:
            assert seg not in text, f"composite text contains internal path segment '{seg}': {text}"

        composites.append({
            "id": f"q_composite_{idx:02d}",
            "question": text,
            "keywords": [cand1["answer"], cand2["answer"], cand3["answer"]],
            "require_all": True,
            "composite": True,
            "private": False,
            "negative": False,
            "path": path,
            "gold_facts": [fact1["fact"], fact2["fact"], fact3["fact"]],
        })

    v1_lookups = [dict(q) for q in v1_questions if not (q["private"] or q["negative"] or q.get("require_all"))]
    v1_privates = [dict(q) for q in v1_questions if q["private"]]
    v1_negatives = [dict(q) for q in v1_questions if q["negative"]]

    return v1_lookups + composites + v1_privates + v1_negatives


# ----------------------------------------------------------------------------
# driver
# ----------------------------------------------------------------------------

def generate(n_facts: int, seed: int, out_dir: Path, quiet: bool = False,
             questions_v2: bool = False) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    specs = build_extended_specs(seed, n_facts)
    mgr, all_paths = build_vault_through_manager(specs, out_dir)
    health = mgr.health_checker.check_all()
    if not health["ok"]:
        raise RuntimeError(f"vault health check failed: {health['violations'][:5]}")

    questions = generate_questions(specs, seed)
    qfile = questions_path(out_dir)
    qfile.write_text(json.dumps(questions, indent=2), encoding="utf-8")

    log_tokens = sum(count_tokens(p.read_text(encoding="utf-8")) for p in sorted((out_dir / "log").glob("*.md")))
    topics = sorted({f["path"].split("/")[0] for f in specs["facts"]})
    manifest = {
        "generator": GENERATOR_VERSION,
        "seed": seed,
        "fact_count": len(specs["facts"]),
        "public_facts": sum(1 for f in specs["facts"] if not f.get("private")),
        "private_facts": sum(1 for f in specs["facts"] if f.get("private")),
        "node_count": len(all_paths),
        "max_depth": max((p.count("/") + 1 for p in all_paths if p), default=0),
        "topics": topics,
        "topic_count": len(topics),
        "flat_log_tokens": log_tokens,
        "tokenizer": "cl100k_base",
        "questions": {
            "lookup": sum(1 for q in questions if not (q["private"] or q["negative"] or q.get("require_all"))),
            "overview": sum(1 for q in questions if q.get("require_all")),
            "private": sum(1 for q in questions if q["private"]),
            "unanswerable": sum(1 for q in questions if q["negative"]),
            "total": len(questions),
        },
        "questions_sha256": file_sha256(qfile),
        "log_sha256": log_sha256(out_dir),
    }
    manifest_path(out_dir).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if questions_v2:
        v2_questions = generate_questions_v2(specs, seed, questions)
        v2_qfile = questions_v2_path(out_dir)
        v2_qfile.write_text(json.dumps(v2_questions, indent=2), encoding="utf-8")
        v2_manifest = dict(manifest)
        v2_manifest["questions_v2_sha256"] = file_sha256(v2_qfile)
        manifest_v2_path(out_dir).write_text(json.dumps(v2_manifest, indent=2), encoding="utf-8")

    if not quiet:
        print(f"[{out_dir.name}] {manifest['fact_count']} facts, {manifest['node_count']} nodes, "
              f"{manifest['topic_count']} topics, depth {manifest['max_depth']}, "
              f"questions {manifest['questions']}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate scalable vaults for TreeMem evaluation")
    parser.add_argument("--facts", type=int, help="Number of facts (including 4 private)")
    parser.add_argument("--all", action="store_true", help=f"Generate sizes {SIZES} under --root")
    parser.add_argument("--root", type=str, default=str(Path(__file__).parent / "vaults"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=str, help="Output directory (with --facts)")
    parser.add_argument("--questions-v2", action="store_true",
                        help="Also generate v2 composite questions and manifest")
    args = parser.parse_args()

    if args.all:
        for size in SIZES:
            generate(size, args.seed, Path(args.root) / f"scaled_{size}",
                     questions_v2=args.questions_v2)
        return
    if not args.facts or not args.out:
        parser.error("use --all, or both --facts and --out")
    generate(args.facts, args.seed, Path(args.out), questions_v2=args.questions_v2)


if __name__ == "__main__":
    main()
