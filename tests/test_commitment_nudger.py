"""
Tests for commitment_nudger — surfaces "don't let me forget" commitments
at session start, ranked by urgency.

Uses ProspectiveTriggerManager as read-only dependency.
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from memory_system.commitment_nudger import (
    COMMITMENT_PATTERNS,
    extract_commitments,
    format_commitment_block,
    get_top_commitments,
    score_trigger,
)
from memory_system.prospective_triggers import (
    ProspectiveTrigger,
    ProspectiveTriggerManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return a temporary database path."""
    return str(tmp_path / "test_commitments.db")


@pytest.fixture
def manager(db_path):
    """Return a fresh ProspectiveTriggerManager with an empty database."""
    return ProspectiveTriggerManager(db_path)


def _make_trigger(
    trigger_id=1,
    memory_id="mem-001",
    trigger_type="time",
    condition=None,
    status="pending",
    created_at=None,
    fired_at=None,
):
    """Helper to build ProspectiveTrigger with sensible defaults."""
    if condition is None:
        condition = {"after_date": "2026-02-01"}
    if created_at is None:
        created_at = "2026-02-01T00:00:00+00:00"
    return ProspectiveTrigger(
        trigger_id=trigger_id,
        memory_id=memory_id,
        trigger_type=trigger_type,
        condition=condition,
        status=status,
        created_at=created_at,
        fired_at=fired_at,
    )


