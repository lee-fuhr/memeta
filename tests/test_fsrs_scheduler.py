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
        # Should have: review_count >= 2, 2+ projects, stability >= 2.0
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


class TestBoundaryConditions:
    """Test stability/difficulty floor and ceiling enforcement"""

    def test_stability_floor_after_repeated_fails(self, scheduler):
        """Repeated FAILs should never push stability below 0.1"""
        scheduler.register_memory("mem-floor", project_id="LFI")
        for _ in range(20):
            scheduler.record_review("mem-floor", ReviewGrade.FAIL, "LFI")

        state = scheduler.get_state("mem-floor")
        assert state.stability >= 0.1

    def test_stability_ceiling_after_repeated_easy(self, scheduler):
        """Repeated EASY reviews should never push stability above 10.0"""
        scheduler.register_memory("mem-ceil", project_id="LFI")
        for _ in range(20):
            scheduler.record_review("mem-ceil", ReviewGrade.EASY, "LFI")

        state = scheduler.get_state("mem-ceil")
        assert state.stability <= 10.0

    def test_difficulty_stays_in_range(self, scheduler):
        """Difficulty should always be between 0.0 and 1.0"""
        scheduler.register_memory("mem-diff", project_id="LFI")
        # Push difficulty down with EASY reviews
        for _ in range(15):
            scheduler.record_review("mem-diff", ReviewGrade.EASY, "LFI")
        state = scheduler.get_state("mem-diff")
        assert 0.0 <= state.difficulty <= 1.0

        # Push difficulty up with FAIL reviews
        for _ in range(15):
            scheduler.record_review("mem-diff", ReviewGrade.FAIL, "LFI")
        state = scheduler.get_state("mem-diff")
        assert 0.0 <= state.difficulty <= 1.0

    def test_concurrent_registration_idempotent(self, scheduler):
        """Concurrent registration of same memory should be safe"""
        import threading
        errors = []

        def register():
            try:
                scheduler.register_memory("mem-concurrent", "LFI")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=register) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert scheduler.get_state("mem-concurrent") is not None

    def test_get_promoted_ids_empty(self, scheduler):
        """Should return empty set when no promoted memories"""
        ids = scheduler.get_promoted_ids()
        assert ids == set()

    def test_get_promoted_ids_returns_promoted(self, scheduler):
        """Should return set of promoted memory IDs"""
        scheduler.register_memory("mem-p1", project_id="LFI")
        scheduler.register_memory("mem-p2", project_id="LFI")
        scheduler.mark_promoted("mem-p1")

        ids = scheduler.get_promoted_ids()
        assert "mem-p1" in ids
        assert "mem-p2" not in ids


class TestDualPathPromotion:
    """Test dual-path promotion criteria (Path A: cross-project, Path B: deep reinforcement)"""

    def test_path_a_promotes_cross_project(self, scheduler):
        """Path A: cross-project with sufficient stability and reviews"""
        scheduler.register_memory("mem-a", project_id="LFI")
        scheduler.record_review("mem-a", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-a", ReviewGrade.EASY, project_id="ClientA")

        assert scheduler.is_promotion_ready("mem-a") is True

    def test_path_b_promotes_deep_reinforcement(self, scheduler):
        """Path B: deep reinforcement from single project should promote"""
        scheduler.register_memory("mem-b", project_id="LFI")
        # 5 EASY reviews from same project = stability ~ 1.0 * 2.2^5 = 51.5 (capped at 10)
        # and review_count = 5
        for _ in range(5):
            scheduler.record_review("mem-b", ReviewGrade.EASY, project_id="LFI")

        state = scheduler.get_state("mem-b")
        assert state.stability >= 4.0
        assert state.review_count >= 5
        assert scheduler.is_promotion_ready("mem-b") is True

    def test_path_b_rejects_insufficient_stability(self, scheduler):
        """Path B should reject when stability is below 4.0"""
        scheduler.register_memory("mem-c", project_id="LFI")
        # 5 GOOD reviews: stability = 1.0 * 1.5^5 = 7.59 — wait, that's above 4.0
        # Use HARD reviews to keep stability low: 1.0 * 0.8^5 = 0.328
        # Then add GOODs to get reviews to 5 but stability low
        scheduler.record_review("mem-c", ReviewGrade.HARD, project_id="LFI")
        scheduler.record_review("mem-c", ReviewGrade.HARD, project_id="LFI")
        scheduler.record_review("mem-c", ReviewGrade.HARD, project_id="LFI")
        scheduler.record_review("mem-c", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-c", ReviewGrade.GOOD, project_id="LFI")

        state = scheduler.get_state("mem-c")
        # stability = 1.0 * 0.8 * 0.8 * 0.8 * 1.5 * 1.5 = 1.152 — below 4.0
        assert state.stability < 4.0
        assert state.review_count == 5
        # Only 1 project, so Path A fails. Path B fails on stability.
        assert scheduler.is_promotion_ready("mem-c") is False

    def test_path_b_rejects_insufficient_reviews(self, scheduler):
        """Path B should reject when review count is below 5"""
        scheduler.register_memory("mem-d", project_id="LFI")
        # 3 EASY reviews: stability = 1.0 * 2.2^3 = 10.648 (capped at 10) but only 3 reviews
        for _ in range(3):
            scheduler.record_review("mem-d", ReviewGrade.EASY, project_id="LFI")

        state = scheduler.get_state("mem-d")
        assert state.stability >= 4.0
        assert state.review_count < 5
        # Only 1 project, so Path A fails. Path B fails on review count.
        assert scheduler.is_promotion_ready("mem-d") is False

    def test_existing_single_project_test_still_passes(self, scheduler):
        """Original test: 3 GOOD reviews from single project should NOT promote"""
        scheduler.register_memory("mem-001", project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review("mem-001", ReviewGrade.GOOD, project_id="LFI")

        # stability = 1.0 * 1.5^3 = 3.375, reviews = 3, projects = 1
        # Path A: fails (1 project < 2)
        # Path B: fails (3.375 < 4.0 and 3 < 5)
        assert scheduler.is_promotion_ready("mem-001") is False

    def test_path_b_in_get_promotion_candidates(self, scheduler):
        """get_promotion_candidates should return Path B candidates"""
        scheduler.register_memory("mem-deep", project_id="LFI")
        for _ in range(5):
            scheduler.record_review("mem-deep", ReviewGrade.EASY, project_id="LFI")

        candidates = scheduler.get_promotion_candidates()
        candidate_ids = [c.memory_id for c in candidates]
        assert "mem-deep" in candidate_ids
