"""Event bus and persistent event logger for TreeMem."""

import asyncio
import json
import re
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set


class EventBus:
    """Manages in-memory pub/sub and append-only event persistence to .events/YYYY-MM-DD.jsonl."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self.events_dir = self.root_dir / ".events"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.events_dir.chmod(0o700)
        except Exception:
            pass
        self._subscribers: Dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        session: str = "default",
        query_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Emit an event, append it to disk, and dispatch to active subscribers."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        event_id = f"ev-{uuid.uuid4().hex[:10]}"

        event_obj: Dict[str, Any] = {
            "id": event_id,
            "ts": now.isoformat(),
            "type": event_type,
            "session": session or "default",
            **payload,
        }
        if query_id:
            event_obj["query_id"] = query_id

        # Persist to .events/YYYY-MM-DD.jsonl
        event_file = self.events_dir / f"{date_str}.jsonl"
        with open(event_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_obj) + "\n")
            f.flush()
            os.fsync(f.fileno())

        # Notify in-memory async queues
        for queue, loop in list(self._subscribers.items()):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event_obj)
            except Exception:
                pass

        return event_obj

    def subscribe(self) -> asyncio.Queue:
        """Register a new async queue for live SSE events."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[q] = asyncio.get_running_loop()
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove an async queue."""
        self._subscribers.pop(q, None)

    def get_events(self, since: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve historical events (oldest to newest) from .events/YYYY-MM-DD.jsonl.

        Files are read newest first and reading stops as soon as `limit` matching events
        have been collected (or a file is older than `since`), so the cost depends on the
        requested window, not on how long the vault has been running.
        """
        if not self.events_dir.exists():
            return []

        since_day = since[:10] if since and re.match(r"^\d{4}-\d{2}-\d{2}", since) else None
        collected: List[Dict[str, Any]] = []
        for file in sorted(self.events_dir.glob("*.jsonl"), reverse=True):
            if since_day and file.stem < since_day:
                break
            file_events: List[Dict[str, Any]] = []
            try:
                with open(file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if since and ev.get("ts", "") <= since:
                            continue
                        file_events.append(ev)
            except OSError:
                continue
            collected = file_events + collected
            if limit > 0 and len(collected) >= limit:
                break

        if limit > 0:
            return collected[-limit:]
        return collected
