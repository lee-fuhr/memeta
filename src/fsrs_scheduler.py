"""
FSRS-6 memory review scheduler

Simplified Free Spaced Repetition Scheduler for memory promotion.
Tracks review state, calculates intervals, determines promotion readiness.

Storage: SQLite database (fsrs.db)
"""

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import List, Optional

# Add src to path for db_pool import
sys.path.insert(0, str(Path(__file__).parent))
from db_pool import get_connection



class ReviewGrade(IntEnum):
    """Review quality grade"""
    FAIL = 1      # Memory contradicted or invalidated
    HARD = 2      # Memory not reinforced (weak signal)
    GOOD = 3      # Same insight from same project
    EASY = 4      # Same insight from different project (strong signal)


@dataclass
class MemoryReviewState:
    """Current FSRS state for a memory"""
    memory_id: str
    stability: float        # How well-established (0.0-10.0)
    difficulty: float       # How hard to remember (0.0-1.0)
    due_date: Optional[str]
    review_count: int
    last_review: Optional[str]
    projects_validated: str  # JSON array of project IDs
    promoted: bool
    promoted_date: Optional[str]


# FSRS-6 parameters (simplified)
INITIAL_STABILITY = 1.0
INITIAL_DIFFICULTY = 0.5
INITIAL_INTERVAL_DAYS = 1.0

# Grade multipliers for stability
STABILITY_MULTIPLIERS = {
    ReviewGrade.FAIL: 0.5,    # Halve stability
    ReviewGrade.HARD: 0.8,    # Reduce stability
    ReviewGrade.GOOD: 1.5,    # Moderate increase
    ReviewGrade.EASY: 2.2,    # Strong increase (cross-project)
}

# Promotion thresholds — Path A: cross-project
MIN_STABILITY_FOR_PROMOTION = 2.0
MIN_REVIEWS_FOR_PROMOTION = 2
MIN_PROJECTS_FOR_PROMOTION = 2

# Promotion thresholds — Path B: deep reinforcement (single project OK)
DEEP_STABILITY_FOR_PROMOTION = 4.0
DEEP_REVIEWS_FOR_PROMOTION = 5


