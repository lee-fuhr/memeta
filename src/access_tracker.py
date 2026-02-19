"""
Feature 23: Memory access pattern tracker.

Tracks when and how memories are accessed, enabling frequency analysis,
identification of never-accessed memories, and access history auditing.

Usage:
    from memory_system.access_tracker import AccessTracker

    tracker = AccessTracker(db_path)
    access_id = tracker.log_access("mem-001", "search", query_context="deployment")
    freq = tracker.get_access_frequency("mem-001")
    stale = tracker.get_never_accessed(days=90)
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


VALID_ACCESS_TYPES = ["search", "direct", "briefing", "consolidation", "maintenance"]


class AccessTracker:
    """
    Tracks memory access patterns for analytics and decay decisions.

    Each instance manages its own SQLite database with a `memory_access_log`
    table.  All timestamps are stored as ISO-8601 UTC strings.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        """
        Initialize the access tracker database.

        Args:
            db_path: Path to the SQLite database file.  Defaults to
                     ``intelligence.db`` in the package root.
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ── Schema ──────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memory_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                access_type TEXT NOT NULL,
                query_context TEXT
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_mal_memory_id "
            "ON memory_access_log(memory_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_mal_accessed_at "
            "ON memory_access_log(accessed_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_mal_access_type "
            "ON memory_access_log(access_type)"
        )
        self.conn.commit()

    # ── Write ───────────────────────────────────────────────────────────

    def log_access(
        self,
        memory_id: str,
        access_type: str,
        query_context: Optional[str] = None,
    ) -> int:
        """
        Record a memory access event.

        Args:
            memory_id: Identifier of the memory that was accessed.
            access_type: One of VALID_ACCESS_TYPES.
            query_context: Optional free-text describing the access context
                           (e.g. the search query that surfaced this memory).

        Returns:
            The row id of the new access log entry.

        Raises:
            ValueError: If *access_type* is not in VALID_ACCESS_TYPES.
        """
        if access_type not in VALID_ACCESS_TYPES:
            raise ValueError(
                f"Invalid access_type {access_type!r}.  "
                f"Must be one of {VALID_ACCESS_TYPES}"
            )
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO memory_access_log (memory_id, accessed_at, access_type, query_context) "
            "VALUES (?, ?, ?, ?)",
            (memory_id, now, access_type, query_context),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ── Read ────────────────────────────────────────────────────────────

    def get_access_frequency(self, memory_id: str) -> Dict:
        """
        Return access frequency breakdown for a single memory.

        Returns:
            Dict with keys ``total_accesses``, ``last_accessed`` (ISO string
            or None), and ``by_type`` (dict mapping each access type to its
            count, defaulting to 0).
        """
        cur = self.conn.cursor()

        # Total + last accessed
        cur.execute(
            "SELECT COUNT(*) AS total, MAX(accessed_at) AS last "
            "FROM memory_access_log WHERE memory_id = ?",
            (memory_id,),
        )
        row = cur.fetchone()
        total = row["total"]
        last = row["last"]

        # Per-type counts
        cur.execute(
            "SELECT access_type, COUNT(*) AS cnt "
            "FROM memory_access_log WHERE memory_id = ? GROUP BY access_type",
            (memory_id,),
        )
        by_type = {t: 0 for t in VALID_ACCESS_TYPES}
        for r in cur.fetchall():
            by_type[r["access_type"]] = r["cnt"]

        return {
            "total_accesses": total,
            "last_accessed": last,
            "by_type": by_type,
        }

    def get_never_accessed(self, days: int = 90) -> List[str]:
        """
        Return memory_ids that have no access within the last *days* days.

        Specifically, this returns every distinct memory_id whose **most
        recent** access is older than the cutoff (or that has never been
        accessed at all within the window).

        Note: this method can only report on memories it *knows about* --
        i.e. those that appear at least once in the access log.  Memories
        that have literally never been logged will not appear here (the
        caller should cross-reference with the full memory inventory).

        Args:
            days: Look-back window in days.

        Returns:
            List of memory_id strings.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT memory_id FROM memory_access_log "
            "GROUP BY memory_id "
            "HAVING MAX(accessed_at) < ?",
            (cutoff,),
        )
        return [r["memory_id"] for r in cur.fetchall()]

    def get_most_accessed(self, limit: int = 20) -> List[Dict]:
        """
        Return the most frequently accessed memories, sorted descending.

        Returns:
            List of dicts with ``memory_id``, ``total_accesses``, and
            ``last_accessed``.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT memory_id, COUNT(*) AS total_accesses, "
            "MAX(accessed_at) AS last_accessed "
            "FROM memory_access_log "
            "GROUP BY memory_id "
            "ORDER BY total_accesses DESC "
            "LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_access_history(self, memory_id: str, limit: int = 50) -> List[Dict]:
        """
        Return the most recent access events for a memory, newest first.

        Returns:
            List of dicts with ``id``, ``memory_id``, ``accessed_at``,
            ``access_type``, and ``query_context``.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, memory_id, accessed_at, access_type, query_context "
            "FROM memory_access_log "
            "WHERE memory_id = ? "
            "ORDER BY accessed_at DESC "
            "LIMIT ?",
            (memory_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_stats(self) -> Dict:
        """
        Return aggregate statistics across all access logs.

        Returns:
            Dict with ``total_accesses``, ``unique_memories_accessed``, and
            ``by_type`` (counts per access type).
        """
        cur = self.conn.cursor()

        cur.execute("SELECT COUNT(*) AS total FROM memory_access_log")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(DISTINCT memory_id) AS uniq FROM memory_access_log")
        unique = cur.fetchone()["uniq"]

        cur.execute(
            "SELECT access_type, COUNT(*) AS cnt "
            "FROM memory_access_log GROUP BY access_type"
        )
        by_type = {t: 0 for t in VALID_ACCESS_TYPES}
        for r in cur.fetchall():
            by_type[r["access_type"]] = r["cnt"]

        return {
            "total_accesses": total,
            "unique_memories_accessed": unique,
            "by_type": by_type,
        }

    # ── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
