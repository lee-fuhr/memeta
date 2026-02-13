"""
Feature 27: Memory Reinforcement Scheduler

Schedules memory reviews based on FSRS-6 spaced repetition intervals.

Use cases:
- Surface memories due for review
- Track review history
- Adjust scheduling based on grades
- Daily review digest

Integration:
- Reads FSRS state from fsrs.db
- Updates review schedule in intelligence.db
- Works with pattern_detector for reinforcement recording
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


@dataclass
class ReviewSchedule:
    """Scheduled review for a memory"""
    id: str
    memory_id: str
    due_at: datetime
    last_reviewed: Optional[datetime]
    review_count: int
    difficulty: Optional[float]  # From FSRS
    stability: Optional[float]   # From FSRS
    next_interval_days: Optional[int]
    created_at: datetime
    updated_at: datetime


@dataclass
class ReviewHistoryEntry:
    """Single review event"""
    id: str
    memory_id: str
    reviewed_at: datetime
    grade: str  # FAIL, HARD, GOOD, EASY
    previous_interval_days: Optional[int]
    new_interval_days: Optional[int]
    difficulty_before: Optional[float]
    difficulty_after: Optional[float]
    stability_before: Optional[float]
    stability_after: Optional[float]


class ReinforcementScheduler:
    """
    Manages memory review scheduling based on FSRS-6.

    Core operations:
    - schedule_memory(): Add memory to review schedule
    - get_due_reviews(): Find memories due for review
    - record_review(): Record review and reschedule
    - get_review_stats(): Statistics on reviews
    """

    def __init__(self, db_path: str = None, fsrs_db_path: str = None):
        """Initialize scheduler with databases"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"

        if fsrs_db_path is None:
            fsrs_db_path = Path(__file__).parent.parent.parent / "fsrs.db"

        self.db_path = str(db_path)
        self.fsrs_db_path = str(fsrs_db_path)
        self._init_schema()

    def _init_schema(self):
        """Create review schedule tables"""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_schedule (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL UNIQUE,
                    due_at INTEGER NOT NULL,
                    last_reviewed INTEGER,
                    review_count INTEGER DEFAULT 0,
                    difficulty REAL,
                    stability REAL,
                    next_interval_days INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_due
                ON review_schedule(due_at ASC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_memory
                ON review_schedule(memory_id)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_history (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    reviewed_at INTEGER NOT NULL,
                    grade TEXT NOT NULL,
                    previous_interval_days INTEGER,
                    new_interval_days INTEGER,
                    difficulty_before REAL,
                    difficulty_after REAL,
                    stability_before REAL,
                    stability_after REAL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_memory
                ON review_history(memory_id, reviewed_at DESC)
            """)

            conn.commit()

    def schedule_memory(
        self,
        memory_id: str,
        initial_interval_days: int = 1
    ) -> str:
        """
        Add memory to review schedule.

        Args:
            memory_id: Memory to schedule
            initial_interval_days: Initial review interval (default 1 day)

        Returns:
            Schedule ID

        Raises:
            ValueError: If memory already scheduled
        """
        import hashlib
        schedule_id = hashlib.md5(f"{memory_id}-schedule".encode()).hexdigest()[:16]

        # Check if already scheduled
        with get_connection(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM review_schedule WHERE memory_id = ?",
                (memory_id,)
            ).fetchone()

            if existing:
                raise ValueError(f"Memory {memory_id} already scheduled")

            # Calculate due_at
            now = int(datetime.now().timestamp())
            due_at = now + (initial_interval_days * 86400)

            # Try to get FSRS state
            difficulty = None
            stability = None

            try:
                fsrs_conn = sqlite3.connect(self.fsrs_db_path)
                fsrs_row = fsrs_conn.execute(
                    "SELECT difficulty, stability, next_review FROM fsrs WHERE memory_id = ?",
                    (memory_id,)
                ).fetchone()
                fsrs_conn.close()

                if fsrs_row:
                    difficulty = fsrs_row[0]
                    stability = fsrs_row[1]
                    # Use FSRS next_review as due_at if available
                    if fsrs_row[2]:
                        due_at = int(fsrs_row[2])
            except Exception:
                pass  # FSRS DB might not exist yet

            # Insert schedule
            conn.execute("""
                INSERT INTO review_schedule
                (id, memory_id, due_at, last_reviewed, review_count, difficulty, stability, next_interval_days, created_at, updated_at)
                VALUES (?, ?, ?, NULL, 0, ?, ?, ?, ?, ?)
            """, (
                schedule_id,
                memory_id,
                due_at,
                difficulty,
                stability,
                initial_interval_days,
                now,
                now
            ))

            conn.commit()

        return schedule_id

    def get_due_reviews(
        self,
        limit: int = 10,
        project_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Get memories due for review.

        Args:
            limit: Maximum number to return
            project_id: Filter by project (optional)

        Returns:
            List of dicts with memory_id, due_at, overdue_days, importance
        """
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            # Query due reviews
            query = """
                SELECT rs.memory_id, rs.due_at, rs.review_count, rs.difficulty, rs.stability
                FROM review_schedule rs
                WHERE rs.due_at <= ?
                ORDER BY rs.due_at ASC
                LIMIT ?
            """

            cursor = conn.execute(query, (now, limit))
            rows = cursor.fetchall()

            results = []
            for row in rows:
                memory_id = row[0]
                due_at = row[1]
                review_count = row[2]
                difficulty = row[3]
                stability = row[4]

                overdue_days = (now - due_at) / 86400

                results.append({
                    'memory_id': memory_id,
                    'due_at': datetime.fromtimestamp(due_at),
                    'overdue_days': overdue_days,
                    'review_count': review_count,
                    'difficulty': difficulty,
                    'stability': stability
                })

            return results

    def record_review(
        self,
        memory_id: str,
        grade: str
    ):
        """
        Record review and reschedule.

        Args:
            memory_id: Memory reviewed
            grade: FAIL, HARD, GOOD, EASY

        Raises:
            ValueError: If grade invalid or memory not scheduled
        """
        # Validate grade
        valid_grades = {'FAIL', 'HARD', 'GOOD', 'EASY'}
        if grade.upper() not in valid_grades:
            raise ValueError(f"Invalid grade: {grade}. Must be one of {valid_grades}")

        grade = grade.upper()

        with get_connection(self.db_path) as conn:
            # Get current schedule
            row = conn.execute(
                "SELECT id, due_at, review_count, difficulty, stability, next_interval_days FROM review_schedule WHERE memory_id = ?",
                (memory_id,)
            ).fetchone()

            if not row:
                raise ValueError(f"Memory {memory_id} not scheduled")

            schedule_id = row[0]
            previous_due_at = row[1]
            review_count = row[2]
            difficulty_before = row[3]
            stability_before = row[4]
            previous_interval_days = row[5]

            # Get new FSRS state
            difficulty_after = difficulty_before
            stability_after = stability_before
            new_interval_days = previous_interval_days

            try:
                fsrs_conn = sqlite3.connect(self.fsrs_db_path)
                fsrs_row = fsrs_conn.execute(
                    "SELECT difficulty, stability, next_review FROM fsrs WHERE memory_id = ?",
                    (memory_id,)
                ).fetchone()
                fsrs_conn.close()

                if fsrs_row:
                    difficulty_after = fsrs_row[0]
                    stability_after = fsrs_row[1]
                    next_review = fsrs_row[2]

                    # Calculate new interval
                    now = int(datetime.now().timestamp())
                    if next_review:
                        new_interval_days = int((next_review - now) / 86400)
            except Exception:
                pass

            # Calculate new due_at
            now = int(datetime.now().timestamp())

            # Default progression if no FSRS state: double the interval (min 1 day)
            if new_interval_days is None or new_interval_days == previous_interval_days:
                new_interval_days = max(1, previous_interval_days * 2)

            new_due_at = now + (new_interval_days * 86400)

            # Update schedule
            conn.execute("""
                UPDATE review_schedule
                SET due_at = ?,
                    last_reviewed = ?,
                    review_count = ?,
                    difficulty = ?,
                    stability = ?,
                    next_interval_days = ?,
                    updated_at = ?
                WHERE memory_id = ?
            """, (
                new_due_at,
                now,
                review_count + 1,
                difficulty_after,
                stability_after,
                new_interval_days,
                now,
                memory_id
            ))

            # Record history
            import hashlib
            import random
            # Add random nonce to prevent ID collision when multiple reviews in same second
            nonce = random.randint(0, 999999)
            history_id = hashlib.md5(f"{memory_id}-{now}-{nonce}".encode()).hexdigest()[:16]

            conn.execute("""
                INSERT INTO review_history
                (id, memory_id, reviewed_at, grade, previous_interval_days, new_interval_days, difficulty_before, difficulty_after, stability_before, stability_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                history_id,
                memory_id,
                now,
                grade,
                previous_interval_days,
                new_interval_days,
                difficulty_before,
                difficulty_after,
                stability_before,
                stability_after
            ))

            conn.commit()

    def reschedule_memory(
        self,
        memory_id: str,
        new_due_at: Optional[datetime] = None
    ):
        """
        Manually reschedule memory.

        Args:
            memory_id: Memory to reschedule
            new_due_at: New due date (if None, calculates from FSRS)

        Raises:
            ValueError: If memory not scheduled
        """
        with get_connection(self.db_path) as conn:
            # Check if scheduled
            row = conn.execute(
                "SELECT id FROM review_schedule WHERE memory_id = ?",
                (memory_id,)
            ).fetchone()

            if not row:
                raise ValueError(f"Memory {memory_id} not scheduled")

            # Calculate due_at
            if new_due_at is None:
                # Try to get from FSRS
                try:
                    fsrs_conn = sqlite3.connect(self.fsrs_db_path)
                    fsrs_row = fsrs_conn.execute(
                        "SELECT next_review FROM fsrs WHERE memory_id = ?",
                        (memory_id,)
                    ).fetchone()
                    fsrs_conn.close()

                    if fsrs_row and fsrs_row[0]:
                        new_due_at = datetime.fromtimestamp(fsrs_row[0])
                    else:
                        # Default: 1 day from now
                        new_due_at = datetime.now() + timedelta(days=1)
                except Exception:
                    new_due_at = datetime.now() + timedelta(days=1)

            due_at_ts = int(new_due_at.timestamp())
            now = int(datetime.now().timestamp())

            conn.execute("""
                UPDATE review_schedule
                SET due_at = ?, updated_at = ?
                WHERE memory_id = ?
            """, (due_at_ts, now, memory_id))

            conn.commit()

    def get_review_stats(
        self,
        memory_id: Optional[str] = None
    ) -> dict:
        """
        Get review statistics.

        Args:
            memory_id: If provided, stats for that memory. Otherwise global.

        Returns:
            dict with total_reviews, avg_grade, review_count, etc.
        """
        with get_connection(self.db_path) as conn:
            if memory_id:
                # Per-memory stats
                cursor = conn.execute("""
                    SELECT COUNT(*), grade
                    FROM review_history
                    WHERE memory_id = ?
                    GROUP BY grade
                """, (memory_id,))

                grade_counts = {row[1]: row[0] for row in cursor.fetchall()}

                # Get schedule info
                schedule_row = conn.execute(
                    "SELECT review_count, difficulty, stability FROM review_schedule WHERE memory_id = ?",
                    (memory_id,)
                ).fetchone()

                if schedule_row:
                    return {
                        'memory_id': memory_id,
                        'total_reviews': schedule_row[0],
                        'grade_distribution': grade_counts,
                        'current_difficulty': schedule_row[1],
                        'current_stability': schedule_row[2]
                    }
                else:
                    return {
                        'memory_id': memory_id,
                        'total_reviews': 0,
                        'grade_distribution': {},
                        'current_difficulty': None,
                        'current_stability': None
                    }
            else:
                # Global stats
                total_scheduled = conn.execute(
                    "SELECT COUNT(*) FROM review_schedule"
                ).fetchone()[0]

                total_reviews = conn.execute(
                    "SELECT COUNT(*) FROM review_history"
                ).fetchone()[0]

                # Grade distribution
                cursor = conn.execute("""
                    SELECT grade, COUNT(*) as count
                    FROM review_history
                    GROUP BY grade
                """)

                grade_counts = {row[0]: row[1] for row in cursor.fetchall()}

                # Due today
                now = int(datetime.now().timestamp())
                due_today = conn.execute(
                    "SELECT COUNT(*) FROM review_schedule WHERE due_at <= ?",
                    (now,)
                ).fetchone()[0]

                return {
                    'total_scheduled': total_scheduled,
                    'total_reviews': total_reviews,
                    'grade_distribution': grade_counts,
                    'due_today': due_today
                }

    def get_daily_review_count(self) -> int:
        """Number of reviews due today"""
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM review_schedule WHERE due_at <= ?",
                (now,)
            ).fetchone()[0]

    def get_overdue_count(self) -> int:
        """Number of overdue reviews"""
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM review_schedule WHERE due_at < ?",
                (now,)
            ).fetchone()[0]
