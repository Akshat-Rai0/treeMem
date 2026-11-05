"""Scaled vault generator v2: questions must be answerable from the vault, at every size."""

import collections
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))


def _load():
    spec = importlib.util.spec_from_file_location("make_scaled_vault", ROOT / "bench" / "make_scaled_vault.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load()
import make_midsize_vault as base  # noqa: E402

SIZES = [50, 200, 1000, 5000]


def _all_text(specs):
    return "\n".join(f["fact"] for f in specs["facts"]).lower()


def _count(needle: str, specs) -> int:
    return sum(1 for f in specs["facts"] if needle.lower() in f["fact"].lower())


@pytest.fixture(scope="module")
def specs_by_size():
    out = {}
    for n in SIZES:
        specs = gen.build_extended_specs(7, n)
        out[n] = (specs, gen.generate_questions(specs, 7))
    return out


@pytest.mark.parametrize("n", SIZES)
def test_counts_and_topic_diversity(specs_by_size, n):
    specs, questions = specs_by_size[n]
    assert len(specs["facts"]) == n
    assert sum(1 for f in specs["facts"] if f.get("private")) == 4
    topics = {f["path"].split("/")[0] for f in specs["facts"]}
    assert len(topics) >= 9, f"size {n} only covers {sorted(topics)}"
    assert len(topics) <= 12  # top-level branching cap
    kinds = collections.Counter(
        "private" if q["private"] else "negative" if q["negative"] else "overview" if q.get("require_all") else "lookup"
        for q in questions
    )
    assert kinds["private"] == 4 and kinds["negative"] == 6
    assert kinds["lookup"] + kinds["overview"] == 40
    assert kinds["overview"] >= 8


@pytest.mark.parametrize("n", SIZES)
def test_no_duplicate_facts(specs_by_size, n):
    specs, _ = specs_by_size[n]
    texts = [f["fact"] for f in specs["facts"]]
    assert len(texts) == len(set(texts))


@pytest.mark.parametrize("n", SIZES)
def test_every_lookup_answer_appears_in_exactly_one_fact(specs_by_size, n):
    specs, questions = specs_by_size[n]
    lookups = [q for q in questions if not (q["private"] or q["negative"] or q.get("require_all"))]
    assert lookups
    for q in lookups:
        (kw,) = q["keywords"]
        assert len(kw) >= 5, f"keyword too generic: {kw!r}"
        assert _count(kw, specs) == 1, f"{q['id']} {kw!r} appears {_count(kw, specs)} times"
        assert q["gold_facts"][0].lower().count(kw.lower()) == 1
        assert q["gold_facts"][0] in [f["fact"] for f in specs["facts"]]


@pytest.mark.parametrize("n", SIZES)
def test_overview_questions_cover_exactly_one_leaf(specs_by_size, n):
    specs, questions = specs_by_size[n]
    by_path = collections.defaultdict(list)
    for f in specs["facts"]:
        by_path[f["path"]].append(f["fact"])
    seen_paths = set()
    for q in [q for q in questions if q.get("require_all")]:
        path = q["path"]
        assert path not in seen_paths
        seen_paths.add(path)
        assert 2 <= len(q["keywords"]) <= 6
        assert len(q["keywords"]) == len(by_path[path]), "keywords must be the answers of ALL facts in the leaf"
        for kw in q["keywords"]:
            assert _count(kw, specs) == 1
        assert sorted(q["gold_facts"]) == sorted(by_path[path])


@pytest.mark.parametrize("n", SIZES)
def test_private_questions_target_real_private_facts(specs_by_size, n):
    specs, questions = specs_by_size[n]
    private_facts = [f for f in specs["facts"] if f.get("private")]
    privs = [q for q in questions if q["private"]]
    assert len(privs) == 4
    for q in privs:
        (secret,) = q["forbidden"]
        assert not re.search(r"\d{5,}", q["question"]), "secret must not be in the question"
        assert secret not in q["question"]
        holders = [f for f in private_facts if secret in f["fact"]]
        assert len(holders) == 1, "the secret must exist in exactly one private fact"
        assert _count(secret, specs) == 1


@pytest.mark.parametrize("n", SIZES)
def test_unanswerable_questions_mention_nothing_in_the_vault(specs_by_size, n):
    specs, questions = specs_by_size[n]
    text = _all_text(specs)
    spare = [*base.SPARE_CITIES, *base.SPARE_GENRES, *base.SPARE_TASKS, base.SPARE_ACTIVITY, base.SPARE_RELATIVE]
    for w in spare:
        assert w.lower() not in text
    negs = [q for q in questions if q["negative"]]
    assert len(negs) == 6
    for q in negs:
        assert any(w.lower() in q["question"].lower() for w in spare), q["question"]


@pytest.mark.parametrize("n", [1000, 5000])
def test_procedural_tree_respects_branching_cap_and_depth(specs_by_size, n):
    specs, _ = specs_by_size[n]
    children = collections.defaultdict(set)
    per_leaf = collections.Counter()
    for f in specs["facts"]:
        parts = f["path"].split("/")
        per_leaf[f["path"]] += 1
        for i in range(len(parts)):
            children["/".join(parts[:i])].add(parts[i])
    assert max(len(v) for v in children.values()) <= 12
    proc = [p for p in per_leaf if p.split("/")[0] in gen.CATEGORIES]
    assert proc and all(p.count("/") == 3 for p in proc)
    assert max(per_leaf[p] for p in proc) <= gen.LEAF_MAX


def test_determinism_of_specs_and_questions():
    for n in (50, 1000):
        a = gen.build_extended_specs(7, n)
        b = gen.build_extended_specs(7, n)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        assert json.dumps(gen.generate_questions(a, 7)) == json.dumps(gen.generate_questions(b, 7))
    assert json.dumps(gen.build_extended_specs(7, 50), sort_keys=True) != json.dumps(gen.build_extended_specs(8, 50), sort_keys=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("vaults")
    out = {}
    for n in (50, 200):
        out[n] = (root / f"scaled_{n}", gen.generate(n, 7, root / f"scaled_{n}", quiet=True))
    return out


@pytest.mark.parametrize("n", [50, 200])
def test_built_vault_is_healthy_and_private_node_is_private(built, n):
    from treemem.tree_manager import TreeManager

    vault, manifest = built[n]
    mgr = TreeManager(vault)
    assert mgr.health_checker.check_all()["violations"] == []
    assert mgr.store.read_node("finance/accounts").sensitivity == "private"
    assert manifest["fact_count"] == n and manifest["private_facts"] == 4
    assert manifest["topic_count"] >= 9


@pytest.mark.parametrize("n", [50, 200])
def test_private_numbers_only_in_log_and_private_node(built, n):
    vault, _ = built[n]
    questions = json.loads(gen.questions_path(vault).read_text())
    secrets = [s for q in questions if q["private"] for s in q["forbidden"]]
    assert len(secrets) == 4
    for path in vault.rglob("*"):
        if not path.is_file() or path.suffix not in (".md", ".jsonl", ".json"):
            continue
        rel = path.relative_to(vault).as_posix()
        if rel.startswith("log/") or rel == "finance/accounts/summary.md" or rel.startswith(".placements"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for secret in secrets:
            assert secret not in text, f"{secret} leaked into {rel}"


def test_manifest_hashes_match_files_and_change_with_content(built):
    vault, manifest = built[50]
    assert manifest["questions_sha256"] == gen.file_sha256(gen.questions_path(vault))
    assert manifest["log_sha256"] == gen.log_sha256(vault)
    before = gen.file_sha256(gen.questions_path(vault))
    qfile = gen.questions_path(vault)
    original = qfile.read_text()
    try:
        qfile.write_text(original.replace("Which", "Whichever", 1))
        assert gen.file_sha256(qfile) != before
    finally:
        qfile.write_text(original)


def test_generating_twice_gives_identical_hashes(tmp_path):
    a = gen.generate(50, 7, tmp_path / "a" / "scaled_50", quiet=True)
    b = gen.generate(50, 7, tmp_path / "b" / "scaled_50", quiet=True)
    assert a["questions_sha256"] == b["questions_sha256"]
    # log lines carry timestamps; the fact content must still be identical
    la = [l.split("| fact:", 1)[1] for l in (next((tmp_path / "a" / "scaled_50" / "log").glob("*.md"))).read_text().splitlines() if "| fact:" in l]
    lb = [l.split("| fact:", 1)[1] for l in (next((tmp_path / "b" / "scaled_50" / "log").glob("*.md"))).read_text().splitlines() if "| fact:" in l]
    assert la == lb
