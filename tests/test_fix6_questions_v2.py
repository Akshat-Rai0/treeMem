"""Tests for v2 questions (composite questions replacing overviews)."""

import collections
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "src"))

gen = importlib.import_module("make_scaled_vault")


@pytest.fixture(scope="module")
def questions_by_size():
    out = {}
    for n in (50, 200, 1000, 5000):
        specs = gen.build_extended_specs(7, n)
        v1_q = gen.generate_questions(specs, 7)
        v2_q = gen.generate_questions_v2(specs, 7, v1_q)
        out[n] = (specs, v1_q, v2_q)
    return out


@pytest.mark.parametrize("n", [50, 200, 1000, 5000])
def test_non_composite_items_equal_v1_items_exactly(questions_by_size, n):
    specs, v1_q, v2_q = questions_by_size[n]
    v1_non_overview = [q for q in v1_q if not q.get("require_all")]
    v2_non_composite = [q for q in v2_q if not q.get("composite")]
    assert len(v1_non_overview) == 40
    assert len(v2_non_composite) == 40
    assert v1_non_overview == v2_non_composite


@pytest.mark.parametrize("n", [50, 200, 1000, 5000])
def test_ten_composites_and_unique_ids(questions_by_size, n):
    specs, v1_q, v2_q = questions_by_size[n]
    composites = [q for q in v2_q if q.get("composite")]
    assert len(composites) == 10
    expected_ids = [f"q_composite_{i:02d}" for i in range(10)]
    assert [q["id"] for q in composites] == expected_ids
    assert len({q["id"] for q in v2_q}) == 50


@pytest.mark.parametrize("n", [50, 200, 1000, 5000])
def test_every_keyword_appears_in_exactly_one_fact(questions_by_size, n):
    specs, v1_q, v2_q = questions_by_size[n]
    corpus = [f["fact"].lower() for f in specs["facts"]]
    composites = [q for q in v2_q if q.get("composite")]
    for q in composites:
        assert len(q["keywords"]) == 3
        for kw in q["keywords"]:
            assert len(kw) >= 5
            count = sum(1 for t in corpus if kw.lower() in t)
            assert count == 1, f"Keyword {kw!r} appears {count} times in size {n} vault"


@pytest.mark.parametrize("n", [50, 200, 1000, 5000])
def test_keywords_of_one_composite_are_distinct(questions_by_size, n):
    specs, v1_q, v2_q = questions_by_size[n]
    composites = [q for q in v2_q if q.get("composite")]
    for q in composites:
        assert len(set(q["keywords"])) == 3


@pytest.mark.parametrize("n", [200, 1000, 5000])
def test_no_composite_gold_fact_is_v1_lookup_gold_fact(questions_by_size, n):
    specs, v1_q, v2_q = questions_by_size[n]
    v1_lookup_gold = {
        gf for q in v1_q
        if not (q["private"] or q["negative"] or q.get("require_all"))
        for gf in q.get("gold_facts", [])
    }
    composites = [q for q in v2_q if q.get("composite")]
    for q in composites:
        for gf in q.get("gold_facts", []):
            assert gf not in v1_lookup_gold, f"Composite gold fact {gf!r} was in v1 lookup gold"


@pytest.mark.parametrize("n", [50, 200, 1000, 5000])
def test_composite_text_contains_no_path_labels(questions_by_size, n):
    specs, v1_q, v2_q = questions_by_size[n]
    composites = [q for q in v2_q if q.get("composite")]
    for q in composites:
        text = q["question"]
        assert ">" not in text
        assert "tier_" not in text
        for seg in q["path"].split("/")[1:-1]:
            assert seg not in text, f"Internal segment {seg!r} in question text {text!r}"


def test_determinism_same_seed_gives_byte_identical_output():
    for n in (50, 200):
        specs_a = gen.build_extended_specs(7, n)
        specs_b = gen.build_extended_specs(7, n)
        v1_a = gen.generate_questions(specs_a, 7)
        v1_b = gen.generate_questions(specs_b, 7)
        v2_a = gen.generate_questions_v2(specs_a, 7, v1_a)
        v2_b = gen.generate_questions_v2(specs_b, 7, v1_b)
        assert json.dumps(v2_a, indent=2) == json.dumps(v2_b, indent=2)


def test_v1_files_untouched_by_new_code_path(tmp_path):
    vault_dir = tmp_path / "scaled_50"
    manifest_v1 = gen.generate(50, 7, vault_dir, quiet=True, questions_v2=False)
    qfile_v1 = gen.questions_path(vault_dir)
    mfile_v1 = gen.manifest_path(vault_dir)

    q_content_v1 = qfile_v1.read_bytes()
    m_content_v1 = mfile_v1.read_bytes()

    # Now generate with questions_v2 enabled in a fresh vault
    vault_dir_v2 = tmp_path / "scaled_50_v2"
    manifest_v2 = gen.generate(50, 7, vault_dir_v2, quiet=True, questions_v2=True)
    qfile_v1_in_v2 = gen.questions_path(vault_dir_v2)
    mfile_v1_in_v2 = gen.manifest_path(vault_dir_v2)

    # v1 questions file and manifest file must have identical sha256
    assert gen.file_sha256(qfile_v1) == gen.file_sha256(qfile_v1_in_v2)
    assert manifest_v1["questions_sha256"] == manifest_v2["questions_sha256"]

    # And v2 files must exist and be recorded in manifest_v2
    qfile_v2 = gen.questions_v2_path(vault_dir_v2)
    mfile_v2 = gen.manifest_v2_path(vault_dir_v2)
    assert qfile_v2.exists()
    assert mfile_v2.exists()
    m2_data = json.loads(mfile_v2.read_text(encoding="utf-8"))
    assert m2_data["questions_v2_sha256"] == gen.file_sha256(qfile_v2)
