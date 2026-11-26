"Tests for placement journal checksums and durability helpers."""
import json
from pathlib import Path

import pytest

from treemem.tree_manager import TreeManager


def test_placement_journal_has_checksum(tmp_path):
    mgr = TreeManager(tmp_path)
    rem = mgr.remember("checksum fact", hint="durability/node")
    mgr.place(rem["entry_id"], "durability/node")
    journal = tmp_path / ".placements.jsonl"
    lines = [json.loads(l) for l in journal.read_text().splitlines() if l.strip()]
    assert lines and all("sha256" in r for r in lines)
    assert not [k for k in mgr._placement_records() if k.startswith("__error__")]


def test_placement_journal_checksum_detects_tamper(tmp_path):
    mgr = TreeManager(tmp_path)
    rem = mgr.remember("tamper fact", hint="durability/node")
    mgr.place(rem["entry_id"], "durability/node")
    journal = tmp_path / ".placements.jsonl"
    rows = [json.loads(l) for l in journal.read_text().splitlines() if l.strip()]
    rows[-1]["path"] = "durability/other"
    journal.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    records = mgr._placement_records()
    assert any(k.startswith("__error__") for k in records)
    assert any("checksum" in v.get("error", "") for v in records.values())


def test_placement_journal_malformed_line_is_error(tmp_path):
    mgr = TreeManager(tmp_path)
    rem = mgr.remember("malformed fact", hint="durability/node")
    mgr.place(rem["entry_id"], "durability/node")
    journal = tmp_path / ".placements.jsonl"
    with journal.open("a") as f:
        f.write("{not json\n")
    records = mgr._placement_records()
    assert any(k.startswith("__error__") for k in records)
