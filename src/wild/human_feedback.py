"""
Feature 64: Human Feedback Mechanism for Extraction Quality

Allows humans to rate extracted memories (thumbs up/down) to calibrate
the prompt evolution loop. Human feedback serves as a fitness signal
for the genetic algorithm.

Integration:
- Dashboard UI for memory review
- Feedback stored in intelligence.db
- Fitness calculation incorporates human feedback (15% weight)
- Trigger every ~20 sessions (configurable)
"""

import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional


class HumanFeedback:
    """
    Manages human feedback on extraction quality.

    Stores thumbs up/down feedback on memories and provides
    statistics for fitness calculation.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize with database path"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create feedback table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    feedback TEXT NOT NULL CHECK(feedback IN ('good', 'bad')),
                    timestamp TEXT NOT NULL,
                    session_context TEXT,
                    UNIQUE(memory_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_memory ON memory_feedback(memory_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON memory_feedback(timestamp)")

    def record_feedback(
        self,
        memory_id: str,
        feedback: str,
        session_context: Optional[str] = None
    ) -> bool:
        """
        Record human feedback for a memory.

        Args:
            memory_id: Memory identifier
            feedback: 'good' or 'bad'
            session_context: Optional context (e.g., "prompt_id=X,session=Y")

        Returns:
            True if recorded successfully

        Raises:
            ValueError: If feedback is not 'good' or 'bad'
        """
        if feedback not in ('good', 'bad'):
            raise ValueError("Feedback must be 'good' or 'bad'")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memory_feedback
                (memory_id, feedback, timestamp, session_context)
                VALUES (?, ?, ?, ?)
            """, (
                memory_id,
                feedback,
                datetime.now().isoformat(),
                session_context or ""
            ))
            conn.commit()

        return True

    def get_feedback(self, memory_id: str) -> Optional[Dict]:
        """
        Get feedback for a specific memory.

        Args:
            memory_id: Memory identifier

        Returns:
            Dict with feedback data or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM memory_feedback
                WHERE memory_id = ?
            """, (memory_id,)).fetchone()

        if row:
            return dict(row)
        return None

    def get_all_feedback(self) -> List[Dict]:
        """
        Get all feedback records.

        Returns:
            List of feedback dicts
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM memory_feedback
                ORDER BY timestamp DESC
            """).fetchall()

        return [dict(row) for row in rows]

    def get_stats(self) -> Dict:
        """
        Get feedback statistics.

        Returns:
            Dict with total, good, bad counts and positive_rate
        """
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM memory_feedback").fetchone()[0]
            good = conn.execute("SELECT COUNT(*) FROM memory_feedback WHERE feedback = 'good'").fetchone()[0]
            bad = conn.execute("SELECT COUNT(*) FROM memory_feedback WHERE feedback = 'bad'").fetchone()[0]

        positive_rate = good / total if total > 0 else 0.0

        return {
            "total": total,
            "good": good,
            "bad": bad,
            "positive_rate": positive_rate
        }

    def get_random_recent_memories(self, count: int = 5, days_back: int = 30) -> List[Dict]:
        """
        Get random recent memories for review, excluding already reviewed.

        Args:
            count: Number of memories to return
            days_back: How many days back to look

        Returns:
            List of memory dicts
        """
        # Load recent memories
        memories = _load_recent_memories(days_back=days_back)

        if not memories:
            return []

        # Get already reviewed memory IDs
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT memory_id FROM memory_feedback").fetchall()
            reviewed_ids = {row[0] for row in rows}

        # Filter out reviewed memories
        unreviewed = [m for m in memories if m.get("id") not in reviewed_ids]

        if not unreviewed:
            return []

        # Return random sample
        sample_size = min(count, len(unreviewed))
        return random.sample(unreviewed, sample_size)

    def get_human_feedback_score(self, prompt_id: str) -> Optional[float]:
        """
        Calculate human feedback score for memories from a specific prompt.

        Looks for memories with session_context containing "prompt_id=X"
        and returns the positive feedback rate.

        Args:
            prompt_id: Prompt identifier

        Returns:
            Score 0.0-1.0 (positive rate) or None if no feedback
        """
        with sqlite3.connect(self.db_path) as conn:
            # Find feedback for memories from this prompt
            rows = conn.execute("""
                SELECT feedback FROM memory_feedback
                WHERE session_context LIKE ?
            """, (f"%prompt_id={prompt_id}%",)).fetchall()

        if not rows:
            return None

        good_count = sum(1 for row in rows if row[0] == 'good')
        total = len(rows)

        return good_count / total if total > 0 else 0.0


def _load_recent_memories(days_back: int = 30) -> List[Dict]:
    """
    Load recent memories from memory files.

    Args:
        days_back: How many days back to look

    Returns:
        List of memory dicts
    """
    from ..memory_injector import load_search_index

    # Load all memories from search index
    all_memories = load_search_index()

    if not all_memories:
        return []

    # Filter to recent memories (if created field exists)
    cutoff = datetime.now() - timedelta(days=days_back)
    recent = []

    for mem in all_memories:
        created_str = mem.get("created")
        if created_str:
            try:
                created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                if created.replace(tzinfo=None) >= cutoff:
                    recent.append(mem)
            except (ValueError, AttributeError):
                # Include if date parsing fails (better to include than exclude)
                recent.append(mem)
        else:
            # Include if no created date
            recent.append(mem)

    return recent
