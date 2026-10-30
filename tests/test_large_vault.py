"""The mid-size vault generator and the offline large-vault benchmark (no API calls)."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


midsize = _load("midsize_under_test", "bench/make_midsize_vault.py")
offline = _load("large_vault_under_test", "bench/large_vault_offline.py")


def test_specs_are_deterministic_and_unique():
    first = midsize.build_specs(7)
    second = midsize.build_specs(7)
    assert first["facts"] == second["facts"]
    assert len(first["facts"]) >= 300
    # every answer value must be unique so ground truth is unambiguous
    answers = [c["answer"] for c in first["candidates"]]
    assert len(answers) == len(set(answers))
    texts = [f["fact"] for f in first["facts"]]
    assert len(texts) == len(set(texts))


def test_questions_cover_all_kinds():
    specs = midsize.build_specs(7)
    questions = midsize.build_questions(specs, 7)
    kinds = {"lookup": 0, "overview": 0, "private": 0, "negative": 0}
    for q in questions:
        if q.get("private"):
            kinds["private"] += 1
        elif q.get("negative"):
            kinds["negative"] += 1
        elif q.get("require_all"):
            kinds["overview"] += 1
        else:
            kinds["lookup"] += 1
    assert kinds["lookup"] >= 25
    assert kinds["overview"] >= 6
    assert kinds["private"] >= 2
    assert kinds["negative"] >= 5
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))


def test_negative_questions_ask_about_values_not_in_facts():
    specs = midsize.build_specs(7)
    all_fact_text = " ".join(f["fact"] for f in specs["facts"]).lower()
    for spare in midsize.SPARE_CITIES + midsize.SPARE_GENRES + midsize.SPARE_TASKS + [midsize.SPARE_ACTIVITY, midsize.SPARE_RELATIVE]:
        assert spare.lower() not in all_fact_text


@pytest.fixture(scope="module")
def built_rich(tmp_path_factory):
    return midsize.build_vault(tmp_path_factory.mktemp("rich") / "vault", 7, "rich")


def test_vault_respects_branching_cap_and_has_many_topics(built_rich):
    manager = built_rich["manager"]
    top = manager.store.list_child_dirs("")
    assert len(top) >= 8
    for topic in top:
        children = manager.store.list_child_dirs(topic)
        assert len(children) <= 12
    assert manager.get_dirty_nodes() == []  # every parent summary was committed


def test_private_leaf_is_private(built_rich):
    node = built_rich["manager"].store.read_node("finance/accounts")
    assert node.sensitivity == "private"


@pytest.fixture(scope="module")
def results():
    return offline.run(7)


def test_no_private_leaks_anywhere(results):
    for vault in results["vaults"]:
        assert vault["private_leaks_tree"] == 0
        assert vault["private_leaks_bm25"] == 0


def test_rich_teasers_do_not_hurt_and_help_lookups(results):
    minimal = [v for v in results["vaults"] if "minimal" in v["label"]][0]
    rich = [v for v in results["vaults"] if "rich" in v["label"]][0]
    assert rich["tree_lookup_answerable"] >= minimal["tree_lookup_answerable"]
    assert len(rich["tree_premature_stops"]) <= len(minimal["tree_premature_stops"])


def test_tree_beats_flat_on_size_and_bm25_on_overviews(results):
    rich = [v for v in results["vaults"] if "rich" in v["label"]][0]
    assert rich["tree_mean_tokens"] * 10 < rich["flat_log_tokens"]
    assert rich["tree_overview_complete"] >= rich["bm25_overview_complete"]


def test_json_result_is_serializable(results):
    json.dumps(results)
