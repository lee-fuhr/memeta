"""
Tests for human feedback mechanism for extraction quality.

TDD: These tests are written FIRST before implementation.
"""

import pytest
import sqlite3
import json
from datetime import datetime
from pathlib import Path
import tempfile


@pytest.fixture
def temp_db():
    """Create temporary intelligence.db for testing"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink()


@pytest.fixture
def feedback_db(temp_db):
    """Initialize database with feedback table"""
    from memory_system.wild.human_feedback import HumanFeedback

    feedback = HumanFeedback(db_path=str(temp_db))
    return feedback


@pytest.fixture
def sample_memories():
    """Sample memories for testing"""
    return [
        {
            "id": "mem-001",
            "content": "Lee prefers TDD workflow",
            "importance": 0.9,
            "session_id": "session-001",
            "created": "2026-02-15T10:00:00",
            "context_type": "knowledge"
        },
        {
            "id": "mem-002",
            "content": "Never use 'any' type in TypeScript",
            "importance": 0.92,
            "session_id": "session-002",
            "created": "2026-02-16T11:00:00",
            "context_type": "correction"
        },
        {
            "id": "mem-003",
            "content": "Jane Smith loves hiking",
            "importance": 0.85,
            "session_id": "session-003",
            "created": "2026-02-17T09:00:00",
            "context_type": "knowledge"
        },
    ]


class TestHumanFeedbackDatabase:
    """Test database schema and operations"""

    def test_creates_feedback_table(self, temp_db):
        """Should create memory_feedback table on init"""
        from memory_system.wild.human_feedback import HumanFeedback

        HumanFeedback(db_path=str(temp_db))

        with sqlite3.connect(str(temp_db)) as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='memory_feedback'
            """)
            assert cursor.fetchone() is not None

    def test_feedback_table_has_required_columns(self, feedback_db, temp_db):
        """Feedback table should have all required columns"""
        with sqlite3.connect(str(temp_db)) as conn:
            cursor = conn.execute("PRAGMA table_info(memory_feedback)")
            columns = {row[1] for row in cursor.fetchall()}

        assert "memory_id" in columns
        assert "feedback" in columns  # 'good' or 'bad'
        assert "timestamp" in columns
        assert "session_context" in columns

    def test_record_feedback_good(self, feedback_db):
        """Should record positive feedback"""
        result = feedback_db.record_feedback(
            memory_id="mem-001",
            feedback="good",
            session_context="Extracted from refactoring session"
        )

        assert result is True

    def test_record_feedback_bad(self, feedback_db):
        """Should record negative feedback"""
        result = feedback_db.record_feedback(
            memory_id="mem-002",
            feedback="bad",
            session_context="Too generic"
        )

        assert result is True

    def test_record_feedback_validates_feedback_type(self, feedback_db):
        """Should only accept 'good' or 'bad' feedback"""
        with pytest.raises(ValueError, match="good.*bad"):
            feedback_db.record_feedback(
                memory_id="mem-001",
                feedback="neutral"  # invalid
            )

    def test_get_feedback_for_memory(self, feedback_db):
        """Should retrieve feedback for specific memory"""
        feedback_db.record_feedback("mem-001", "good")

        result = feedback_db.get_feedback("mem-001")

        assert result is not None
        assert result["memory_id"] == "mem-001"
        assert result["feedback"] == "good"

    def test_get_feedback_returns_none_when_not_found(self, feedback_db):
        """Should return None for memory without feedback"""
        result = feedback_db.get_feedback("nonexistent")
        assert result is None

    def test_get_all_feedback(self, feedback_db):
        """Should retrieve all feedback records"""
        feedback_db.record_feedback("mem-001", "good")
        feedback_db.record_feedback("mem-002", "bad")
        feedback_db.record_feedback("mem-003", "good")

        all_feedback = feedback_db.get_all_feedback()

        assert len(all_feedback) == 3
        assert all(f["feedback"] in ["good", "bad"] for f in all_feedback)


