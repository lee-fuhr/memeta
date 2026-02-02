"""
Tests for promotion executor - promotes validated memories from project → global scope

Tests promotion criteria checking, scope updates, tag additions,
FSRS state marking, and promotion logging.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fsrs_scheduler import FSRSScheduler, ReviewGrade
from src.memory_ts_client import MemoryTSClient
from src.promotion_executor import (
    PromotionExecutor,
    PromotionResult,
)


@pytest.fixture
def db_path(tmp_path):
    """Create temporary FSRS database"""
    return tmp_path / "test_fsrs.db"


@pytest.fixture
def memory_dir(tmp_path):
    """Create temporary memory directory"""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def scheduler(db_path):
    """Create FSRS scheduler"""
    return FSRSScheduler(db_path=db_path)


@pytest.fixture
def memory_client(memory_dir):
    """Create memory-ts client"""
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def executor(memory_dir, scheduler, memory_client):
    """Create promotion executor"""
    return PromotionExecutor(
        memory_dir=memory_dir,
        scheduler=scheduler,
        memory_client=memory_client,
    )


def create_promotable_memory(memory_client, scheduler, memory_id="mem-001",
                              project_id="LFI"):
    """Helper: create a memory that meets promotion criteria"""
    # Create memory file
    memory_client.create(
        content="Always validate user input at system boundaries",
        project_id=project_id,
        tags=["#learning"],
        importance=0.8,
        scope="project",
    )
    # Get the actual ID assigned
    memories = memory_client.search(project_id=project_id)
    actual_id = memories[-1].id

    # Register in FSRS and build up reviews
    scheduler.register_memory(actual_id, project_id=project_id)
    scheduler.record_review(actual_id, ReviewGrade.GOOD, project_id=project_id)
    scheduler.record_review(actual_id, ReviewGrade.EASY, project_id="ClientA")
    scheduler.record_review(actual_id, ReviewGrade.EASY, project_id="ClientB")

    return actual_id


class TestPromotionCriteria:
    """Test that promotion only happens when all criteria are met"""

    def test_promotes_when_criteria_met(self, executor, memory_client, scheduler):
        """Should promote memory that meets all criteria"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        results = executor.execute_promotions()

        assert len(results) >= 1
        promoted_ids = [r.memory_id for r in results]
        assert mem_id in promoted_ids

    def test_skips_low_stability(self, executor, memory_client, scheduler):
        """Should not promote memory with low stability"""
        memory_client.create(
            content="Unstable memory that keeps changing",
            project_id="LFI",
            tags=["#learning"],
            importance=0.8,
            scope="project",
        )
        memories = memory_client.search(project_id="LFI")
        mem_id = memories[-1].id

        # Register but only give it a FAIL review (reduces stability)
        scheduler.register_memory(mem_id, project_id="LFI")
        scheduler.record_review(mem_id, ReviewGrade.FAIL, project_id="LFI")
        scheduler.record_review(mem_id, ReviewGrade.FAIL, project_id="ClientA")
        scheduler.record_review(mem_id, ReviewGrade.FAIL, project_id="ClientB")

        results = executor.execute_promotions()
        promoted_ids = [r.memory_id for r in results]
        assert mem_id not in promoted_ids

    def test_skips_single_project(self, executor, memory_client, scheduler):
        """Should not promote memory validated in only 1 project"""
        memory_client.create(
            content="Single project insight",
            project_id="LFI",
            tags=["#learning"],
            importance=0.8,
            scope="project",
        )
        memories = memory_client.search(project_id="LFI")
        mem_id = memories[-1].id

        scheduler.register_memory(mem_id, project_id="LFI")
        # All reviews from same project
        scheduler.record_review(mem_id, ReviewGrade.EASY, project_id="LFI")
        scheduler.record_review(mem_id, ReviewGrade.EASY, project_id="LFI")
        scheduler.record_review(mem_id, ReviewGrade.EASY, project_id="LFI")

        results = executor.execute_promotions()
        promoted_ids = [r.memory_id for r in results]
        assert mem_id not in promoted_ids

    def test_skips_already_promoted(self, executor, memory_client, scheduler):
        """Should not re-promote an already promoted memory"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        # Promote once
        results1 = executor.execute_promotions()
        assert len(results1) >= 1

        # Try again - should not re-promote
        results2 = executor.execute_promotions()
        promoted_ids = [r.memory_id for r in results2]
        assert mem_id not in promoted_ids


class TestPromotionActions:
    """Test what promotion actually does"""

    def test_updates_scope_to_global(self, executor, memory_client, scheduler):
        """Should change memory scope from project to global"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        executor.execute_promotions()

        memory = memory_client.get(mem_id)
        assert memory.scope == "global"

    def test_adds_promoted_tag(self, executor, memory_client, scheduler):
        """Should add #promoted tag to memory"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        executor.execute_promotions()

        memory = memory_client.get(mem_id)
        assert "#promoted" in memory.tags

    def test_preserves_existing_tags(self, executor, memory_client, scheduler):
        """Should not remove existing tags when adding #promoted"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        executor.execute_promotions()

        memory = memory_client.get(mem_id)
        assert "#learning" in memory.tags
        assert "#promoted" in memory.tags

    def test_marks_promoted_in_fsrs(self, executor, memory_client, scheduler):
        """Should mark memory as promoted in FSRS scheduler"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        executor.execute_promotions()

        state = scheduler.get_state(mem_id)
        assert state.promoted is True
        assert state.promoted_date is not None

    def test_returns_promotion_result(self, executor, memory_client, scheduler):
        """Should return PromotionResult with details"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        results = executor.execute_promotions()

        assert len(results) >= 1
        result = [r for r in results if r.memory_id == mem_id][0]
        assert result.memory_id == mem_id
        assert result.old_scope == "project"
        assert result.new_scope == "global"
        assert result.stability > 0
        assert len(result.projects_validated) >= 2


