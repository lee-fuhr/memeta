"""Tests for skill_provenance.py — TDD red phase.

Skill provenance tracker: records which sessions invoked which skills,
stores outcomes, and supports usage history and co-invocation queries.
"""

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from memory_system.skill_provenance import (
    ProvenanceRecord,
    SkillProvenanceTracker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def tracker(temp_db):
    return SkillProvenanceTracker(db_path=temp_db)


# ---------------------------------------------------------------------------
# ProvenanceRecord dataclass
# ---------------------------------------------------------------------------

class TestProvenanceRecord:
    def test_has_required_fields(self):
        r = ProvenanceRecord(
            id=1,
            skill_name="my-skill",
            session_id="abc123",
            invoked_at="2026-03-07T10:00:00",
            outcome="success",
            context_snippet="doing the thing",
            notes="",
        )
        assert r.skill_name == "my-skill"
        assert r.session_id == "abc123"
        assert r.outcome == "success"

    def test_notes_defaults_to_empty(self):
        r = ProvenanceRecord(
            id=1,
            skill_name="my-skill",
            session_id="abc",
            invoked_at="2026-03-07T10:00:00",
            outcome="success",
            context_snippet="",
            notes="",
        )
        assert r.notes == ""


# ---------------------------------------------------------------------------
# record_invocation()
# ---------------------------------------------------------------------------

class TestRecordInvocation:
    def test_returns_provenance_record(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1")
        assert isinstance(result, ProvenanceRecord)

    def test_stores_skill_name(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1")
        assert result.skill_name == "my-skill"

    def test_stores_session_id(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1")
        assert result.session_id == "session-1"

    def test_default_outcome_is_unknown(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1")
        assert result.outcome == "unknown"

    def test_custom_outcome(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1", outcome="success")
        assert result.outcome == "success"

    def test_stores_context_snippet(self, tracker):
        result = tracker.record_invocation(
            "my-skill", "session-1", context_snippet="fixing bug"
        )
        assert result.context_snippet == "fixing bug"

    def test_stores_notes(self, tracker):
        result = tracker.record_invocation(
            "my-skill", "session-1", notes="took two tries"
        )
        assert result.notes == "took two tries"

    def test_invoked_at_is_iso(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1")
        dt = datetime.fromisoformat(result.invoked_at)
        assert isinstance(dt, datetime)

    def test_persists_to_db(self, tracker, temp_db):
        tracker.record_invocation("my-skill", "session-1")
        conn = sqlite3.connect(temp_db)
        rows = conn.execute("SELECT * FROM skill_provenance").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_multiple_invocations_accumulate(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-2")
        history = tracker.get_history("my-skill")
        assert len(history) == 2

    def test_result_has_id(self, tracker):
        result = tracker.record_invocation("my-skill", "session-1")
        assert result.id is not None
        assert result.id > 0


# ---------------------------------------------------------------------------
# get_history()
# ---------------------------------------------------------------------------

class TestGetHistory:
    def test_returns_list(self, tracker):
        result = tracker.get_history("my-skill")
        assert isinstance(result, list)

    def test_empty_when_no_invocations(self, tracker):
        result = tracker.get_history("nonexistent")
        assert result == []

    def test_history_ordered_chronologically(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-2")
        history = tracker.get_history("my-skill")
        assert history[0].session_id == "session-1"
        assert history[1].session_id == "session-2"

    def test_history_contains_provenance_records(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        history = tracker.get_history("my-skill")
        assert all(isinstance(r, ProvenanceRecord) for r in history)

    def test_history_isolated_by_skill(self, tracker):
        tracker.record_invocation("skill-a", "session-1")
        tracker.record_invocation("skill-b", "session-1")
        assert len(tracker.get_history("skill-a")) == 1
        assert len(tracker.get_history("skill-b")) == 1


# ---------------------------------------------------------------------------
# get_first_use()
# ---------------------------------------------------------------------------

class TestGetFirstUse:
    def test_returns_datetime_after_invocation(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        result = tracker.get_first_use("my-skill")
        assert isinstance(result, datetime)

    def test_returns_none_for_unknown_skill(self, tracker):
        result = tracker.get_first_use("unknown")
        assert result is None

    def test_first_use_is_earliest_invocation(self, tracker):
        r1 = tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-2")
        first = tracker.get_first_use("my-skill")
        assert first == datetime.fromisoformat(r1.invoked_at)


# ---------------------------------------------------------------------------
# get_sessions_for_skill()
# ---------------------------------------------------------------------------

class TestGetSessionsForSkill:
    def test_returns_list(self, tracker):
        result = tracker.get_sessions_for_skill("my-skill")
        assert isinstance(result, list)

    def test_empty_for_unknown_skill(self, tracker):
        result = tracker.get_sessions_for_skill("unknown")
        assert result == []

    def test_returns_session_ids(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-2")
        sessions = tracker.get_sessions_for_skill("my-skill")
        assert "session-1" in sessions
        assert "session-2" in sessions

    def test_deduplicates_sessions(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-1")  # same session again
        sessions = tracker.get_sessions_for_skill("my-skill")
        assert sessions.count("session-1") == 1


# ---------------------------------------------------------------------------
# get_skills_for_session()
# ---------------------------------------------------------------------------

class TestGetSkillsForSession:
    def test_returns_list(self, tracker):
        result = tracker.get_skills_for_session("session-1")
        assert isinstance(result, list)

    def test_empty_for_unknown_session(self, tracker):
        result = tracker.get_skills_for_session("unknown")
        assert result == []

    def test_returns_skill_names(self, tracker):
        tracker.record_invocation("skill-a", "session-1")
        tracker.record_invocation("skill-b", "session-1")
        skills = tracker.get_skills_for_session("session-1")
        assert "skill-a" in skills
        assert "skill-b" in skills

    def test_deduplicates_skills(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-1")
        skills = tracker.get_skills_for_session("session-1")
        assert skills.count("my-skill") == 1


# ---------------------------------------------------------------------------
# get_co_invocations()
# ---------------------------------------------------------------------------

class TestGetCoInvocations:
    def test_returns_list(self, tracker):
        result = tracker.get_co_invocations("my-skill")
        assert isinstance(result, list)

    def test_empty_when_used_alone(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        result = tracker.get_co_invocations("my-skill")
        assert result == []

    def test_returns_co_invoked_skill_names(self, tracker):
        tracker.record_invocation("skill-a", "session-1")
        tracker.record_invocation("skill-b", "session-1")
        co = tracker.get_co_invocations("skill-a")
        assert "skill-b" in co

    def test_co_invocations_symmetric(self, tracker):
        tracker.record_invocation("skill-a", "session-1")
        tracker.record_invocation("skill-b", "session-1")
        assert "skill-b" in tracker.get_co_invocations("skill-a")
        assert "skill-a" in tracker.get_co_invocations("skill-b")

    def test_excludes_self(self, tracker):
        tracker.record_invocation("my-skill", "session-1")
        tracker.record_invocation("my-skill", "session-1")
        result = tracker.get_co_invocations("my-skill")
        assert "my-skill" not in result

    def test_deduplicates_across_sessions(self, tracker):
        # skill-b appears in two sessions with skill-a
        tracker.record_invocation("skill-a", "session-1")
        tracker.record_invocation("skill-b", "session-1")
        tracker.record_invocation("skill-a", "session-2")
        tracker.record_invocation("skill-b", "session-2")
        co = tracker.get_co_invocations("skill-a")
        assert co.count("skill-b") == 1


# ---------------------------------------------------------------------------
# outcome_summary()
# ---------------------------------------------------------------------------

class TestOutcomeSummary:
    def test_returns_dict(self, tracker):
        result = tracker.outcome_summary("my-skill")
        assert isinstance(result, dict)

    def test_empty_dict_for_unknown_skill(self, tracker):
        result = tracker.outcome_summary("unknown")
        assert result == {}

    def test_counts_outcomes(self, tracker):
        tracker.record_invocation("my-skill", "s1", outcome="success")
        tracker.record_invocation("my-skill", "s2", outcome="success")
        tracker.record_invocation("my-skill", "s3", outcome="failure")
        summary = tracker.outcome_summary("my-skill")
        assert summary["success"] == 2
        assert summary["failure"] == 1

    def test_unknown_outcome_counted(self, tracker):
        tracker.record_invocation("my-skill", "s1")
        summary = tracker.outcome_summary("my-skill")
        assert summary.get("unknown", 0) == 1


# ---------------------------------------------------------------------------
# invocation_count()
# ---------------------------------------------------------------------------

class TestInvocationCount:
    def test_returns_zero_for_unknown(self, tracker):
        assert tracker.invocation_count("my-skill") == 0

    def test_counts_correctly(self, tracker):
        tracker.record_invocation("my-skill", "s1")
        tracker.record_invocation("my-skill", "s2")
        assert tracker.invocation_count("my-skill") == 2

    def test_isolated_by_skill(self, tracker):
        tracker.record_invocation("skill-a", "s1")
        tracker.record_invocation("skill-b", "s1")
        assert tracker.invocation_count("skill-a") == 1