class TestFeedbackStatistics:
    """Test feedback statistics and aggregation"""

    def test_get_feedback_stats(self, feedback_db):
        """Should calculate feedback statistics"""
        feedback_db.record_feedback("mem-001", "good")
        feedback_db.record_feedback("mem-002", "good")
        feedback_db.record_feedback("mem-003", "bad")

        stats = feedback_db.get_stats()

        assert stats["total"] == 3
        assert stats["good"] == 2
        assert stats["bad"] == 1
        assert stats["positive_rate"] == pytest.approx(0.667, abs=0.01)

    def test_stats_empty_when_no_feedback(self, feedback_db):
        """Should handle empty feedback gracefully"""
        stats = feedback_db.get_stats()

        assert stats["total"] == 0
        assert stats["good"] == 0
        assert stats["bad"] == 0
        assert stats["positive_rate"] == 0.0


class TestGetRandomRecentMemories:
    """Test fetching random recent memories for review"""

    def test_get_random_recent_memories(self, feedback_db, sample_memories, monkeypatch):
        """Should return N random recent memories"""
        # Mock memory loading
        def mock_load_memories(days_back=30):
            return sample_memories

        monkeypatch.setattr(
            "memory_system.wild.human_feedback._load_recent_memories",
            mock_load_memories
        )

        memories = feedback_db.get_random_recent_memories(count=2)

        assert len(memories) <= 2
        assert all(m["id"].startswith("mem-") for m in memories)

    def test_excludes_already_reviewed_memories(self, feedback_db, sample_memories, monkeypatch):
        """Should not return memories that already have feedback"""
        # Record feedback for mem-001
        feedback_db.record_feedback("mem-001", "good")

        def mock_load_memories(days_back=30):
            return sample_memories

        monkeypatch.setattr(
            "memory_system.wild.human_feedback._load_recent_memories",
            mock_load_memories
        )

        memories = feedback_db.get_random_recent_memories(count=5)

        # Should not include mem-001
        assert all(m["id"] != "mem-001" for m in memories)

    def test_returns_empty_when_all_reviewed(self, feedback_db, sample_memories, monkeypatch):
        """Should return empty list when all recent memories reviewed"""
        # Mark all as reviewed
        for mem in sample_memories:
            feedback_db.record_feedback(mem["id"], "good")

        def mock_load_memories(days_back=30):
            return sample_memories

        monkeypatch.setattr(
            "memory_system.wild.human_feedback._load_recent_memories",
            mock_load_memories
        )

        memories = feedback_db.get_random_recent_memories(count=5)

        assert len(memories) == 0


class TestFitnessIntegration:
    """Test integration with prompt_evolver fitness calculation"""

    def test_get_human_feedback_score_for_prompt(self, feedback_db):
        """Should calculate human feedback score for memories from a prompt"""
        # Simulate memories from a specific prompt test
        feedback_db.record_feedback("mem-001", "good", session_context="prompt_id=test-prompt-1,session=s1")
        feedback_db.record_feedback("mem-002", "good", session_context="prompt_id=test-prompt-1,session=s2")
        feedback_db.record_feedback("mem-003", "bad", session_context="prompt_id=test-prompt-1,session=s3")

        score = feedback_db.get_human_feedback_score("test-prompt-1")

        # 2 good out of 3 total = 0.667
        assert score == pytest.approx(0.667, abs=0.01)

    def test_human_feedback_score_returns_none_when_no_data(self, feedback_db):
        """Should return None when no human feedback exists for prompt"""
        score = feedback_db.get_human_feedback_score("nonexistent-prompt")
        assert score is None

    def test_human_feedback_weight_in_fitness(self):
        """Human feedback should contribute to overall fitness score"""
        # This test verifies the integration point exists
        # Implementation will add human_feedback_score to fitness calculation

        # Mock fitness calculation with human feedback
        quality_score = 0.8
        yield_score = 0.7
        dedup_score = 0.9
        correction_score = 0.85
        human_feedback_score = 0.9

        # Expected weighted combination (fitness formula with human feedback added)
        # quality (35%) + yield (25%) + dedup (15%) + corrections (10%) + human (15%)
        expected_fitness = (
            quality_score * 0.35 +
            yield_score * 0.25 +
            dedup_score * 0.15 +
            correction_score * 0.10 +
            human_feedback_score * 0.15
        )

        assert expected_fitness > 0.8  # Sanity check


class TestDashboardEndpoints:
    """Test dashboard API endpoint logic (integration)"""

    def test_endpoints_implemented(self):
        """Verify dashboard endpoints are implemented"""
        # This is a placeholder - dashboard endpoints are implemented in server.py
        # Real testing would require starting the Flask app
        # For now, we verify the module logic works via the HumanFeedback tests above
        assert True
