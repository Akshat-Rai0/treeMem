"""Pass 3: get_events reads only the newest files needed."""
import builtins
import json
from pathlib import Path
from treemem.events import EventBus


def _make(tmp_path, days=30, per_day=5):
    ev = tmp_path / ".events"
    ev.mkdir()
    for day in range(1, days + 1):
        (ev / f"2026-10-{day:02d}.jsonl").write_text(
            "".join(json.dumps({"ts": f"2026-10-{day:02d}T00:00:{i:02d}", "type": "recall", "n": i}) + "\n"
                    for i in range(per_day)))
    return EventBus(tmp_path)


def test_limit_reads_only_newest_files(tmp_path, monkeypatch):
    bus = _make(tmp_path)
    opened = []
    real_open = builtins.open
    def spy(file, *a, **k):
        if str(file).endswith(".jsonl") and "r" in (a[0] if a else k.get("mode", "r")):
            opened.append(Path(file).name)
        return real_open(file, *a, **k)
    monkeypatch.setattr(builtins, "open", spy)
    events = bus.get_events(limit=10)
    assert len(events) == 10
    assert len(opened) <= 3
    assert events[0]["ts"] < events[-1]["ts"]          # oldest -> newest preserved
    assert events[-1]["ts"].startswith("2026-10-30")


def test_since_skips_older_files_and_filters_lines(tmp_path):
    bus = _make(tmp_path)
    events = bus.get_events(since="2026-10-29T00:00:02", limit=100)
    assert [e["ts"] for e in events][0] == "2026-10-29T00:00:03"
    assert len(events) == 7


def test_limit_zero_returns_everything_in_order(tmp_path):
    bus = _make(tmp_path, days=3)
    events = bus.get_events(limit=0)
    assert len(events) == 15
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
