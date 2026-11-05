"""Log appends and lookups must not re-parse the whole day file every time (was O(n^2))."""
import threading
from treemem.log_writer import LogWriter


def test_append_and_get_entry_do_not_reparse_whole_file(tmp_path, monkeypatch):
    w = LogWriter(tmp_path)
    calls = {"n": 0}
    real = LogWriter._parse_line

    def counting(self, date_str, line):
        calls["n"] += 1
        return real(self, date_str, line)

    monkeypatch.setattr(LogWriter, "_parse_line", counting)
    ids = [w.append(f"fact number {i}", hint="h") for i in range(300)]
    for eid in ids[::10]:
        assert w.get_entry(eid)["fact"].startswith("fact number")
    # one parse per appended line (cache update) plus a handful; quadratic would be ~45,000
    assert calls["n"] < 1000


def test_cache_sees_appends_from_another_writer(tmp_path):
    a, b = LogWriter(tmp_path), LogWriter(tmp_path)
    first = a.append("from a")
    assert a.get_entry(first)["fact"] == "from a"
    second = b.append("from b")          # other instance/process appends
    assert a.get_entry(second)["fact"] == "from b"
    third = a.append("again a")
    assert third.split("#")[1] == str(int(second.split("#")[1]) + 1)


def test_ids_stay_unique_and_sequential_under_threads(tmp_path):
    w = LogWriter(tmp_path)
    out = []
    def work():
        for i in range(25):
            out.append(w.append(f"x{i}"))
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    nums = sorted(int(e.split("#")[1]) for e in out)
    assert nums == list(range(1, 201))
