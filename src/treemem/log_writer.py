"""Append-only daily log writer and parser with concurrent-safe locking."""

try:
    import fcntl
except ImportError:  # pragma: no cover - platform guard
    fcntl = None
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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

                    return f"{date_str}#{line_num}"
                finally:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

    def _next_line_number(self, log_file: Path, date_str: str) -> int:
        """Highest parsed line number in today's file + 1 (not a count of lines)."""
        max_num = 0
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    parsed = self._parse_line(date_str, raw_line)
                    if parsed:
                        max_num = max(max_num, parsed["line"])
        return max_num + 1

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

        with open(log_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                parsed = self._parse_line(date_str, raw_line)
                if parsed and parsed.get("line") == target_line:
                    return parsed
        return None

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
