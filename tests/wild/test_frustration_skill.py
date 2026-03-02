"""Tests for frustration-to-skill pipeline in SkillProposalEngine."""

import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone

from memory_system.wild.skill_proposal_engine import (
    SkillProposalEngine,
    SkillProposal,
    FrustrationAggregate,
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def temp_state(tmp_path):
    """Create temporary state file path."""
    return tmp_path / "action-patterns.json"


@pytest.fixture
def engine(temp_db, temp_state):
    """Create SkillProposalEngine with temp database and state file."""
    return SkillProposalEngine(db_path=temp_db, state_path=temp_state)


# --- Helpers ---

def _insert_frustration(engine, session_id, trigger_words, context=None, timestamp=None):
    """Insert a frustration record into sentiment_patterns."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    engine.db.conn.execute(
        "INSERT INTO sentiment_patterns (session_id, timestamp, sentiment, trigger_words, context) "
        "VALUES (?, ?, 'frustrated', ?, ?)",
        (session_id, ts, trigger_words, context),
    )
    engine.db.conn.commit()


# --- _aggregate_frustration_topics ---

class TestAggregateFrustrationTopics:
    """Tests for frustration topic aggregation."""

    def test_groups_by_trigger_words(self, engine):
        """Aggregation groups frustrations by trigger_words."""
        _insert_frustration(engine, "s1", "slow tests")
        _insert_frustration(engine, "s2", "slow tests")
        _insert_frustration(engine, "s3", "flaky deploy")

        result = engine._aggregate_frustration_topics()
        assert "slow tests" in result
        assert "flaky deploy" in result
        assert len(result) == 2

    def test_counts_occurrences_correctly(self, engine):
        """Aggregation counts total occurrences per topic."""
        for i in range(5):
            _insert_frustration(engine, f"s{i}", "slow tests")

        result = engine._aggregate_frustration_topics()
        assert result["slow tests"].occurrence_count == 5

    def test_counts_distinct_sessions(self, engine):
        """Aggregation counts distinct sessions per topic."""
        # Same session twice, different session once
        _insert_frustration(engine, "s1", "slow tests")
        _insert_frustration(engine, "s1", "slow tests")
        _insert_frustration(engine, "s2", "slow tests")

        result = engine._aggregate_frustration_topics()
        assert result["slow tests"].session_count == 2

    def test_respects_days_back_filter(self, engine):
        """Aggregation only includes records within days_back window."""
        recent_ts = datetime.now(timezone.utc).isoformat()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()

        _insert_frustration(engine, "s1", "slow tests", timestamp=recent_ts)
        _insert_frustration(engine, "s2", "slow tests", timestamp=old_ts)

        result = engine._aggregate_frustration_topics(days_back=90)
        assert result["slow tests"].occurrence_count == 1

    def test_empty_table_returns_empty(self, engine):
        """Aggregation on empty table returns empty dict."""
        result = engine._aggregate_frustration_topics()
        assert result == {}


# --- evaluate_frustration_patterns ---

class TestEvaluateFrustrationPatterns:
    """Tests for frustration-based skill proposal evaluation."""

    def test_meets_both_thresholds_proposes_skill(self, engine):
        """Topics meeting both occurrence and session thresholds generate proposals."""
        for i in range(6):
            _insert_frustration(engine, f"session-{i}", "slow tests")

        proposals = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert len(proposals) == 1
        assert proposals[0].proposed_name is not None

    def test_below_occurrence_threshold_no_proposal(self, engine):
        """Topics below occurrence threshold generate no proposals."""
        for i in range(3):
            _insert_frustration(engine, f"session-{i}", "slow tests")

        proposals = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=2)
        assert proposals == []

    def test_below_session_threshold_no_proposal(self, engine):
        """Topics below session threshold generate no proposals (even if occurrence count is high)."""
        # Many occurrences but only 2 sessions
        for i in range(10):
            _insert_frustration(engine, "s1" if i < 5 else "s2", "slow tests")

        proposals = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert proposals == []

    def test_dedup_against_existing_proposals(self, engine):
        """No duplicate proposals for topics with existing pending proposals."""
        for i in range(6):
            _insert_frustration(engine, f"session-{i}", "slow tests")

        # First evaluation creates proposals
        proposals_1 = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert len(proposals_1) == 1
        engine.create_proposal(proposals_1[0])

        # Second evaluation should skip it
        proposals_2 = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert proposals_2 == []

    def test_trigger_reason_is_frustration_pattern(self, engine):
        """Proposals from frustration pipeline have trigger_reason='frustration_pattern'."""
        for i in range(6):
            _insert_frustration(engine, f"session-{i}", "slow tests")

        proposals = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert proposals[0].trigger_reason == "frustration_pattern"

    def test_confidence_is_0_7(self, engine):
        """Frustration-based proposals have confidence=0.7."""
        for i in range(6):
            _insert_frustration(engine, f"session-{i}", "slow tests")

        proposals = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert proposals[0].confidence == pytest.approx(0.7)


# --- FrustrationAggregate ---

class TestFrustrationAggregate:
    """Tests for FrustrationAggregate dataclass."""

    def test_sample_evidence_limited_to_3(self, engine):
        """sample_evidence in FrustrationAggregate should contain at most 3 items."""
        for i in range(10):
            _insert_frustration(engine, f"session-{i}", "slow tests", context=f"context-{i}")

        result = engine._aggregate_frustration_topics()
        assert len(result["slow tests"].sample_evidence) <= 3


# --- Integration ---

class TestFrustrationIntegration:
    """Integration test: aggregate -> evaluate -> create pipeline."""

    def test_aggregate_evaluate_create_pipeline(self, engine):
        """Full pipeline: insert frustrations -> aggregate -> evaluate -> create proposals."""
        # Seed enough data
        for i in range(7):
            _insert_frustration(engine, f"sess-{i}", "flaky deploy", context=f"deploy failed again #{i}")

        # Aggregate
        aggregated = engine._aggregate_frustration_topics()
        assert "flaky deploy" in aggregated
        assert aggregated["flaky deploy"].occurrence_count == 7
        assert aggregated["flaky deploy"].session_count == 7

        # Evaluate
        proposals = engine.evaluate_frustration_patterns(min_occurrences=5, min_sessions=3)
        assert len(proposals) == 1

        # Create
        row_id = engine.create_proposal(proposals[0])
        assert row_id > 0

        # Verify persisted
        stored = engine.get_proposal(row_id)
        assert stored is not None
        assert stored["trigger_reason"] == "frustration_pattern"
        assert stored["confidence"] == pytest.approx(0.7)
        assert stored["status"] == "pending"
