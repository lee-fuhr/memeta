"""
Tests for Feature 27: Memory Reinforcement Scheduler

Test coverage:
- Initialization and schema creation
- Schedule creation (basic, duplicates, FSRS integration)
- Due review retrieval (basic, filtering, overdue)
- Review recording (basic, grade validation, rescheduling)
- Manual rescheduling
- Statistics (global and per-memory)
- Integration with FSRS
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
from datetime import datetime, timedelta
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from intelligence.reinforcement_scheduler import (
    ReinforcementScheduler,
    ReviewSchedule,
    ReviewHistoryEntry
)


@pytest.fixture
def temp_dbs():
    """Create temporary databases for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        intel_db = f.name

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        fsrs_db = f.name

    yield intel_db, fsrs_db

    # Cleanup
    Path(intel_db).unlink(missing_ok=True)
    Path(fsrs_db).unlink(missing_ok=True)


@pytest.fixture
def scheduler(temp_dbs):
    """Create scheduler with temp databases"""
    intel_db, fsrs_db = temp_dbs
    return ReinforcementScheduler(db_path=intel_db, fsrs_db_path=fsrs_db)


# === Initialization Tests ===

def test_scheduler_initialization(scheduler):
    """Test scheduler initializes database correctly"""
    # Check tables exist
    with sqlite3.connect(scheduler.db_path) as conn:
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'review_schedule' in table_names
        assert 'review_history' in table_names


