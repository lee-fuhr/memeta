"""
Tests for FSRS-6 memory review scheduler

Tests review scheduling, interval calculation, and promotion readiness.
"""

import json
import pytest
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fsrs_scheduler import (
    FSRSScheduler,
    ReviewGrade,
    MemoryReviewState,
)


@pytest.fixture
def db_path(tmp_path):
    """Create temporary database"""
    return tmp_path / "test_fsrs.db"


@pytest.fixture
def scheduler(db_path):
    """Create scheduler with fresh database"""
    return FSRSScheduler(db_path=db_path)


class TestDatabaseSetup:
    """Test database initialization"""

    def test_creates_database(self, db_path):
        """Should create SQLite database on init"""
        scheduler = FSRSScheduler(db_path=db_path)
        assert db_path.exists()

    def test_creates_tables(self, scheduler, db_path):
        """Should create required tables"""
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "memory_reviews" in tables
        assert "review_log" in tables


class TestRegisterMemory:
    """Test registering memories for review"""

    def test_register_new_memory(self, scheduler):
        """Should register a memory with default state"""
        scheduler.register_memory("mem-001", project_id="LFI")
        state = scheduler.get_state("mem-001")
        assert state is not None
        assert state.stability == 1.0
        assert state.difficulty == 0.5
        assert state.review_count == 0

    def test_register_idempotent(self, scheduler):
        """Registering same memory twice should not overwrite"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.register_memory("mem-001", project_id="LFI")
        state = scheduler.get_state("mem-001")
        assert state.review_count == 1  # Not reset

    def test_register_sets_due_date(self, scheduler):
        """Due date should be set to 1 day from now"""
        scheduler.register_memory("mem-001", project_id="LFI")
        state = scheduler.get_state("mem-001")
        assert state.due_date is not None
        due = datetime.fromisoformat(state.due_date)
        assert due > datetime.now()


class TestRecordReview:
    """Test review recording and state updates"""

    def test_good_review_increases_stability(self, scheduler):
        """A good review should increase stability"""
        scheduler.register_memory("mem-001", project_id="LFI")
        old_state = scheduler.get_state("mem-001")

        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        new_state = scheduler.get_state("mem-001")

        assert new_state.stability > old_state.stability

    def test_easy_review_increases_stability_more(self, scheduler):
        """An easy review (cross-project) should increase more than good"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.register_memory("mem-002", project_id="LFI")

        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-002", ReviewGrade.EASY, project_id="ClientA")

        state_good = scheduler.get_state("mem-001")
        state_easy = scheduler.get_state("mem-002")

        assert state_easy.stability > state_good.stability

    def test_hard_review_decreases_stability(self, scheduler):
        """A hard review should decrease stability"""
        scheduler.register_memory("mem-001", project_id="LFI")
        # First make stability > 1
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        mid_state = scheduler.get_state("mem-001")

        scheduler.record_review("mem-001", ReviewGrade.HARD, project_id="LFI")
        new_state = scheduler.get_state("mem-001")

        assert new_state.stability < mid_state.stability

    def test_review_increments_count(self, scheduler):
        """Each review should increment review_count"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")

        state = scheduler.get_state("mem-001")
        assert state.review_count == 2

    def test_review_updates_due_date(self, scheduler):
        """Review should update due date based on new interval"""
        scheduler.register_memory("mem-001", project_id="LFI")
        old_state = scheduler.get_state("mem-001")

        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        new_state = scheduler.get_state("mem-001")

        old_due = datetime.fromisoformat(old_state.due_date)
        new_due = datetime.fromisoformat(new_state.due_date)
        assert new_due > old_due

    def test_review_tracks_project(self, scheduler):
        """Reviews should track which project validated"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientA")

        state = scheduler.get_state("mem-001")
        projects = json.loads(state.projects_validated)
        assert "LFI" in projects
        assert "ClientA" in projects

    def test_review_logs_event(self, scheduler, db_path):
        """Each review should be logged to review_log table"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM review_log WHERE memory_id = 'mem-001'")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 1


class TestIntervalCalculation:
    """Test FSRS interval formula"""

    def test_initial_interval_is_one_day(self, scheduler):
        """First review should set ~1 day interval"""
        scheduler.register_memory("mem-001", project_id="LFI")
        state = scheduler.get_state("mem-001")
        due = datetime.fromisoformat(state.due_date)
        now = datetime.now()
        diff = (due - now).total_seconds() / 86400
        assert 0.5 < diff < 2.0  # roughly 1 day

    def test_intervals_grow_with_stability(self, scheduler):
        """Higher stability should produce longer intervals"""
        scheduler.register_memory("mem-001", project_id="LFI")

        # Record several good reviews
        intervals = []
        for _ in range(4):
            old_state = scheduler.get_state("mem-001")
            scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
            new_state = scheduler.get_state("mem-001")

            old_due = datetime.fromisoformat(old_state.due_date)
            new_due = datetime.fromisoformat(new_state.due_date)
            interval = (new_due - old_due).total_seconds() / 86400
            intervals.append(interval)

        # Each interval should generally be longer than the previous
        assert intervals[-1] > intervals[0]


class TestPromotionReadiness:
    """Test promotion criteria checking"""

    def test_not_ready_initially(self, scheduler):
        """New memory should not be promotion-ready"""
        scheduler.register_memory("mem-001", project_id="LFI")
        assert scheduler.is_promotion_ready("mem-001") is False

    def test_ready_after_sufficient_reviews(self, scheduler):
        """Should be ready after meeting all criteria"""
        scheduler.register_memory("mem-001", project_id="LFI")

        # Build up stability with reviews from multiple projects
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientA")
        scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientB")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")

        state = scheduler.get_state("mem-001")
        # Should have: review_count >= 3, 3 projects, stability > 3.0
        assert scheduler.is_promotion_ready("mem-001") is True

    def test_not_ready_single_project(self, scheduler):
        """Should not promote if only validated in 1 project"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")

        assert scheduler.is_promotion_ready("mem-001") is False

    def test_get_promotion_candidates(self, scheduler):
        """Should return list of memories ready for promotion"""
        # Register multiple memories
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.register_memory("mem-002", project_id="LFI")

        # Only mem-001 gets enough reviews
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientA")
        scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientB")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")

        candidates = scheduler.get_promotion_candidates()
        candidate_ids = [c.memory_id for c in candidates]
        assert "mem-001" in candidate_ids
        assert "mem-002" not in candidate_ids

    def test_mark_promoted(self, scheduler):
        """Should mark memory as promoted"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.mark_promoted("mem-001")

        state = scheduler.get_state("mem-001")
        assert state.promoted is True
        assert state.promoted_date is not None

    def test_promoted_excluded_from_candidates(self, scheduler):
        """Already promoted memories should not appear as candidates"""
        scheduler.register_memory("mem-001", project_id="LFI")
        for _ in range(4):
            scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientA")
        scheduler.record_review("mem-001", ReviewGrade.EASY, project_id="ClientB")

        scheduler.mark_promoted("mem-001")
        candidates = scheduler.get_promotion_candidates()
        assert len(candidates) == 0


class TestGetDueReviews:
    """Test finding memories due for review"""

    def test_due_reviews_returned(self, scheduler):
        """Should return memories whose due_date has passed"""
        scheduler.register_memory("mem-001", project_id="LFI")

        # Manually set due date to yesterday
        conn = sqlite3.connect(scheduler.db_path)
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE memory_reviews SET due_date = ? WHERE memory_id = ?",
            (yesterday, "mem-001")
        )
        conn.commit()
        conn.close()

        due = scheduler.get_due_reviews()
        assert len(due) >= 1
        assert due[0].memory_id == "mem-001"

    def test_future_reviews_not_returned(self, scheduler):
        """Should not return memories not yet due"""
        scheduler.register_memory("mem-001", project_id="LFI")
        # Default due date is tomorrow - should not be due yet
        due = scheduler.get_due_reviews()
        due_ids = [d.memory_id for d in due]
        assert "mem-001" not in due_ids
