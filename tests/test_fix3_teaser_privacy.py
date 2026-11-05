"""Pass 3: private teasers are overwritten server-side and teasers are leak-scanned."""
from treemem.tree_manager import TreeManager, PRIVATE_TEASER


def _vault(tmp_path):
    m = TreeManager(tmp_path / "v")
    r = m.remember("account number 4921 salary details", hint="fin/priv")
    m.place(r["entry_id"], "fin/priv", sensitivity="private")
    r = m.remember("likes tea", hint="fin/misc")
    m.place(r["entry_id"], "fin/misc")
    return m


def test_private_child_teaser_is_overwritten_on_disk(tmp_path):
    m = _vault(tmp_path)
    res = m.commit_summary(
        "fin",
        "Finance.\n\n## Children\n- [[priv]] - account number 4921 salary\n- [[misc]] - misc notes",
    )
    assert res["ok"] is True
    assert res["teasers_overwritten"] == ["priv"]
    teasers = {c["label"]: c["teaser"] for c in m.store.read_node("fin").children}
    assert teasers["priv"] == PRIVATE_TEASER
    assert teasers["misc"] == "misc notes"
    raw = (tmp_path / "v" / "fin" / "summary.md").read_text()
    assert "4921" not in raw


def test_teaser_of_normal_child_cannot_leak_private_descendant(tmp_path):
    m = TreeManager(tmp_path / "v")
    r = m.remember("passport number 8837261", hint="docs/id/pass")
    m.place(r["entry_id"], "docs/id/pass", sensitivity="private")
    r = m.remember("library card", hint="docs/lib")
    m.place(r["entry_id"], "docs/lib")
    res = m.commit_summary(
        "docs",
        "Documents.\n\n## Children\n- [[id]] - passport number 8837261\n- [[lib]] - library card",
    )
    assert res["ok"] is False
    assert "leaks" in res["error"]


def test_descendants_of_private_node_are_checked_even_if_own_flag_is_normal(tmp_path):
    m = TreeManager(tmp_path / "v")
    r = m.remember("secret mortgage amount 450000", hint="fin/home/loan")
    m.place(r["entry_id"], "fin/home/loan")  # own flag normal
    node = m.store.read_node("fin/home")
    node.sensitivity = "private"
    m.store.write_node_atomic("fin/home", node)
    res = m.commit_summary("fin", "Finance mentions mortgage 450000.\n\n## Children\n- [[home]] - x")
    assert res["ok"] is False


def test_year_digit_still_not_a_false_positive(tmp_path):
    m = TreeManager(tmp_path / "v")
    r = m.remember("I have 2 savings accounts", hint="fin/acct")
    m.place(r["entry_id"], "fin/acct", sensitivity="private")
    res = m.commit_summary("fin", "Financial topics, updated in 2026.\n\n## Children\n- [[acct]] - x")
    assert res["ok"] is True


def test_private_node_summary_may_not_quote_its_private_children(tmp_path):
    m = TreeManager(tmp_path / "v")
    r = m.remember("loan balance 450000", hint="priv/loan")
    m.place(r["entry_id"], "priv/loan", sensitivity="private")
    node = m.store.read_node("priv")
    node.sensitivity = "private"
    m.store.write_node_atomic("priv", node)
    res = m.commit_summary("priv", "Loan balance 450000 tracked here.\n\n## Children\n- [[loan]] - x")
    assert res["ok"] is False
    ok = m.commit_summary("priv", "Loans and related paperwork.\n\n## Children\n- [[loan]] - x")
    assert ok["ok"] is True


def test_parent_summary_may_name_a_private_child(tmp_path):
    """Labels are public by design: a parent must be able to say 'accounts' about child 'accounts'."""
    m = TreeManager(tmp_path / "v")
    r = m.remember("Harborline Bank account number is 8578933331.", hint="finance/accounts", sensitivity="private")
    m.place(r["entry_id"], "finance/accounts", sensitivity="private")
    ok = m.commit_summary("finance", "finance. Subtopics: accounts.\n\n## Children\n- [[accounts]] - x")
    assert ok["ok"] is True
    bad = m.commit_summary("finance", "Bank account 8578933331 lives here.\n\n## Children\n- [[accounts]] - x")
    assert bad["ok"] is False