class TestPromotionLogging:
    """Test promotion event logging"""

    def test_logs_to_database(self, executor, memory_client, scheduler, db_path):
        """Should log promotion event to FSRS review_log"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        executor.execute_promotions()

        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE memory_id = ?",
            (mem_id,)
        )
        count = cursor.fetchone()[0]
        conn.close()

        # Should have at least the 3 review entries from create_promotable_memory
        assert count >= 3


class TestBatchPromotion:
    """Test promoting multiple memories at once"""

    def test_promotes_multiple(self, executor, memory_client, scheduler):
        """Should promote all eligible memories in one call"""
        mem_id_1 = create_promotable_memory(memory_client, scheduler)

        # Create a second promotable memory
        memory_client.create(
            content="Structured logging with context fields aids debugging",
            project_id="LFI",
            tags=["#learning"],
            importance=0.7,
            scope="project",
        )
        memories = memory_client.search(content="Structured logging")
        mem_id_2 = memories[-1].id
        scheduler.register_memory(mem_id_2, project_id="LFI")
        scheduler.record_review(mem_id_2, ReviewGrade.GOOD, project_id="LFI")
        scheduler.record_review(mem_id_2, ReviewGrade.EASY, project_id="ClientA")
        scheduler.record_review(mem_id_2, ReviewGrade.EASY, project_id="ClientB")

        results = executor.execute_promotions()

        promoted_ids = [r.memory_id for r in results]
        assert mem_id_1 in promoted_ids
        assert mem_id_2 in promoted_ids

    def test_returns_empty_when_none_eligible(self, executor):
        """Should return empty list when no memories are promotion-ready"""
        results = executor.execute_promotions()
        assert results == []

    def test_promote_single_by_id(self, executor, memory_client, scheduler):
        """Should be able to promote a specific memory by ID"""
        mem_id = create_promotable_memory(memory_client, scheduler)

        result = executor.promote_single(mem_id)

        assert result is not None
        assert result.memory_id == mem_id
        assert result.new_scope == "global"

    def test_promote_single_not_ready(self, executor, memory_client, scheduler):
        """Should return None if specific memory isn't ready"""
        memory_client.create(
            content="Not ready yet",
            project_id="LFI",
            tags=["#learning"],
            importance=0.5,
            scope="project",
        )
        memories = memory_client.search(content="Not ready")
        mem_id = memories[-1].id
        scheduler.register_memory(mem_id, project_id="LFI")

        result = executor.promote_single(mem_id)
        assert result is None