class FSRSScheduler:
    """
    FSRS-6 scheduler for memory review and promotion

    Manages review state in SQLite, calculates intervals using
    simplified FSRS formula, determines promotion readiness.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize scheduler

        Args:
            db_path: Path to SQLite database (default: fsrs.db in module dir)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "fsrs.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Get pooled database connection

        Note: Returns connection from pool. Caller must close() when done.
        TODO: Refactor to use context manager pattern for auto-return to pool.
        """
        from db_pool import get_pool
        pool = get_pool(self.db_path)
        return pool.get_connection()

    def _init_db(self):
        """Create database tables if they don't exist"""
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_reviews (
                memory_id TEXT PRIMARY KEY,
                stability REAL DEFAULT 1.0,
                difficulty REAL DEFAULT 0.5,
                due_date TEXT,
                review_count INTEGER DEFAULT 0,
                last_review TEXT,
                projects_validated TEXT DEFAULT '[]',
                promoted BOOLEAN DEFAULT FALSE,
                promoted_date TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT,
                review_date TEXT,
                grade INTEGER,
                new_stability REAL,
                new_interval_days REAL,
                source_session TEXT,
                source_project TEXT
            )
        """)
        # Indexes for common query patterns
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_due
            ON memory_reviews(due_date, promoted)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_promotion
            ON memory_reviews(promoted, stability, review_count)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_review_log_memory
            ON review_log(memory_id, review_date)
        """)
        conn.commit()
        conn.close()

    def register_memory(self, memory_id: str, project_id: str = "LFI"):
        """
        Register a memory for FSRS tracking

        Idempotent - won't overwrite existing state.

        Args:
            memory_id: Memory identifier
            project_id: Source project
        """
        due_date = (datetime.now() + timedelta(days=INITIAL_INTERVAL_DAYS)).isoformat()
        projects = json.dumps([project_id])

        conn = self._connect()
        conn.execute(
            """INSERT OR IGNORE INTO memory_reviews
            (memory_id, stability, difficulty, due_date, review_count,
             projects_validated, promoted)
            VALUES (?, ?, ?, ?, 0, ?, FALSE)""",
            (memory_id, INITIAL_STABILITY, INITIAL_DIFFICULTY, due_date, projects)
        )
        conn.commit()
        conn.close()

    def get_state(self, memory_id: str) -> Optional[MemoryReviewState]:
        """
        Get current review state for a memory

        Args:
            memory_id: Memory identifier

        Returns:
            MemoryReviewState or None if not registered
        """
        conn = self._connect()
        cursor = conn.execute(
            """SELECT memory_id, stability, difficulty, due_date,
                      review_count, last_review, projects_validated,
                      promoted, promoted_date
               FROM memory_reviews WHERE memory_id = ?""",
            (memory_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return MemoryReviewState(
            memory_id=row[0],
            stability=row[1],
            difficulty=row[2],
            due_date=row[3],
            review_count=row[4],
            last_review=row[5],
            projects_validated=row[6],
            promoted=bool(row[7]),
            promoted_date=row[8],
        )

    def record_review(
        self,
        memory_id: str,
        grade: ReviewGrade,
        project_id: str = "LFI",
        session_id: Optional[str] = None
    ):
        """
        Record a review event and update memory state

        Args:
            memory_id: Memory identifier
            grade: Review quality (FAIL/HARD/GOOD/EASY)
            project_id: Project that validated this memory
            session_id: Session that triggered the review
        """
        state = self.get_state(memory_id)
        if state is None:
            return

        # Calculate new stability
        multiplier = STABILITY_MULTIPLIERS[grade]
        new_stability = max(0.1, min(10.0, state.stability * multiplier))

        # Update difficulty based on grade
        # Easy reviews lower difficulty, hard reviews raise it
        difficulty_delta = (3 - grade) * 0.1  # EASY=-0.1, GOOD=0, HARD=0.1, FAIL=0.2
        new_difficulty = max(0.0, min(1.0, state.difficulty + difficulty_delta))

        # Calculate new interval
        interval_days = new_stability * (1 + (grade - 2) * 0.5)
        interval_days = max(0.5, interval_days)  # Minimum half day
        new_due_date = (datetime.now() + timedelta(days=interval_days)).isoformat()

        # Update project list
        projects = json.loads(state.projects_validated)
        if project_id not in projects:
            projects.append(project_id)

        # Update database (transactional - both succeed or both rollback)
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE memory_reviews SET
                    stability = ?,
                    difficulty = ?,
                    due_date = ?,
                    review_count = review_count + 1,
                    last_review = ?,
                    projects_validated = ?
                WHERE memory_id = ?""",
                (new_stability, new_difficulty, new_due_date,
                 datetime.now().isoformat(), json.dumps(projects), memory_id)
            )

            # Log the review event
            conn.execute(
                """INSERT INTO review_log
                (memory_id, review_date, grade, new_stability,
                 new_interval_days, source_session, source_project)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (memory_id, datetime.now().isoformat(), int(grade),
                 new_stability, interval_days, session_id, project_id)
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def is_promotion_ready(self, memory_id: str) -> bool:
        """
        Check if a memory meets promotion criteria via either path.

        Path A (cross-project): stability >= 2.0, reviews >= 2, projects >= 2
        Path B (deep reinforcement): stability >= 4.0, reviews >= 5 (single project OK)

        Args:
            memory_id: Memory identifier

        Returns:
            True if ready for promotion
        """
        state = self.get_state(memory_id)
        if state is None:
            return False

        if state.promoted:
            return False

        projects = json.loads(state.projects_validated)

        # Path A: cross-project validation
        if (state.stability >= MIN_STABILITY_FOR_PROMOTION
                and state.review_count >= MIN_REVIEWS_FOR_PROMOTION
                and len(projects) >= MIN_PROJECTS_FOR_PROMOTION):
            return True

        # Path B: deep reinforcement (single project OK)
        if (state.stability >= DEEP_STABILITY_FOR_PROMOTION
                and state.review_count >= DEEP_REVIEWS_FOR_PROMOTION):
            return True

        return False

    def get_promotion_candidates(self) -> List[MemoryReviewState]:
        """
        Get all memories ready for promotion via either path.

        Path A: stability >= 2.0, reviews >= 2, projects >= 2
        Path B: stability >= 4.0, reviews >= 5

        Returns:
            List of MemoryReviewState objects that meet promotion criteria
        """
        conn = self._connect()
        # Broad SQL filter — catches both paths, then refine in Python
        cursor = conn.execute(
            """SELECT memory_id, stability, difficulty, due_date,
                      review_count, last_review, projects_validated,
                      promoted, promoted_date
               FROM memory_reviews
               WHERE promoted = FALSE
                 AND stability >= ?
                 AND review_count >= ?""",
            (MIN_STABILITY_FOR_PROMOTION, MIN_REVIEWS_FOR_PROMOTION)
        )

        candidates = []
        for row in cursor.fetchall():
            state = MemoryReviewState(
                memory_id=row[0],
                stability=row[1],
                difficulty=row[2],
                due_date=row[3],
                review_count=row[4],
                last_review=row[5],
                projects_validated=row[6],
                promoted=bool(row[7]),
                promoted_date=row[8],
            )
            projects = json.loads(state.projects_validated)

            # Path A: cross-project
            if (state.stability >= MIN_STABILITY_FOR_PROMOTION
                    and state.review_count >= MIN_REVIEWS_FOR_PROMOTION
                    and len(projects) >= MIN_PROJECTS_FOR_PROMOTION):
                candidates.append(state)
                continue

            # Path B: deep reinforcement
            if (state.stability >= DEEP_STABILITY_FOR_PROMOTION
                    and state.review_count >= DEEP_REVIEWS_FOR_PROMOTION):
                candidates.append(state)

        conn.close()
        return candidates

    def mark_promoted(self, memory_id: str):
        """
        Mark a memory as promoted

        Args:
            memory_id: Memory identifier
        """
        conn = self._connect()
        conn.execute(
            """UPDATE memory_reviews SET
                promoted = TRUE,
                promoted_date = ?
            WHERE memory_id = ?""",
            (datetime.now().isoformat(), memory_id)
        )
        conn.commit()
        conn.close()

    def get_promoted_ids(self) -> set:
        """
        Get set of all promoted memory IDs (for batch filtering).

        Returns:
            Set of memory_id strings that are promoted
        """
        conn = self._connect()
        cursor = conn.execute(
            "SELECT memory_id FROM memory_reviews WHERE promoted = TRUE"
        )
        promoted = {row[0] for row in cursor.fetchall()}
        conn.close()
        return promoted

    def get_due_reviews(self) -> List[MemoryReviewState]:
        """
        Get memories whose review is due (due_date <= now)

        Returns:
            List of memories due for review
        """
        conn = self._connect()
        now = datetime.now().isoformat()
        cursor = conn.execute(
            """SELECT memory_id, stability, difficulty, due_date,
                      review_count, last_review, projects_validated,
                      promoted, promoted_date
               FROM memory_reviews
               WHERE due_date <= ? AND promoted = FALSE""",
            (now,)
        )

        due = []
        for row in cursor.fetchall():
            due.append(MemoryReviewState(
                memory_id=row[0],
                stability=row[1],
                difficulty=row[2],
                due_date=row[3],
                review_count=row[4],
                last_review=row[5],
                projects_validated=row[6],
                promoted=bool(row[7]),
                promoted_date=row[8],
            ))

        conn.close()
        return due
