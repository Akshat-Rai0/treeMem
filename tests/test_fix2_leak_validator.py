"""WP-A: Fix leak validator false positives using whole-word tokenization."""

import re
import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wpa_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_single_digit_in_private_fact_does_not_block_summary_with_year(vault):
    """Summary 'updated in 2026' should be accepted when private fact contains '2'."""
    mgr = TreeManager(vault)
    # Create a private node with a fact containing single digit
    entry = mgr.remember("I have 2 savings accounts", hint="private/finance", sensitivity="private")
    mgr.place(entry["entry_id"], "private/finance")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()

    # This summary should be accepted - "2" is a single digit, not 3+ digits
    summary_text = """---
name: private
dirty: false
---
Financial topics, updated in 2026

## Children
- [[finance]] - Finance details
"""
    result = mgr.commit_summary("private", summary_text)
    assert result["ok"], f"Should accept summary with year, got error: {result.get('error')}"


def test_whole_word_4921_in_summary_blocked_when_in_private_fact(vault):
    """Summary containing the whole word '4921' should be rejected when private fact contains it."""
    mgr = TreeManager(vault)
    entry = mgr.remember("Account number is 4921", hint="private/bank", sensitivity="private")
    mgr.place(entry["entry_id"], "private/bank")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()

    # This should be rejected - "4921" is a 4-digit number in the private fact
    summary_text = """---
name: private
dirty: false
---
The account number is 4921

## Children
- [[bank]] - Bank details
"""
    result = mgr.commit_summary("private", summary_text)
    assert not result["ok"]
    assert "4921" in result.get("error", "")


def test_accountability_accepted_when_private_fact_contains_account(vault):
    """Summary containing 'accountability' should be accepted when private fact contains 'account'."""
    mgr = TreeManager(vault)
    entry = mgr.remember("My account is private", hint="private/info", sensitivity="private")
    mgr.place(entry["entry_id"], "private/info")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()

    # This should be accepted - no whole-word match for "accountability" vs "account"
    summary_text = """---
name: private
dirty: false
---
Focus on accountability and transparency

## Children
- [[info]] - Information
"""
    result = mgr.commit_summary("private", summary_text)
    assert result["ok"], f"Should accept 'accountability' when private fact has 'account', got error: {result.get('error')}"


def test_exact_private_fact_sentence_rejected(vault):
    """Summary that copies a private fact sentence should be rejected."""
    mgr = TreeManager(vault)
    entry = mgr.remember("This is a secret password for access", hint="private/auth", sensitivity="private")
    mgr.place(entry["entry_id"], "private/auth")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()

    # This should be rejected - exact sentence from private fact
    summary_text = """---
name: private
dirty: false
---
This is a secret password for access

## Children
- [[auth]] - Authentication
"""
    result = mgr.commit_summary("private", summary_text)
    assert not result["ok"]
    assert "leaks" in result.get("error", "").lower()


def test_hindi_text_tokenized_without_crashing(vault):
    """Hindi text should be tokenized without crashing."""
    mgr = TreeManager(vault)
    entry = mgr.remember("मेरा गोपनीय डेटा", hint="private/hindi", sensitivity="private")
    mgr.place(entry["entry_id"], "private/hindi")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()

    # Should not crash when processing Hindi text
    summary_text = """---
name: private
dirty: false
---
यह एक सारांश है

## Children
- [[hindi]] - Hindi data
"""
    result = mgr.commit_summary("private", summary_text)
    # May or may not pass depending on content, but should not crash
    assert result is not None


def test_stop_words_still_respected(vault):
    """Stop words should still be respected in the overlap check."""
    mgr = TreeManager(vault)
    # Create a private node with multiple words
    entry = mgr.remember("secret confidential important data", hint="private/test", sensitivity="private")
    mgr.place(entry["entry_id"], "private/test")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    mgr.rebuild_index()

    # Summary with only stop words should be accepted
    summary_text1 = """---
name: private
dirty: false
---
Child details and view information

## Children
- [[test]] - Test data
"""
    result = mgr.commit_summary("private", summary_text1)
    assert result["ok"], f"Should accept summary with only stop words, got error: {result.get('error')}"

    # Summary with 3+ non-stop words should be rejected
    summary_text2 = """---
name: private
dirty: false
---
Secret confidential important summary

## Children
- [[test]] - Test data
"""
    result2 = mgr.commit_summary("private", summary_text2)
    assert not result2["ok"]