def test_schema_indices(scheduler):
    """Test database indices are created"""
    with sqlite3.connect(scheduler.db_path) as conn:
        indices = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='index'
        """).fetchall()

        index_names = [i[0] for i in indices]
        assert 'idx_review_due' in index_names
        assert 'idx_review_memory' in index_names
        assert 'idx_history_memory' in index_names


# === Schedule Creation Tests ===

def test_schedule_memory_basic(scheduler):
    """Test creating basic schedule"""
    schedule_id = scheduler.schedule_memory("mem1", initial_interval_days=1)

    assert schedule_id is not None
    assert len(schedule_id) == 16  # MD5 hash truncated


def test_schedule_memory_duplicate(scheduler):
    """Test UNIQUE constraint prevents duplicate schedules"""
    scheduler.schedule_memory("mem1")

    with pytest.raises(ValueError, match="already scheduled"):
        scheduler.schedule_memory("mem1")


def test_schedule_memory_custom_interval(scheduler):
    """Test custom initial interval"""
    scheduler.schedule_memory("mem1", initial_interval_days=7)

    # Verify interval set correctly
    with sqlite3.connect(scheduler.db_path) as conn:
        row = conn.execute(
            "SELECT next_interval_days FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()

        assert row[0] == 7


# === Due Review Retrieval Tests ===

def test_get_due_reviews_empty(scheduler):
    """Test querying when no reviews due"""
    due = scheduler.get_due_reviews()
    assert len(due) == 0


def test_get_due_reviews_basic(scheduler):
    """Test finding due reviews"""
    # Schedule with interval of 0 days (due immediately)
    scheduler.schedule_memory("mem1", initial_interval_days=0)

    due = scheduler.get_due_reviews()

    assert len(due) == 1
    assert due[0]['memory_id'] == "mem1"
    assert due[0]['overdue_days'] >= 0


def test_get_due_reviews_not_yet_due(scheduler):
    """Test that future reviews not returned"""
    # Schedule with interval of 30 days (not due yet)
    scheduler.schedule_memory("mem1", initial_interval_days=30)

    due = scheduler.get_due_reviews()

    assert len(due) == 0


def test_get_due_reviews_ordering(scheduler):
    """Test due reviews ordered by due_at (oldest first)"""
    # Schedule multiple memories with different intervals
    scheduler.schedule_memory("mem1", initial_interval_days=0)  # Due now

    # Manually set due_at to past for mem2
    with sqlite3.connect(scheduler.db_path) as conn:
        now = int(datetime.now().timestamp())
        past = now - 86400  # 1 day ago

        scheduler.schedule_memory("mem2", initial_interval_days=0)
        conn.execute(
            "UPDATE review_schedule SET due_at = ? WHERE memory_id = ?",
            (past, "mem2")
        )
        conn.commit()

    due = scheduler.get_due_reviews()

    # mem2 should come first (older due_at)
    assert len(due) == 2
    assert due[0]['memory_id'] == "mem2"
    assert due[1]['memory_id'] == "mem1"


def test_get_due_reviews_limit(scheduler):
    """Test limit parameter"""
    # Schedule 5 memories, all due
    for i in range(5):
        scheduler.schedule_memory(f"mem{i}", initial_interval_days=0)

    due = scheduler.get_due_reviews(limit=3)

    assert len(due) == 3


# === Review Recording Tests ===

def test_record_review_basic(scheduler):
    """Test recording review"""
    scheduler.schedule_memory("mem1", initial_interval_days=0)

    # Record review
    scheduler.record_review("mem1", "GOOD")

    # Verify review count updated
    with sqlite3.connect(scheduler.db_path) as conn:
        row = conn.execute(
            "SELECT review_count FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()

        assert row[0] == 1


def test_record_review_invalid_grade(scheduler):
    """Test ValueError on invalid grade"""
    scheduler.schedule_memory("mem1")

    with pytest.raises(ValueError, match="Invalid grade"):
        scheduler.record_review("mem1", "INVALID")


def test_record_review_not_scheduled(scheduler):
    """Test ValueError on non-scheduled memory"""
    with pytest.raises(ValueError, match="not scheduled"):
        scheduler.record_review("nonexistent", "GOOD")


def test_record_review_history(scheduler):
    """Test review recorded in history"""
    scheduler.schedule_memory("mem1", initial_interval_days=0)
    scheduler.record_review("mem1", "GOOD")

    # Check history table
    with sqlite3.connect(scheduler.db_path) as conn:
        row = conn.execute(
            "SELECT memory_id, grade FROM review_history WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()

        assert row[0] == "mem1"
        assert row[1] == "GOOD"


def test_record_review_rescheduling(scheduler):
    """Test that recording review reschedules memory"""
    scheduler.schedule_memory("mem1", initial_interval_days=0)

    # Get original due_at
    with sqlite3.connect(scheduler.db_path) as conn:
        original_due = conn.execute(
            "SELECT due_at FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()[0]

    # Record review
    scheduler.record_review("mem1", "GOOD")

    # Get new due_at
    with sqlite3.connect(scheduler.db_path) as conn:
        new_due = conn.execute(
            "SELECT due_at FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()[0]

    # Should be rescheduled to future
    assert new_due > original_due


# === Manual Rescheduling Tests ===

def test_reschedule_memory_basic(scheduler):
    """Test manual rescheduling"""
    scheduler.schedule_memory("mem1")

    # Reschedule to tomorrow
    tomorrow = datetime.now() + timedelta(days=1)
    scheduler.reschedule_memory("mem1", tomorrow)

    # Verify updated
    with sqlite3.connect(scheduler.db_path) as conn:
        row = conn.execute(
            "SELECT due_at FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()

        due_at = datetime.fromtimestamp(row[0])

        # Should be approximately tomorrow (within 1 minute)
        assert abs((due_at - tomorrow).total_seconds()) < 60


def test_reschedule_memory_not_scheduled(scheduler):
    """Test ValueError on non-scheduled memory"""
    with pytest.raises(ValueError, match="not scheduled"):
        scheduler.reschedule_memory("nonexistent")


def test_reschedule_memory_auto(scheduler):
    """Test automatic rescheduling (new_due_at=None)"""
    scheduler.schedule_memory("mem1")

    # Get original due_at
    with sqlite3.connect(scheduler.db_path) as conn:
        original_due = conn.execute(
            "SELECT due_at FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()[0]

    # Reschedule with auto calculation
    scheduler.reschedule_memory("mem1", new_due_at=None)

    # Should have new due_at
    with sqlite3.connect(scheduler.db_path) as conn:
        new_due = conn.execute(
            "SELECT due_at FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()[0]

    # Could be same or different depending on FSRS state
    # Just verify it's a valid timestamp
    assert new_due > 0


# === Statistics Tests ===

def test_get_review_stats_global(scheduler):
    """Test global statistics"""
    # Create some schedules and reviews
    scheduler.schedule_memory("mem1", initial_interval_days=0)
    scheduler.schedule_memory("mem2", initial_interval_days=0)

    scheduler.record_review("mem1", "GOOD")
    scheduler.record_review("mem2", "EASY")

    stats = scheduler.get_review_stats()

    assert stats['total_scheduled'] == 2
    assert stats['total_reviews'] == 2
    assert 'GOOD' in stats['grade_distribution']
    assert 'EASY' in stats['grade_distribution']


def test_get_review_stats_per_memory(scheduler):
    """Test per-memory statistics"""
    scheduler.schedule_memory("mem1", initial_interval_days=0)

    scheduler.record_review("mem1", "GOOD")
    scheduler.record_review("mem1", "GOOD")
    scheduler.record_review("mem1", "EASY")

    stats = scheduler.get_review_stats(memory_id="mem1")

    assert stats['memory_id'] == "mem1"
    assert stats['total_reviews'] == 3
    assert stats['grade_distribution']['GOOD'] == 2
    assert stats['grade_distribution']['EASY'] == 1


def test_get_daily_review_count(scheduler):
    """Test counting reviews due today"""
    # Schedule some memories
    scheduler.schedule_memory("mem1", initial_interval_days=0)  # Due now
    scheduler.schedule_memory("mem2", initial_interval_days=30)  # Not due yet

    count = scheduler.get_daily_review_count()

    assert count == 1


def test_get_overdue_count(scheduler):
    """Test counting overdue reviews"""
    scheduler.schedule_memory("mem1", initial_interval_days=0)

    # Set due_at to past
    with sqlite3.connect(scheduler.db_path) as conn:
        past = int((datetime.now() - timedelta(days=1)).timestamp())
        conn.execute(
            "UPDATE review_schedule SET due_at = ? WHERE memory_id = ?",
            (past, "mem1")
        )
        conn.commit()

    count = scheduler.get_overdue_count()

    assert count == 1


# === FSRS Integration Tests ===

def test_fsrs_integration_reading_state(temp_dbs):
    """Test reading FSRS state when scheduling"""
    intel_db, fsrs_db = temp_dbs

    # Create FSRS DB with mock data
    with sqlite3.connect(fsrs_db) as conn:
        conn.execute("""
            CREATE TABLE fsrs (
                memory_id TEXT PRIMARY KEY,
                difficulty REAL,
                stability REAL,
                next_review INTEGER
            )
        """)

        # Add mock FSRS state
        next_review = int((datetime.now() + timedelta(days=3)).timestamp())
        conn.execute(
            "INSERT INTO fsrs (memory_id, difficulty, stability, next_review) VALUES (?, ?, ?, ?)",
            ("mem1", 0.5, 2.5, next_review)
        )
        conn.commit()

    scheduler = ReinforcementScheduler(db_path=intel_db, fsrs_db_path=fsrs_db)

    # Schedule memory - should read FSRS state
    scheduler.schedule_memory("mem1")

    # Verify FSRS state copied
    with sqlite3.connect(intel_db) as conn:
        row = conn.execute(
            "SELECT difficulty, stability, due_at FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()

        assert row[0] == 0.5  # difficulty
        assert row[1] == 2.5  # stability
        # due_at should be approximately next_review
        assert abs(row[2] - next_review) < 60


def test_fsrs_integration_updating_after_review(temp_dbs):
    """Test updating FSRS state after review"""
    intel_db, fsrs_db = temp_dbs

    # Create FSRS DB
    with sqlite3.connect(fsrs_db) as conn:
        conn.execute("""
            CREATE TABLE fsrs (
                memory_id TEXT PRIMARY KEY,
                difficulty REAL,
                stability REAL,
                next_review INTEGER
            )
        """)

        # Add mock FSRS state
        conn.execute(
            "INSERT INTO fsrs (memory_id, difficulty, stability, next_review) VALUES (?, ?, ?, ?)",
            ("mem1", 0.5, 2.5, int(datetime.now().timestamp()))
        )
        conn.commit()

    scheduler = ReinforcementScheduler(db_path=intel_db, fsrs_db_path=fsrs_db)
    scheduler.schedule_memory("mem1")

    # Update FSRS state (simulating FSRS recording review)
    with sqlite3.connect(fsrs_db) as conn:
        new_next_review = int((datetime.now() + timedelta(days=5)).timestamp())
        conn.execute(
            "UPDATE fsrs SET difficulty = ?, stability = ?, next_review = ? WHERE memory_id = ?",
            (0.3, 3.5, new_next_review, "mem1")
        )
        conn.commit()

    # Record review - should read updated FSRS state
    scheduler.record_review("mem1", "GOOD")

    # Verify scheduler has new FSRS state
    with sqlite3.connect(intel_db) as conn:
        row = conn.execute(
            "SELECT difficulty, stability FROM review_schedule WHERE memory_id = ?",
            ("mem1",)
        ).fetchone()

        assert row[0] == 0.3  # Updated difficulty
        assert row[1] == 3.5  # Updated stability
