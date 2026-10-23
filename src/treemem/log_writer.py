"""Append-only daily log writer and parser with concurrent-safe locking."""

import fcntl
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOG_LOCK = threading.Lock()


class LogWriter:
    """Manages the append-only ground truth log at <root>/log/YYYY-MM-DD.md."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self.log_dir = self.root_dir / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.log_dir.chmod(0o700)
        except Exception:
            pass

    def append(self, fact: str, hint: str = "", session: str = "") -> str:
        """Append a fact to today's log file atomically and return entry_id (date#line)."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%SZ")

        log_file = self.log_dir / f"{date_str}.md"
        lock_file = self.log_dir / f"{date_str}.lock"

        fact_clean = fact.replace("\n", " ").strip()
        hint_clean = hint.strip()
        session_clean = session.strip() or "default"

        with _LOG_LOCK:
            with open(lock_file, "w") as lock_f:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                try:
                    # Count existing non-empty lines to get 1-indexed line number
                    line_num = 1
                    if log_file.exists():
                        with open(log_file, "r", encoding="utf-8") as f:
                            lines = [l for l in f if l.strip()]
                            line_num = len(lines) + 1

                    if hint_clean:
                        entry_line = f"- {line_num} | {time_str} | session={session_clean} | fact: {fact_clean} | hint: {hint_clean}\n"
                    else:
                        entry_line = f"- {line_num} | {time_str} | session={session_clean} | fact: {fact_clean}\n"

                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(entry_line)
                        f.flush()
                        os.fsync(f.fileno())

                    return f"{date_str}#{line_num}"
                finally:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

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
        line = line.strip()
        if not line.startswith("-"):
            return None

        content = line[1:].strip()
        parts = [p.strip() for p in content.split("|")]
        if len(parts) < 3:
            return None

        try:
            line_num = int(parts[0])
        except ValueError:
            return None

        time_str = parts[1]
        session = ""
        fact = ""
        hint = ""

        for p in parts[2:]:
            if p.startswith("session="):
                session = p.split("=", 1)[1].strip()
            elif p.startswith("fact:"):
                fact = p.split(":", 1)[1].strip()
            elif p.startswith("hint:"):
                hint = p.split(":", 1)[1].strip()

        if not fact and len(parts) >= 4:
            fact = parts[3]

        return {
            "entry_id": f"{date_str}#{line_num}",
            "date": date_str,
            "line": line_num,
            "time": time_str,
            "session": session,
            "fact": fact,
            "hint": hint,
            "raw": line,
        }
