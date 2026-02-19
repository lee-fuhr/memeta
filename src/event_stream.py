"""
Memory event stream — pub/sub for memory system events.

Feature 22: Provides a publish/subscribe event bus backed by SQLite.
Events are persisted to the `memory_events` table for audit and replay,
and delivered synchronously to in-process subscribers.
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional


EVENT_TYPES = [
    "MEMORY_CREATED",
    "MEMORY_UPDATED",
    "MEMORY_ARCHIVED",
    "CONTRADICTION_DETECTED",
    "SEARCH_PERFORMED",
    "MAINTENANCE_RUN",
]


class EventStream:
    """
    Persistent event bus for the memory system.

    Events are stored in SQLite and dispatched synchronously to
    registered callbacks.  Subscriber errors are caught so one
    failing callback never blocks the rest.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"

        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────────────

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON memory_events(event_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_created ON memory_events(created_at)"
        )
        self.conn.commit()

    # ── Pub/Sub ────────────────────────────────────────────────────────────

    def publish(self, event_type: str, payload: Optional[dict] = None) -> int:
        """
        Persist an event and notify subscribers synchronously.

        Args:
            event_type: One of EVENT_TYPES.
            payload: Arbitrary JSON-serialisable dict (default {}).

        Returns:
            The auto-generated event id.

        Raises:
            ValueError: If *event_type* is not in EVENT_TYPES.
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Invalid event type '{event_type}'. "
                f"Must be one of: {', '.join(EVENT_TYPES)}"
            )

        if payload is None:
            payload = {}

        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)

        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO memory_events (event_type, payload_json, created_at) "
            "VALUES (?, ?, ?)",
            (event_type, payload_json, now),
        )
        self.conn.commit()
        event_id = cursor.lastrowid

        # Build the event dict delivered to callbacks
        event = {
            "id": event_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": now,
        }

        # Notify type-specific subscribers, then wildcard subscribers.
        for cb in list(self._subscribers.get(event_type, [])):
            try:
                cb(event)
            except Exception:
                pass  # isolate subscriber failures

        for cb in list(self._subscribers.get("*", [])):
            try:
                cb(event)
            except Exception:
                pass

        return event_id

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        Register *callback* for events of *event_type*.

        Use ``'*'`` to receive every event regardless of type.
        """
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a previously registered callback."""
        subs = self._subscribers.get(event_type, [])
        if callback in subs:
            subs.remove(callback)

    # ── Query helpers ──────────────────────────────────────────────────────

    def get_recent(
        self, event_type: Optional[str] = None, limit: int = 50
    ) -> List[Dict]:
        """
        Return recent events from the database, newest first.

        Args:
            event_type: Filter to a single type, or ``None`` for all.
            limit: Maximum rows to return.
        """
        cursor = self.conn.cursor()
        if event_type:
            cursor.execute(
                "SELECT id, event_type, payload_json, created_at "
                "FROM memory_events WHERE event_type = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            cursor.execute(
                "SELECT id, event_type, payload_json, created_at "
                "FROM memory_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_stats(self) -> Dict[str, int]:
        """Return event counts keyed by event type."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT event_type, COUNT(*) as cnt "
            "FROM memory_events GROUP BY event_type"
        )
        return {row["event_type"]: row["cnt"] for row in cursor.fetchall()}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def close(self):
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
