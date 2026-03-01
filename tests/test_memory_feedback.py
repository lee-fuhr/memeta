"""
Tests for memory feedback mechanism.

Covers:
- Dashboard endpoint: GET /api/memory-quality-check
- Dashboard endpoint: POST /api/memory-feedback
- Feedback storage in intelligence.db
- Integration with prompt_evolver fitness function
"""

import json
import pytest
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# We'll need to import the Flask app and feedback functions
# These don't exist yet - tests will fail (red phase)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Create a temporary intelligence.db for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Initialize tables
    with sqlite3.connect(db_path) as conn:
        # Create memory_feedback table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                feedback TEXT NOT NULL CHECK (feedback IN ('good', 'bad')),
                timestamp TEXT NOT NULL,
                session_context TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

    yield db_path

    # Cleanup
    db_path.unlink()


@pytest.fixture
def temp_memory_dir(tmp_path):
    """Create temporary memory directory with test memories."""
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()

    # Create 10 test memories
    for i in range(10):
        memory_path = memory_dir / f"mem-{i:03d}.md"
        content = f"""---
id: mem-{i:03d}
importance_weight: {0.5 + (i * 0.05)}
semantic_tags: ["test", "memory-{i}"]
context_type: knowledge
created_at: {(datetime.now(timezone.utc) - timedelta(days=i)).isoformat()}
---

This is test memory number {i}.
It contains some knowledge about testing.
"""
        memory_path.write_text(content)

    return memory_dir


# ---------------------------------------------------------------------------
# TestMemoryQualityCheckEndpoint
# ---------------------------------------------------------------------------

class TestMemoryQualityCheckEndpoint:
    """Tests for GET /api/memory-quality-check endpoint."""

    def test_returns_5_random_memories(self, temp_memory_dir):
        """Endpoint returns exactly 5 memories."""
        from memory_system.memory_feedback import get_quality_check_batch

        memories = get_quality_check_batch(memory_dir=temp_memory_dir, batch_size=5)

        assert len(memories) == 5
        assert all(isinstance(m, dict) for m in memories)

    def test_includes_required_fields(self, temp_memory_dir):
        """Each memory includes id, content, importance, tags."""
        from memory_system.memory_feedback import get_quality_check_batch

        memories = get_quality_check_batch(memory_dir=temp_memory_dir, batch_size=1)

        memory = memories[0]
        assert "id" in memory
        assert "content" in memory
        assert "importance" in memory
        assert "tags" in memory
        assert "created_at" in memory

    def test_filters_recent_memories_only(self, temp_memory_dir):
        """Only returns memories from last 30 days by default."""
        from memory_system.memory_feedback import get_quality_check_batch

        memories = get_quality_check_batch(
            memory_dir=temp_memory_dir,
            batch_size=10,
            days_back=7
        )

        # Should return fewer than 10 since only 7 days of memories exist
        assert len(memories) <= 7

    def test_excludes_already_reviewed(self, temp_memory_dir, temp_db):
        """Doesn't return memories that already have feedback."""
        from memory_system.memory_feedback import (
            get_quality_check_batch,
            save_feedback
        )

        # Add feedback for first 3 memories
        with sqlite3.connect(temp_db) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO memory_feedback (memory_id, feedback, timestamp) VALUES (?, ?, ?)",
                    (f"mem-{i:03d}", "good", datetime.now(timezone.utc).isoformat())
                )

        memories = get_quality_check_batch(
            memory_dir=temp_memory_dir,
            batch_size=5,
            db_path=temp_db
        )

        # Should not include mem-000, mem-001, mem-002
        memory_ids = [m["id"] for m in memories]
        assert "mem-000" not in memory_ids
        assert "mem-001" not in memory_ids
        assert "mem-002" not in memory_ids


# ---------------------------------------------------------------------------
# TestMemoryFeedbackEndpoint
# ---------------------------------------------------------------------------

class TestMemoryFeedbackEndpoint:
    """Tests for POST /api/memory-feedback endpoint."""

    def test_saves_feedback_to_db(self, temp_db):
        """Feedback is persisted to database."""
        from memory_system.memory_feedback import save_feedback

        result = save_feedback(
            memory_id="mem-001",
            feedback="good",
            session_context="test-session",
            db_path=temp_db
        )

        assert result is True

        # Verify in DB
        with sqlite3.connect(temp_db) as conn:
            row = conn.execute(
                "SELECT memory_id, feedback, session_context FROM memory_feedback WHERE memory_id = ?",
                ("mem-001",)
            ).fetchone()

        assert row is not None
        assert row[0] == "mem-001"
        assert row[1] == "good"
        assert row[2] == "test-session"

    def test_validates_feedback_value(self, temp_db):
        """Only accepts 'good' or 'bad' feedback."""
        from memory_system.memory_feedback import save_feedback

        # Should raise on invalid feedback
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            save_feedback(
                memory_id="mem-001",
                feedback="maybe",  # Invalid
                db_path=temp_db
            )

    def test_records_timestamp(self, temp_db):
        """Feedback includes ISO 8601 timestamp."""
        from memory_system.memory_feedback import save_feedback

        before = datetime.now(timezone.utc).isoformat()
        save_feedback("mem-001", "bad", db_path=temp_db)
        after = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(temp_db) as conn:
            row = conn.execute(
                "SELECT timestamp FROM memory_feedback WHERE memory_id = ?",
                ("mem-001",)
            ).fetchone()

        assert row[0] >= before
        assert row[0] <= after

    def test_allows_duplicate_feedback(self, temp_db):
        """Can provide feedback multiple times for same memory (tracks changes)."""
        from memory_system.memory_feedback import save_feedback

        save_feedback("mem-001", "good", db_path=temp_db)
        save_feedback("mem-001", "bad", db_path=temp_db)

        with sqlite3.connect(temp_db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_feedback WHERE memory_id = ?",
                ("mem-001",)
            ).fetchone()[0]

        assert count == 2


