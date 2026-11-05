"""Append-only daily log writer and parser with concurrent-safe locking."""

try:
    import fcntl
except ImportError:  # pragma: no cover - platform guard
    fcntl = None
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Any, Dict, List, Optional

_LOG_LOCK = threading.Lock()

# Line-break characters flattened to a single space so each record stays one line.
_LINEBREAKS = dict.fromkeys(map(ord, "\r\n\u2028\u2029\x0b\x0c\x85"), " ")


def _flatten_linebreaks(text: str) -> str:
    return (text or "").translate(_LINEBREAKS)


def _escape_field(text: str) -> str:
    """Escape backslash and pipe so records can contain those characters."""
    return _flatten_linebreaks(text).replace("\\", "\\\\").replace("|", "\\|")


def _unescape_field(text: str) -> str:
    """Undo only \\\\ and \\|; other backslashes are left intact."""
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n and text[i + 1] in "\\|":
            out.append(text[i + 1])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _split_unescaped_pipes(text: str) -> List[str]:
    """Split on '|' that are not escaped by a preceding backslash."""
    parts: List[str] = []
    buf: List[str] = []
    escaped = False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            buf.append(ch)
            escaped = True
            continue
        if ch == "|":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def _field_value(part: str, prefix: str) -> str:
    """Value after prefix; keep trailing spaces; drop one conventional space after prefix."""
    idx = part.find(prefix)
    if idx < 0:
        return ""
    value = part[idx + len(prefix) :]
    if value.startswith(" "):
        value = value[1:]
    return _unescape_field(value)


