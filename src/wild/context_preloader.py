"""F54: Context Pre-Loading (Dream Mode v2)

Pre-loads relevant context before work sessions.

Usage:
    from wild.context_preloader import ContextPreloader

    preloader = ContextPreloader()

    # Schedule preload
    preloader.schedule_preload(
        scheduled_for=datetime.now() + timedelta(hours=1),
        context_type="client_meeting",
        target_id="Connection Lab"
    )

    # Get preloaded context
    memories = preloader.get_preloaded_context("client_meeting")
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class PreloadTask:
    """Context preload task"""
    id: str
    scheduled_for: int
    context_type: str
    target_id: Optional[str]
    memories_loaded: Optional[List[str]]
    status: str  # pending, loaded, expired
    created_at: int


class ContextPreloader:
    """Pre-loads context for upcoming work sessions"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize context preloader

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def schedule_preload(
        self,
        scheduled_for: datetime,
        context_type: str,
        target_id: Optional[str] = None
    ) -> str:
        """Schedule context preload

        Args:
            scheduled_for: When to preload
            context_type: Type of context (client_meeting, coding_session, writing)
            target_id: Optional target (project name, client name)

        Returns:
            Preload task ID
        """
        task_id = str(uuid.uuid4())
        timestamp = int(time.time())
        scheduled_ts = int(scheduled_for.timestamp())

        self.db.conn.execute(
            """
            INSERT INTO context_preload_queue
            (id, scheduled_for, context_type, target_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, scheduled_ts, context_type, target_id, "pending", timestamp)
        )
        self.db.conn.commit()

        return task_id

    def get_pending_preloads(self) -> List[PreloadTask]:
        """Get preload tasks ready to execute

        Returns:
            List of pending tasks where scheduled_for <= now
        """
        now = int(time.time())

        rows = self.db.conn.execute(
            """
            SELECT id, scheduled_for, context_type, target_id, memories_loaded, status, created_at
            FROM context_preload_queue
            WHERE status = 'pending' AND scheduled_for <= ?
            ORDER BY scheduled_for ASC
            """,
            (now,)
        ).fetchall()

        return [self._row_to_preload_task(row) for row in rows]

    def mark_loaded(self, task_id: str, memory_ids: List[str]):
        """Mark preload task as loaded

        Args:
            task_id: Task ID
            memory_ids: List of memory IDs that were loaded
        """
        self.db.conn.execute(
            """
            UPDATE context_preload_queue
            SET status = 'loaded', memories_loaded = ?
            WHERE id = ?
            """,
            (json.dumps(memory_ids), task_id)
        )
        self.db.conn.commit()

    def mark_expired(self, task_id: str):
        """Mark preload task as expired

        Args:
            task_id: Task ID
        """
        self.db.conn.execute(
            """
            UPDATE context_preload_queue
            SET status = 'expired'
            WHERE id = ?
            """,
            (task_id,)
        )
        self.db.conn.commit()

    def get_preloaded_context(
        self,
        context_type: str,
        target_id: Optional[str] = None
    ) -> List[str]:
        """Get preloaded memory IDs for context type

        Args:
            context_type: Context type
            target_id: Optional target filter

        Returns:
            List of memory IDs
        """
        if target_id:
            row = self.db.conn.execute(
                """
                SELECT memories_loaded
                FROM context_preload_queue
                WHERE context_type = ? AND target_id = ? AND status = 'loaded'
                ORDER BY scheduled_for DESC
                LIMIT 1
                """,
                (context_type, target_id)
            ).fetchone()
        else:
            row = self.db.conn.execute(
                """
                SELECT memories_loaded
                FROM context_preload_queue
                WHERE context_type = ? AND status = 'loaded'
                ORDER BY scheduled_for DESC
                LIMIT 1
                """,
                (context_type,)
            ).fetchone()

        if row and row["memories_loaded"]:
            return json.loads(row["memories_loaded"])

        return []

    def clear_preload_queue(self, older_than_days: int = 7):
        """Clear old preload tasks

        Args:
            older_than_days: Clear tasks older than this many days
        """
        cutoff = int(time.time()) - (older_than_days * 86400)

        self.db.conn.execute(
            """
            DELETE FROM context_preload_queue
            WHERE created_at < ?
            """,
            (cutoff,)
        )
        self.db.conn.commit()

    def get_preload_statistics(self) -> Dict:
        """Get statistics about preload queue

        Returns:
            Dict with statistics
        """
        stats = {}

        # Count by status
        rows = self.db.conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM context_preload_queue
            GROUP BY status
            """
        ).fetchall()

        stats["by_status"] = {row["status"]: row["count"] for row in rows}

        # Count by context type
        rows = self.db.conn.execute(
            """
            SELECT context_type, COUNT(*) as count
            FROM context_preload_queue
            GROUP BY context_type
            """
        ).fetchall()

        stats["by_context_type"] = {row["context_type"]: row["count"] for row in rows}

        # Total count
        total = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM context_preload_queue"
        ).fetchone()
        stats["total"] = total["count"]

        return stats

    def _row_to_preload_task(self, row) -> PreloadTask:
        """Convert database row to PreloadTask"""
        memories = None
        if row["memories_loaded"]:
            memories = json.loads(row["memories_loaded"])

        return PreloadTask(
            id=row["id"],
            scheduled_for=row["scheduled_for"],
            context_type=row["context_type"],
            target_id=row["target_id"],
            memories_loaded=memories,
            status=row["status"],
            created_at=row["created_at"]
        )
