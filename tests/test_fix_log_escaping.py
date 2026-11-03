"""WP1: log truncation on '|', escaping, line numbers, concurrent IDs."""

import concurrent.futures
import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.log_writer import LogWriter
from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_wp1_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_remember_roundtrip_pipe_and_hint_literal(vault):
    mgr = TreeManager(vault)
    fact = "Server password | hint: x"
    rem = mgr.remember(fact)
    entry = mgr.log_writer.get_entry(rem["entry_id"])
    assert entry is not None
    assert entry["fact"] == fact
    assert "hint: x" in entry["fact"]
    assert entry["hint"] == ""


def test_roundtrip_backslash_windows_path_unicode_trailing_spaces(vault):
    lw = LogWriter(vault)
    cases = [
        ("plain pipe | in middle", "a | hint: nested", "sess|ion"),
        ("backslash only \\ here", "", "default"),
        ("C:\\new", "win\\path", "s"),
        ("café 密码 ☃", "hint-ü", "sesión"),
        ("trailing spaces   ", "hint trail  ", "sess"),
        ("mix \\ and | and \\\\|", "h|h", "s\\s"),
    ]
    for fact, hint, session in cases:
        eid = lw.append(fact, hint=hint, session=session)
        got = lw.get_entry(eid)
        assert got is not None, fact
        assert got["fact"] == fact, (fact, got["fact"])
        assert got["hint"] == hint, (hint, got["hint"])
        assert got["session"] == session, (session, got["session"])


def test_linebreaks_become_single_space(vault):
    lw = LogWriter(vault)
    fact = "line1\nline2\rline3\u2028line4\u2029line5\x0bline6\x0cline7\x85line8"
    eid = lw.append(fact)
    got = lw.get_entry(eid)
    assert got["fact"] == "line1 line2 line3 line4 line5 line6 line7 line8"
    raw = (vault / "log" / f"{got['date']}.md").read_text(encoding="utf-8")
    assert "\n- " in ("\n" + raw) or raw.startswith("- ")
    # stored fact portion has no raw line breaks besides the record terminator
    body_lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(body_lines) == 1


def test_parse_handwritten_legacy_log_line(vault):
    lw = LogWriter(vault)
    log_dir = vault / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    date_str = "2024-01-15"
    legacy = (
        "- 1 | 12:00:00Z | session=default | fact: Server password | hint: x\n"
        "- 2 | 12:01:00Z | session=cli | fact: no pipes here\n"
    )
    (log_dir / f"{date_str}.md").write_text(legacy, encoding="utf-8")

    e1 = lw.get_entry(f"{date_str}#1")
    assert e1["fact"] == "Server password"
    assert e1["hint"] == "x"
    assert e1["session"] == "default"

    e2 = lw.get_entry(f"{date_str}#2")
    assert e2["fact"] == "no pipes here"
    assert e2["hint"] == ""
    assert e2["session"] == "cli"


def test_next_id_is_highest_parsed_line_plus_one(vault):
    lw = LogWriter(vault)
    log_dir = vault / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Gaps + a junk line: next id must be 5, not len(lines)+1
    (log_dir / f"{date_str}.md").write_text(
        "- 1 | 00:00:00Z | session=default | fact: a\n"
        "not-a-log-line\n"
        "- 4 | 00:00:01Z | session=default | fact: b\n",
        encoding="utf-8",
    )
    eid = lw.append("c")
    assert eid == f"{date_str}#5"
    got = lw.get_entry(eid)
    assert got["fact"] == "c"
    assert got["line"] == 5


def test_concurrent_appends_unique_sequential_ids(vault):
    lw = LogWriter(vault)
    n = 8

    def worker(i):
        return lw.append(f"fact-{i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        eids = list(ex.map(worker, range(n)))

    assert len(eids) == n
    assert len(set(eids)) == n
    lines = sorted(int(e.split("#", 1)[1]) for e in eids)
    assert lines == list(range(1, n + 1))
