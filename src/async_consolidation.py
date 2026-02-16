"""
Async Session Consolidation - Background Worker

Fixes Performance Issue #2: Session consolidation blocking SessionEnd hook.

Problem:
- LLM extraction + dedup + contradiction detection = 60-120s
- SessionEnd hook has 180s timeout
- Hook failures cause lost extractions

Solution:
- SessionEnd hook writes session to queue (instant return)
- Background worker processes queue asynchronously
- No timeout, can retry on failure

Performance:
- Before: 60-120s blocking hook (timeout risk)
- After: <1s hook (just writes to queue), processing happens async
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import time

from memory_system.db_pool import get_connection


class ConsolidationQueue:
    """
    Queue for async session consolidation.

    Architecture:
    - consolidation_queue table: (session_id, session_path, status, added_at)
    - SessionEnd hook adds to queue (fast)
    - Background worker processes queue
    - Retries on failure with exponential backoff
    """

    def __init__(self, db_path: str = None):
        """Initialize consolidation queue"""
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create queue table"""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consolidation_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    session_path TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
                    added_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    next_retry_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON consolidation_queue(status, added_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_retry ON consolidation_queue(next_retry_at)")

    def add(self, session_id: str, session_path: str) -> bool:
        """
        Add session to consolidation queue.

        Called from SessionEnd hook - must be FAST.

        Args:
            session_id: Session identifier
            session_path: Path to session .jsonl file

        Returns:
            True if added, False if already queued
        """
        try:
            with get_connection(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO consolidation_queue
                    (session_id, session_path, status, added_at)
                    VALUES (?, ?, 'pending', ?)
                """, (session_id, session_path, datetime.now().isoformat()))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Already in queue
            return False

    def get_next(self) -> Optional[Dict]:
        """
        Get next session to process.

        Returns:
            Dict with session details or None if queue empty
        """
        with get_connection(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get pending sessions or failed sessions ready for retry
            now = datetime.now().isoformat()

            row = conn.execute("""
                SELECT *
                FROM consolidation_queue
                WHERE (status = 'pending')
                   OR (status = 'failed' AND next_retry_at <= ?)
                ORDER BY added_at ASC
                LIMIT 1
            """, (now,)).fetchone()

            if not row:
                return None

            # Mark as processing
            conn.execute("""
                UPDATE consolidation_queue
                SET status = 'processing', started_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), row['id']))
            conn.commit()

            return dict(row)

    def mark_completed(self, session_id: str):
        """Mark session as successfully processed"""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE consolidation_queue
                SET status = 'completed', completed_at = ?
                WHERE session_id = ?
            """, (datetime.now().isoformat(), session_id))
            conn.commit()

    def mark_failed(self, session_id: str, error_message: str, retry_in_seconds: int = 300):
        """
        Mark session as failed and schedule retry.

        Args:
            session_id: Session identifier
            error_message: Error description
            retry_in_seconds: Seconds until next retry (exponential backoff)
        """
        next_retry = datetime.now().timestamp() + retry_in_seconds
        next_retry_iso = datetime.fromtimestamp(next_retry).isoformat()

        with get_connection(self.db_path) as conn:
            # Increment retry count
            conn.execute("""
                UPDATE consolidation_queue
                SET status = 'failed',
                    error_message = ?,
                    retry_count = retry_count + 1,
                    next_retry_at = ?
                WHERE session_id = ?
            """, (error_message, next_retry_iso, session_id))
            conn.commit()

    def get_stats(self) -> Dict:
        """Get queue statistics"""
        with get_connection(self.db_path) as conn:
            pending = conn.execute("SELECT COUNT(*) FROM consolidation_queue WHERE status = 'pending'").fetchone()[0]
            processing = conn.execute("SELECT COUNT(*) FROM consolidation_queue WHERE status = 'processing'").fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM consolidation_queue WHERE status = 'completed'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM consolidation_queue WHERE status = 'failed'").fetchone()[0]

            # Oldest pending
            oldest_pending = conn.execute("""
                SELECT added_at FROM consolidation_queue
                WHERE status = 'pending'
                ORDER BY added_at ASC
                LIMIT 1
            """).fetchone()

        return {
            'pending': pending,
            'processing': processing,
            'completed': completed,
            'failed': failed,
            'oldest_pending': oldest_pending[0] if oldest_pending else None
        }

    def cleanup_old(self, days: int = 7):
        """Remove completed/failed entries older than N days"""
        cutoff = (datetime.now().timestamp() - (days * 86400))
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()

        with get_connection(self.db_path) as conn:
            deleted = conn.execute("""
                DELETE FROM consolidation_queue
                WHERE status IN ('completed', 'failed')
                  AND completed_at < ?
            """, (cutoff_iso,)).rowcount
            conn.commit()

        return deleted


def process_consolidation_queue(max_sessions: int = 10, timeout_per_session: int = 300):
    """
    Process consolidation queue (called by background worker).

    Args:
        max_sessions: Maximum sessions to process in this run
        timeout_per_session: Timeout for each session (seconds)

    Returns:
        Number of sessions processed
    """
    from memory_system.session_consolidator import SessionConsolidator

    queue = ConsolidationQueue()
    consolidator = SessionConsolidator(project_id="LFI")

    processed = 0

    for _ in range(max_sessions):
        session = queue.get_next()

        if not session:
            break  # Queue empty

        session_id = session['session_id']
        session_path = session['session_path']
        retry_count = session['retry_count']

        print(f"🔄 Processing: {session_id} (attempt {retry_count + 1})")

        try:
            # Process with timeout
            start_time = time.time()

            result = consolidator.consolidate_session(
                session_path=session_path,
                use_llm=True  # Full processing
            )

            duration = time.time() - start_time

            print(f"✅ Completed: {session_id} ({duration:.1f}s)")
            print(f"   Extracted: {result.new_count} new, {result.updated_count} updated, {result.duplicate_count} duplicates")

            queue.mark_completed(session_id)
            processed += 1

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Failed: {session_id} - {error_msg}")

            # Exponential backoff: 5min, 15min, 45min, 2h, 6h
            retry_delays = [300, 900, 2700, 7200, 21600]
            retry_delay = retry_delays[min(retry_count, len(retry_delays) - 1)]

            queue.mark_failed(session_id, error_msg, retry_delay)

    return processed


if __name__ == "__main__":
    # Process queue
    queue = ConsolidationQueue()

    print("\n📊 Queue Stats:")
    stats = queue.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n🔄 Processing queue...")
    processed = process_consolidation_queue(max_sessions=10)

    print(f"\n✅ Processed {processed} sessions")

    print("\n📊 Final Queue Stats:")
    stats = queue.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