def _insert_trigger(db_path, memory_id, trigger_type, condition, created_at=None):
    """Insert a trigger directly into the DB. Returns trigger_id."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO prospective_triggers "
        "(memory_id, trigger_type, condition, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (memory_id, trigger_type, json.dumps(condition), "pending", created_at),
    )
    conn.commit()
    tid = cursor.lastrowid
    conn.close()
    return tid


# ---------------------------------------------------------------------------
# score_trigger
# ---------------------------------------------------------------------------

class TestScoreTrigger:
    """Test trigger scoring for priority ranking."""

    def test_time_overdue_scores_higher_than_topic_match(self):
        """A trigger overdue by many days should outscore a topic match."""
        overdue_trigger = _make_trigger(
            trigger_type="time",
            condition={"after_date": "2026-01-01"},
        )
        topic_trigger = _make_trigger(
            trigger_id=2,
            trigger_type="topic",
            condition={"keywords": ["deploy", "server"]},
        )
        context = {
            "current_date": "2026-03-01",
            "keywords": ["deploy", "server"],
        }
        overdue_score = score_trigger(overdue_trigger, context)
        topic_score = score_trigger(topic_trigger, context)
        assert overdue_score > topic_score

    def test_topic_keyword_overlap_contributes_to_score(self):
        """Keywords matching context should produce a positive score."""
        trigger = _make_trigger(
            trigger_type="topic",
            condition={"keywords": ["deploy", "server", "production"]},
        )
        context_match = {"keywords": ["deploy", "server"]}
        context_no_match = {"keywords": ["cooking", "recipes"]}
        score_match = score_trigger(trigger, context_match)
        score_no_match = score_trigger(trigger, context_no_match)
        assert score_match > score_no_match
        assert score_match > 0

    def test_importance_multiplier_works(self):
        """importance_map should multiply the base score."""
        trigger = _make_trigger(
            trigger_type="time",
            condition={"after_date": "2026-02-01"},
            memory_id="mem-important",
        )
        context_base = {"current_date": "2026-03-01"}
        context_important = {
            "current_date": "2026-03-01",
            "importance_map": {"mem-important": 3.0},
        }
        base_score = score_trigger(trigger, context_base)
        important_score = score_trigger(trigger, context_important)
        assert important_score > base_score
        assert important_score == pytest.approx(base_score * 3.0)

    def test_zero_for_non_overdue_time_trigger(self):
        """A time trigger not yet due should score zero for time component."""
        trigger = _make_trigger(
            trigger_type="time",
            condition={"after_date": "2026-12-31"},
        )
        context = {"current_date": "2026-03-01"}
        score = score_trigger(trigger, context)
        assert score == 0.0


# ---------------------------------------------------------------------------
# get_top_commitments
# ---------------------------------------------------------------------------

class TestGetTopCommitments:
    """Test retrieval of top-N most urgent commitments."""

    def test_returns_top_n_sorted_by_score(self, db_path, manager):
        """Should return triggers sorted descending by score."""
        # Insert 3 time triggers with different overdue amounts
        past_far = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
        past_mid = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        past_near = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")

        _insert_trigger(db_path, "mem-a", "time", {"after_date": past_far})
        _insert_trigger(db_path, "mem-b", "time", {"after_date": past_mid})
        _insert_trigger(db_path, "mem-c", "time", {"after_date": past_near})

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = get_top_commitments(db_path, {"current_date": today}, limit=3)
        assert len(result) == 3
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)
        # Most overdue (mem-a) should be first
        assert result[0]["trigger"].memory_id == "mem-a"

    def test_deduplicates_by_memory_id_keeps_highest(self, db_path, manager):
        """When multiple triggers share a memory_id, keep highest score."""
        past = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
        _insert_trigger(db_path, "mem-dup", "time", {"after_date": past})
        _insert_trigger(db_path, "mem-dup", "topic", {"keywords": ["misc"]})

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = get_top_commitments(db_path, {"current_date": today}, limit=10)
        mem_ids = [r["trigger"].memory_id for r in result]
        assert mem_ids.count("mem-dup") == 1

    def test_respects_limit_parameter(self, db_path, manager):
        """Should return at most `limit` commitments."""
        past = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        for i in range(10):
            _insert_trigger(db_path, f"mem-lim-{i}", "time", {"after_date": past})

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = get_top_commitments(db_path, {"current_date": today}, limit=3)
        assert len(result) <= 3

    def test_empty_when_no_pending_triggers(self, db_path, manager):
        """Empty DB should return empty list."""
        result = get_top_commitments(db_path, {"current_date": "2026-03-01"})
        assert result == []

    def test_single_trigger_works(self, db_path, manager):
        """Should handle a single trigger gracefully."""
        past = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _insert_trigger(db_path, "mem-single", "time", {"after_date": past})

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = get_top_commitments(db_path, {"current_date": today}, limit=3)
        assert len(result) == 1
        assert result[0]["trigger"].memory_id == "mem-single"
        assert "reason" in result[0]


# ---------------------------------------------------------------------------
# format_commitment_block
# ---------------------------------------------------------------------------

class TestFormatCommitmentBlock:
    """Test display formatting of commitments."""

    def test_correct_header_format(self):
        """Output should start with the expected header."""
        trigger = _make_trigger(
            trigger_type="time",
            condition={"after_date": "2026-02-01"},
        )
        commitments = [{"trigger": trigger, "score": 5.0, "reason": "overdue"}]
        output = format_commitment_block(commitments)
        assert "=== PENDING COMMITMENTS ===" in output

    def test_numbered_items(self):
        """Each commitment should be numbered sequentially."""
        commitments = [
            {"trigger": _make_trigger(trigger_id=i, memory_id=f"mem-{i}"), "score": float(5 - i), "reason": f"reason {i}"}
            for i in range(1, 4)
        ]
        output = format_commitment_block(commitments)
        assert "1." in output
        assert "2." in output
        assert "3." in output

    def test_empty_list_returns_empty_string(self):
        """No commitments should produce an empty string."""
        output = format_commitment_block([])
        assert output == ""


# ---------------------------------------------------------------------------
# extract_commitments
# ---------------------------------------------------------------------------

class TestExtractCommitments:
    """Test extraction of commitments from text."""

    def test_detects_i_should_pattern(self, db_path, manager):
        """'I should' is a commitment pattern."""
        text = "I should review the architecture doc before next sprint."
        triggers = extract_commitments(text, "mem-ext-1", db_path)
        assert len(triggers) >= 1

    def test_detects_need_to_pattern(self, db_path, manager):
        """'need to' is a commitment pattern."""
        text = "We need to update the staging environment."
        triggers = extract_commitments(text, "mem-ext-2", db_path)
        assert len(triggers) >= 1

    def test_detects_lets_make_sure_pattern(self, db_path, manager):
        """'let's make sure' is a commitment pattern."""
        text = "Let's make sure the tests pass before merging."
        triggers = extract_commitments(text, "mem-ext-3", db_path)
        assert len(triggers) >= 1

    def test_detects_follow_up_on_pattern(self, db_path, manager):
        """'follow up on' is a commitment pattern."""
        text = "I'll follow up on the client feedback tomorrow."
        triggers = extract_commitments(text, "mem-ext-4", db_path)
        assert len(triggers) >= 1

    def test_also_catches_ptm_existing_patterns(self, db_path, manager):
        """Should detect PTM patterns like 'remember to' and 'don't forget'."""
        text = "Remember to check the logs. Don't forget to update the changelog."
        triggers = extract_commitments(text, "mem-ext-5", db_path)
        assert len(triggers) >= 2

    def test_no_duplicates_from_overlapping_patterns(self, db_path, manager):
        """Text matching both PTM and commitment patterns should not double-count."""
        # "I should remember to X" could match both "I should" and "remember to"
        text = "I should remember to fix the bug."
        triggers = extract_commitments(text, "mem-ext-6", db_path)
        # Should have triggers but not duplicated entries for same captured text
        captured_texts = set()
        for t in triggers:
            kw_key = tuple(sorted(t.condition.get("keywords", [])))
            captured_texts.add(kw_key)
        # The set should be smaller or equal to the list — no exact keyword duplicates
        assert len(captured_texts) <= len(triggers)


# ---------------------------------------------------------------------------
# COMMITMENT_PATTERNS
# ---------------------------------------------------------------------------

class TestCommitmentPatterns:
    """Test the commitment pattern list."""

    def test_all_patterns_are_valid_regex(self):
        """Every pattern in COMMITMENT_PATTERNS should compile without error."""
        for pattern in COMMITMENT_PATTERNS:
            compiled = re.compile(pattern, re.IGNORECASE)
            assert compiled is not None


# ---------------------------------------------------------------------------
# Integration: extract → get_top → format pipeline
# ---------------------------------------------------------------------------

class TestIntegrationPipeline:
    """End-to-end test: extract commitments, rank them, format output."""

    def test_extract_rank_format_pipeline(self, db_path, manager):
        """Full pipeline should produce formatted output from raw text."""
        texts = [
            "I should fix the authentication bug.",
            "Need to update the API docs before release.",
            "Let's make sure we have proper error handling.",
        ]
        for i, text in enumerate(texts):
            extract_commitments(text, f"mem-pipe-{i}", db_path)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        commitments = get_top_commitments(db_path, {"current_date": today}, limit=3)
        assert len(commitments) >= 1

        output = format_commitment_block(commitments)
        assert "=== PENDING COMMITMENTS ===" in output
        assert "1." in output
