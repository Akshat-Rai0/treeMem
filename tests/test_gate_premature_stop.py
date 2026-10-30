"""Regression tests for the premature-stop fix in the descent gate."""

import importlib.util
from pathlib import Path

from treemem.descent_gate import DescentGate, stem

ROOT = Path(__file__).resolve().parent.parent

# A made-up vault, deliberately unrelated to examples/sample_memory.
ROOT_SUMMARY = "Personal memory vault for Sam Ortiz, 30-year-old designer in Oslo."
ROOT_CHILDREN = [
    {"label": "identity", "teaser": "Personal bio and contact"},
    {"label": "projects", "teaser": "Technical projects and code"},
    {"label": "hobbies", "teaser": "Fitness and travel"},
]


def test_stem_is_light_and_generic():
    assert stem("projects") == "project"
    assert stem("languages") == "language"
    assert stem("classes") == "class"
    assert stem("building") == "build"
    assert stem("glass") == "glass"
    assert stem("is") == "is"


# The real root of examples/sample_memory, where the failure was observed with gpt-oss-120b.
SAMPLE_ROOT_SUMMARY = "Personal memory vault for Alex Mercer, 28-year-old software engineer in Metropolis."
SAMPLE_ROOT_CHILDREN = [
    {"label": "identity", "teaser": "Personal bio and contact"},
    {"label": "education", "teaser": "University and coursework"},
    {"label": "career", "teaser": "Work history and achievements"},
    {"label": "projects", "teaser": "Technical projects and code"},
    {"label": "preferences", "teaser": "Engineering, reading, and music preferences"},
    {"label": "hobbies", "teaser": "Fitness and travel"},
    {"label": "finance", "teaser": "Financial records"},
]


def test_root_summary_that_only_shares_words_does_not_stop():
    """The q09 failure: the root says 'memory' but the question needs a named project."""
    question = "What hierarchical memory project is the user building?"
    legacy = DescentGate.legacy().evaluate(question, "/", SAMPLE_ROOT_SUMMARY, SAMPLE_ROOT_CHILDREN)
    current = DescentGate().evaluate(question, "/", SAMPLE_ROOT_SUMMARY, SAMPLE_ROOT_CHILDREN)
    assert legacy["action"] == "stop"  # documents the old failure
    assert current["action"] == "descend"
    assert current["suggested_child"] == "projects"


def test_unrelated_vault_descends_to_projects_too():
    question = "What hierarchical memory project is the user building?"
    result = DescentGate().evaluate(question, "/", ROOT_SUMMARY, ROOT_CHILDREN)
    assert result["action"] == "descend"
    assert result["suggested_child"] == "projects"


def test_root_summary_that_really_answers_still_stops():
    current = DescentGate().evaluate("How old is Sam Ortiz?", "/", "Sam Ortiz, 30 years old, designer in Oslo.", ROOT_CHILDREN)
    assert current["action"] == "stop"


def test_synonym_match_alone_can_still_stop():
    summary = "Sam Ortiz is a 30-year-old Software Engineer living in Oslo."
    current = DescentGate().evaluate("What is the user's profession?", "/", summary, ROOT_CHILDREN)
    assert current["action"] == "stop"


def test_close_child_rule_only_applies_in_eager_mode():
    summary = "University education, degree history, and completed coursework."
    children = [{"label": "degree", "teaser": "Degree specifics"}, {"label": "coursework", "teaser": "Core classes taken"}]
    question = "What degree does he hold?"
    manual = DescentGate().evaluate(question, "education", summary, children)
    eager = DescentGate().evaluate(question, "education", summary, children, eager_descent=True)
    eager_off = DescentGate(descend_ratio=0.0).evaluate(question, "education", summary, children, eager_descent=True)
    assert manual["action"] == "stop"  # manual descent: an extra step costs the agent a tool call
    assert eager["action"] == "descend" and eager["suggested_child"] == "degree"
    assert eager_off["action"] == "stop"


def test_scores_include_coverage():
    result = DescentGate().evaluate("What project is he building?", "/", ROOT_SUMMARY, ROOT_CHILDREN)
    assert "parent_coverage" in result


def _load_offline():
    spec = importlib.util.spec_from_file_location("gate_offline_under_test", ROOT / "bench" / "gate_offline_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_gate_check_guards():
    offline = _load_offline()
    vault = ROOT / "examples" / "sample_memory"
    results = {}
    for set_name in ("dev", "heldout"):
        questions, grade_answer = offline.load_questions(set_name)
        for label, gate in (("legacy", DescentGate.legacy()), ("current", DescentGate())):
            results[(set_name, label)] = offline.evaluate_gate(gate, questions, grade_answer, vault)["summary"]

    for set_name in ("dev", "heldout"):
        legacy = results[(set_name, "legacy")]
        current = results[(set_name, "current")]
        assert current["private_leaks"] == 0
        assert len(current["premature_stops"]) <= len(legacy["premature_stops"])
        assert current["answerable_from_first_call"] >= legacy["answerable_from_first_call"]

    assert "q09_project" not in results[("dev", "current")]["premature_stops"]
    assert "q09_project" in results[("dev", "legacy")]["premature_stops"]
