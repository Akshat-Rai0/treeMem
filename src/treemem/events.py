"""Event bus and persistent event logger for TreeMem."""

import asyncio
import json
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
        self._subscribers: Set[asyncio.Queue] = set()

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
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event_obj)
            except Exception:
                pass

        return event_obj

    def subscribe(self) -> asyncio.Queue:
        """Register a new async queue for live SSE events."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove an async queue."""
        self._subscribers.discard(q)

    def get_events(self, since: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve historical events from .events/*.jsonl files."""
        if not self.events_dir.exists():
            return []

        all_events: List[Dict[str, Any]] = []
        for file in sorted(self.events_dir.glob("*.jsonl")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                ev = json.loads(line)
                                if since and ev.get("ts", "") <= since:
                                    continue
                                all_events.append(ev)
                            except Exception:
                                pass
            except Exception:
                pass

        if limit > 0:
            return all_events[-limit:]
        return all_events
