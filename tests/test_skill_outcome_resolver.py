"""Tests for skill_outcome_resolver — session-end outcome resolution.

Reads active_skills from hook_state, checks the session summary
frustration_level, and updates provenance records accordingly.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def tmp_state(tmp_path):
    state_file = tmp_path / "hook-state.json"
    return state_file


def _seed_provenance(db_path, skill_name, session_id, outcome="unknown"):
    from memory_system.skill_provenance import SkillProvenanceTracker
    tracker = SkillProvenanceTracker(db_path=db_path)
    tracker.record_invocation(skill_name=skill_name, session_id=session_id, outcome=outcome)
    return tracker


def _seed_active_skills(state_file, session_id, skills):
    from memory_system.hook_state import update_session_state
    update_session_state({"active_skills": skills}, session_id=session_id, state_file=state_file)


# ── Import guard ───────────────────────────────────────────────────────────────

class TestImport:
    def test_module_importable(self):
        from memory_system.skill_outcome_resolver import resolve_session_outcomes  # noqa: F401


# ── resolve_session_outcomes — basic contract ─────────────────────────────────

class TestResolveContract:
    def setup_method(self):
        from memory_system.skill_outcome_resolver import resolve_session_outcomes
        self.resolve = resolve_session_outcomes

    def test_returns_dict(self, tmp_db, tmp_state):
        result = self.resolve("sess-empty", db_path=tmp_db, state_file=tmp_state)
        assert isinstance(result, dict)

    def test_returns_zero_updated_for_no_skills(self, tmp_db, tmp_state):
        result = self.resolve("sess-empty", db_path=tmp_db, state_file=tmp_state)
        assert result["updated"] == 0

    def test_returns_session_id(self, tmp_db, tmp_state):
        result = self.resolve("my-session", db_path=tmp_db, state_file=tmp_state)
        assert result["session_id"] == "my-session"

    def test_returns_outcome_field(self, tmp_db, tmp_state):
        result = self.resolve("my-session", db_path=tmp_db, state_file=tmp_state)
        assert "outcome" in result


# ── Outcome mapping ────────────────────────────────────────────────────────────

class TestOutcomeMapping:
    def setup_method(self):
        from memory_system.skill_outcome_resolver import resolve_session_outcomes
        self.resolve = resolve_session_outcomes

    def _run_with_frustration(self, frustration_level, db_path, state_file, session_id="s1"):
        _seed_provenance(db_path, "my-skill", session_id)
        _seed_active_skills(state_file, session_id, ["my-skill"])
        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value=frustration_level):
            return self.resolve(session_id, db_path=db_path, state_file=state_file)

    def test_low_frustration_maps_to_success(self, tmp_db, tmp_state):
        result = self._run_with_frustration("low", tmp_db, tmp_state)
        assert result["outcome"] == "success"

    def test_unknown_frustration_maps_to_success(self, tmp_db, tmp_state):
        result = self._run_with_frustration("unknown", tmp_db, tmp_state, session_id="s2")
        assert result["outcome"] == "success"

    def test_medium_frustration_maps_to_partial(self, tmp_db, tmp_state):
        result = self._run_with_frustration("medium", tmp_db, tmp_state, session_id="s3")
        assert result["outcome"] == "partial"

    def test_high_frustration_maps_to_partial(self, tmp_db, tmp_state):
        result = self._run_with_frustration("high", tmp_db, tmp_state, session_id="s4")
        assert result["outcome"] == "partial"


# ── DB update ─────────────────────────────────────────────────────────────────

class TestDbUpdate:
    def setup_method(self):
        from memory_system.skill_outcome_resolver import resolve_session_outcomes
        self.resolve = resolve_session_outcomes

    def test_updates_provenance_outcome(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        _seed_provenance(tmp_db, "seo-audit", "s1")
        _seed_active_skills(tmp_state, "s1", ["seo-audit"])

        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value="low"):
            self.resolve("s1", db_path=tmp_db, state_file=tmp_state)

        tracker = SkillProvenanceTracker(db_path=tmp_db)
        history = tracker.get_history("seo-audit")
        assert history[0].outcome == "success"

    def test_updates_multiple_skills(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        _seed_provenance(tmp_db, "skillA", "s1")
        _seed_provenance(tmp_db, "skillB", "s1")
        _seed_active_skills(tmp_state, "s1", ["skillA", "skillB"])

        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value="low"):
            result = self.resolve("s1", db_path=tmp_db, state_file=tmp_state)

        assert result["updated"] == 2
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        assert tracker.get_history("skillA")[0].outcome == "success"
        assert tracker.get_history("skillB")[0].outcome == "success"

    def test_returns_correct_updated_count(self, tmp_db, tmp_state):
        _seed_provenance(tmp_db, "foo", "s1")
        _seed_provenance(tmp_db, "bar", "s1")
        _seed_active_skills(tmp_state, "s1", ["foo", "bar"])

        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value="low"):
            result = self.resolve("s1", db_path=tmp_db, state_file=tmp_state)

        assert result["updated"] == 2

    def test_only_updates_skills_for_this_session(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        _seed_provenance(tmp_db, "skillA", "s1")
        _seed_provenance(tmp_db, "skillB", "s2")  # different session
        _seed_active_skills(tmp_state, "s1", ["skillA"])

        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value="low"):
            self.resolve("s1", db_path=tmp_db, state_file=tmp_state)

        tracker = SkillProvenanceTracker(db_path=tmp_db)
        # s2's skill should remain "unknown"
        assert tracker.get_history("skillB")[0].outcome == "unknown"

    def test_skips_skills_with_no_provenance_row(self, tmp_db, tmp_state):
        """Skills in active_skills but not in provenance — updated count is 0."""
        _seed_active_skills(tmp_state, "s1", ["never-recorded"])
        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value="low"):
            result = self.resolve("s1", db_path=tmp_db, state_file=tmp_state)
        assert result["updated"] == 0

    def test_does_not_update_already_resolved_outcomes(self, tmp_db, tmp_state):
        """Rows already set to 'success' or 'failure' should not be overwritten."""
        from memory_system.skill_provenance import SkillProvenanceTracker
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        tracker.record_invocation("my-skill", "s1", outcome="success")
        _seed_active_skills(tmp_state, "s1", ["my-skill"])

        with patch("memory_system.skill_outcome_resolver._get_frustration_level", return_value="high"):
            self.resolve("s1", db_path=tmp_db, state_file=tmp_state)

        history = tracker.get_history("my-skill")
        assert history[0].outcome == "success"  # not downgraded to "partial"


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def setup_method(self):
        from memory_system.skill_outcome_resolver import resolve_session_outcomes
        self.resolve = resolve_session_outcomes

    def test_handles_empty_active_skills(self, tmp_db, tmp_state):
        _seed_active_skills(tmp_state, "s1", [])
        result = self.resolve("s1", db_path=tmp_db, state_file=tmp_state)
        assert result["updated"] == 0

    def test_handles_missing_session_state(self, tmp_db, tmp_state):
        """Session never initialized — no active_skills key."""
        result = self.resolve("nonexistent-session", db_path=tmp_db, state_file=tmp_state)
        assert result["updated"] == 0

    def test_fails_silently_on_bad_db_path(self, tmp_state):
        """Bad DB path should not raise — just return 0 updated."""
        _seed_active_skills(tmp_state, "s1", ["my-skill"])
        result = self.resolve("s1", db_path="/nonexistent/path/db.db", state_file=tmp_state)
        assert "updated" in result