class LogWriter:
    """Manages the append-only ground truth log at <root>/log/YYYY-MM-DD.md."""

    def __init__(self, root_dir: Path):
        if fcntl is None:
            raise RuntimeError("TreeMem currently supports macOS and Linux only")
        self.root_dir = Path(root_dir)
        self.log_dir = self.root_dir / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.log_dir.chmod(0o700)
        except Exception:
            pass
        # Per-day-file cache: date -> ((size, mtime_ns), {line: entry}, max_line).
        # Validated by stat on every use, so appends from other processes are picked up.
        self._file_cache: Dict[str, Tuple[Tuple[int, int], Dict[int, Dict[str, Any]], int]] = {}
        self._cache_lock = threading.Lock()

    def _stat_key(self, log_file: Path) -> Optional[Tuple[int, int]]:
        try:
            st = log_file.stat()
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _load_file(self, log_file: Path, date_str: str) -> Tuple[Dict[int, Dict[str, Any]], int]:
        """Entries of one daily file keyed by line number (first occurrence wins), plus max line.

        Re-parses only when the file changed since the last call; appending N facts is O(N), not O(N^2).
        """
        key = self._stat_key(log_file)
        if key is None:
            return {}, 0
        with self._cache_lock:
            cached = self._file_cache.get(date_str)
            if cached is not None and cached[0] == key:
                return cached[1], cached[2]
        entries: Dict[int, Dict[str, Any]] = {}
        max_line = 0
        with open(log_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                parsed = self._parse_line(date_str, raw_line)
                if parsed:
                    entries.setdefault(parsed["line"], parsed)
                    max_line = max(max_line, parsed["line"])
        with self._cache_lock:
            self._file_cache[date_str] = (key, entries, max_line)
        return entries, max_line

    def append(self, fact: str, hint: str = "", session: str = "", sensitivity: str = "normal") -> str:
        """Append a fact to today's log file atomically and return entry_id (date#line)."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%SZ")

        log_file = self.log_dir / f"{date_str}.md"
        lock_file = self.log_dir / f"{date_str}.lock"

        fact_esc = _escape_field(fact)
        hint_esc = _escape_field(hint)
        session_esc = _escape_field(session) or "default"
        sens = (sensitivity or "normal").strip().lower()

        with _LOG_LOCK:
            with open(lock_file, "w") as lock_f:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                try:
                    line_num = self._next_line_number(log_file, date_str)

                    entry_line = (
                        f"- {line_num} | {time_str} | session={session_esc} | fact: {fact_esc}"
                    )
                    if hint_esc:
                        entry_line += f" | hint: {hint_esc}"
                    if sens == "private":
                        entry_line += " | sens: private"
                    entry_line += "\n"

                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(entry_line)
                        f.flush()
                        os.fsync(f.fileno())

                    self._remember_appended(log_file, date_str, entry_line)
                    return f"{date_str}#{line_num}"
                finally:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

    def _remember_appended(self, log_file: Path, date_str: str, entry_line: str) -> None:
        """Keep the cache current after our own append without re-reading the file."""
        parsed = self._parse_line(date_str, entry_line)
        key = self._stat_key(log_file)
        with self._cache_lock:
            cached = self._file_cache.get(date_str)
            if parsed is None or key is None or cached is None:
                self._file_cache.pop(date_str, None)
                return
            old_key, entries, max_line = cached
            # Only extend if nobody else wrote since we cached (size grew by exactly our line).
            if key[0] != old_key[0] + len(entry_line.encode("utf-8")):
                self._file_cache.pop(date_str, None)
                return
            entries.setdefault(parsed["line"], parsed)
            self._file_cache[date_str] = (key, entries, max(max_line, parsed["line"]))

    def _next_line_number(self, log_file: Path, date_str: str) -> int:
        """Highest parsed line number in today's file + 1 (not a count of lines)."""
        _, max_line = self._load_file(log_file, date_str)
        return max_line + 1

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific log entry by date#line."""
        if "#" not in entry_id:
            return None
        date_str, line_str = entry_id.split("#", 1)
        try:
            target_line = int(line_str)
        except ValueError:
            return None

        log_file = self.log_dir / f"{date_str}.md"
        if not log_file.exists():
            return None

        entries, _ = self._load_file(log_file, date_str)
        return entries.get(target_line)

    def read_all_entries(self) -> List[Dict[str, Any]]:
        """Return all log entries across all daily log files in chronological order."""
        if not self.log_dir.exists():
            return []

        entries: List[Dict[str, Any]] = []
        for log_file in sorted(self.log_dir.glob("*.md")):
            date_str = log_file.stem
            with open(log_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    parsed = self._parse_line(date_str, raw_line)
                    if parsed:
                        entries.append(parsed)
        return entries

    def _parse_line(self, date_str: str, line: str) -> Optional[Dict[str, Any]]:
        line = line.rstrip("\n\r")
        if not line.lstrip().startswith("-"):
            return None

        content = line.lstrip()[1:]
        if content.startswith(" "):
            content = content[1:]
        parts = _split_unescaped_pipes(content)
        if len(parts) < 3:
            return None

        # Format uses " | " around delimiters; drop that one padding space on
        # non-final fields so real trailing spaces in fact/hint still round-trip.
        trimmed: List[str] = []
        last = len(parts) - 1
        for i, p in enumerate(parts):
            if i < last and p.endswith(" "):
                trimmed.append(p[:-1])
            else:
                trimmed.append(p)
        parts = trimmed

        try:
            line_num = int(parts[0].strip())
        except ValueError:
            return None

        time_str = parts[1].strip()
        session = ""
        fact = ""
        hint = ""
        sensitivity = "normal"

        for p in parts[2:]:
            s = p.strip()
            if s.startswith("session="):
                session = _unescape_field(s.split("=", 1)[1])
            elif s.startswith("fact:"):
                fact = _field_value(p, "fact:")
            elif s.startswith("hint:"):
                hint = _field_value(p, "hint:")
            elif s.startswith("sens:"):
                sensitivity = _field_value(p, "sens:").strip() or "normal"

        if not fact and len(parts) >= 4:
            fact = _unescape_field(parts[3].strip())

        return {
            "entry_id": f"{date_str}#{line_num}",
            "date": date_str,
            "line": line_num,
            "time": time_str,
            "session": session,
            "fact": fact,
            "hint": hint,
            "sensitivity": sensitivity,
            "raw": line.strip() if not line[:1].isspace() else line.lstrip(),
        }