# ---------------------------------------------------------------------------
# TestFeedbackMetrics
# ---------------------------------------------------------------------------

class TestFeedbackMetrics:
    """Tests for feedback aggregation and metrics."""

    def test_calculates_quality_score(self, temp_db):
        """Calculates quality score as ratio of good/(good+bad)."""
        from memory_system.memory_feedback import (
            save_feedback,
            get_quality_metrics
        )

        # 7 good, 3 bad = 0.70 quality score
        for i in range(7):
            save_feedback(f"mem-{i:03d}", "good", db_path=temp_db)
        for i in range(7, 10):
            save_feedback(f"mem-{i:03d}", "bad", db_path=temp_db)

        metrics = get_quality_metrics(db_path=temp_db)

        assert metrics["total_feedback"] == 10
        assert metrics["good_count"] == 7
        assert metrics["bad_count"] == 3
        assert metrics["quality_score"] == pytest.approx(0.70, abs=0.01)

    def test_quality_score_by_timeframe(self, temp_db):
        """Can get quality metrics for specific time window."""
        from memory_system.memory_feedback import (
            save_feedback,
            get_quality_metrics
        )

        # Recent: 5 good, 0 bad
        for i in range(5):
            save_feedback(f"mem-{i:03d}", "good", db_path=temp_db)

        # Old feedback (simulated by manual timestamp)
        with sqlite3.connect(temp_db) as conn:
            old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
            conn.execute(
                "INSERT INTO memory_feedback (memory_id, feedback, timestamp) VALUES (?, ?, ?)",
                ("mem-old", "bad", old_ts)
            )

        metrics = get_quality_metrics(db_path=temp_db, days_back=30)

        # Should only count recent feedback
        assert metrics["total_feedback"] == 5
        assert metrics["quality_score"] == 1.0

    def test_handles_no_feedback(self, temp_db):
        """Returns sensible defaults when no feedback exists."""
        from memory_system.memory_feedback import get_quality_metrics

        metrics = get_quality_metrics(db_path=temp_db)

        assert metrics["total_feedback"] == 0
        assert metrics["good_count"] == 0
        assert metrics["bad_count"] == 0
        assert metrics["quality_score"] == 0.0  # Or None/undefined


# ---------------------------------------------------------------------------
# TestPromptEvolverIntegration
# ---------------------------------------------------------------------------

class TestPromptEvolverIntegration:
    """Tests for integration with prompt_evolver fitness function."""

    def test_feedback_contributes_to_fitness(self, temp_db):
        """Human feedback data is available for prompt fitness calculation."""
        from memory_system.memory_feedback import save_feedback

        # Integration point: prompt_evolver can query this feedback data
        # to calculate fitness scores for different prompt versions
        save_feedback("mem-001", "good", session_context="prompt-v1", db_path=temp_db)
        save_feedback("mem-002", "bad", session_context="prompt-v1", db_path=temp_db)

        with sqlite3.connect(temp_db) as conn:
            feedback = conn.execute(
                "SELECT feedback FROM memory_feedback WHERE session_context = ?",
                ("prompt-v1",)
            ).fetchall()

        assert len(feedback) == 2
        # Future: prompt_evolver will use this data in fitness calculation

    def test_get_feedback_for_prompt_version(self, temp_db):
        """Can retrieve all feedback for a specific prompt version."""
        from memory_system.memory_feedback import (
            save_feedback,
            get_feedback_by_context
        )

        save_feedback("mem-001", "good", session_context="prompt-v2", db_path=temp_db)
        save_feedback("mem-002", "good", session_context="prompt-v2", db_path=temp_db)
        save_feedback("mem-003", "bad", session_context="prompt-v1", db_path=temp_db)

        feedback = get_feedback_by_context("prompt-v2", db_path=temp_db)

        assert len(feedback) == 2
        assert all(f["session_context"] == "prompt-v2" for f in feedback)


# ---------------------------------------------------------------------------
# TestFeedbackTrigger
# ---------------------------------------------------------------------------

class TestFeedbackTrigger:
    """Tests for feedback prompt trigger logic."""

    def test_should_show_feedback_every_20_sessions(self, temp_db):
        """Feedback prompt appears every ~20 sessions."""
        from memory_system.memory_feedback import should_show_feedback_prompt

        # Mock session count
        assert should_show_feedback_prompt(session_count=20, db_path=temp_db) is True
        assert should_show_feedback_prompt(session_count=40, db_path=temp_db) is True
        assert should_show_feedback_prompt(session_count=19, db_path=temp_db) is False
        assert should_show_feedback_prompt(session_count=21, db_path=temp_db) is False

    def test_configurable_trigger_interval(self, temp_db):
        """Trigger interval can be configured."""
        from memory_system.memory_feedback import should_show_feedback_prompt

        assert should_show_feedback_prompt(session_count=10, interval=10, db_path=temp_db) is True
        assert should_show_feedback_prompt(session_count=30, interval=10, db_path=temp_db) is True
        assert should_show_feedback_prompt(session_count=15, interval=10, db_path=temp_db) is False

    def test_doesnt_trigger_if_recently_completed(self, temp_db):
        """Won't trigger if user completed feedback < 24 hours ago."""
        from memory_system.memory_feedback import (
            should_show_feedback_prompt,
            mark_feedback_completed
        )

        mark_feedback_completed(db_path=temp_db)

        # Even if session count hits interval, don't show if recently completed
        assert should_show_feedback_prompt(session_count=20, db_path=temp_db) is False
