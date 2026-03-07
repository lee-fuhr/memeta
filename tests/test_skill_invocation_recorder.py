"""Tests for skill_invocation_recorder — PreToolUse hook logic.

The recorder extracts skill invocations from PreToolUse payloads,
calls SkillProvenanceTracker.record_invocation(), and appends the
skill name to active_skills in hook_state.
"""

import json
import tempfile
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def tmp_state(tmp_path):
    return tmp_path / "hook-state.json"


def _skill_payload(skill_name="my-skill", session_id="sess-abc", args="Do the thing"):
    """Build a realistic PreToolUse payload for a Skill tool call."""
    return {
        "sessionId": session_id,
        "toolName": "Skill",
        "toolInput": {
            "skill": skill_name,
            "args": args,
        },
    }


def _other_payload(tool_name="Read"):
    """Build a PreToolUse payload for a non-Skill tool."""
    return {
        "sessionId": "sess-xyz",
        "toolName": tool_name,
        "toolInput": {"file_path": "/tmp/foo.txt"},
    }


# ── Import guard ───────────────────────────────────────────────────────────────

class TestImport:
    def test_module_importable(self):
        from memory_system.skill_invocation_recorder import process_tool_event  # noqa: F401


# ── process_tool_event — filtering ────────────────────────────────────────────

class TestFiltering:
    def setup_method(self):
        from memory_system.skill_invocation_recorder import process_tool_event
        self.process = process_tool_event

    def test_returns_none_for_non_skill_tool(self, tmp_db, tmp_state):
        result = self.process(_other_payload("Read"), state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_for_write_tool(self, tmp_db, tmp_state):
        result = self.process(_other_payload("Write"), state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_for_bash_tool(self, tmp_db, tmp_state):
        result = self.process(_other_payload("Bash"), state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_for_empty_payload(self, tmp_db, tmp_state):
        result = self.process({}, state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_for_missing_tool_name(self, tmp_db, tmp_state):
        payload = {"sessionId": "sess", "toolInput": {"skill": "foo"}}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_when_tool_input_missing(self, tmp_db, tmp_state):
        payload = {"sessionId": "sess", "toolName": "Skill"}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_when_no_skill_name_in_input(self, tmp_db, tmp_state):
        payload = {"sessionId": "sess", "toolName": "Skill", "toolInput": {"args": "stuff"}}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result is None

    def test_returns_none_for_empty_skill_name(self, tmp_db, tmp_state):
        payload = {"sessionId": "sess", "toolName": "Skill", "toolInput": {"skill": ""}}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result is None


# ── process_tool_event — happy path ───────────────────────────────────────────

class TestHappyPath:
    def setup_method(self):
        from memory_system.skill_invocation_recorder import process_tool_event
        self.process = process_tool_event

    def test_returns_skill_name_on_success(self, tmp_db, tmp_state):
        result = self.process(_skill_payload("reddit-fetch"), state_file=tmp_state, db_path=tmp_db)
        assert result == "reddit-fetch"

    def test_works_with_skill_key(self, tmp_db, tmp_state):
        """Primary key: toolInput["skill"]"""
        payload = {"sessionId": "s1", "toolName": "Skill", "toolInput": {"skill": "seo-audit"}}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result == "seo-audit"

    def test_works_with_name_key_fallback(self, tmp_db, tmp_state):
        """Fallback key: toolInput["name"]"""
        payload = {"sessionId": "s1", "toolName": "Skill", "toolInput": {"name": "copywriter"}}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result == "copywriter"

    def test_prefers_skill_key_over_name_key(self, tmp_db, tmp_state):
        payload = {
            "sessionId": "s1", "toolName": "Skill",
            "toolInput": {"skill": "reddit-fetch", "name": "other"},
        }
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result == "reddit-fetch"

    def test_uses_unknown_session_when_missing(self, tmp_db, tmp_state):
        """Missing sessionId should not crash — defaults to 'unknown'."""
        payload = {"toolName": "Skill", "toolInput": {"skill": "foo"}}
        result = self.process(payload, state_file=tmp_state, db_path=tmp_db)
        assert result == "foo"


# ── DB recording ──────────────────────────────────────────────────────────────

class TestDbRecording:
    def setup_method(self):
        from memory_system.skill_invocation_recorder import process_tool_event
        self.process = process_tool_event

    def test_records_provenance_row(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        self.process(_skill_payload("reddit-fetch", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        history = tracker.get_history("reddit-fetch")
        assert len(history) == 1
        assert history[0].skill_name == "reddit-fetch"
        assert history[0].session_id == "s1"

    def test_outcome_defaults_to_unknown(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        self.process(_skill_payload("seo-audit", session_id="s2"), state_file=tmp_state, db_path=tmp_db)
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        history = tracker.get_history("seo-audit")
        assert history[0].outcome == "unknown"

    def test_context_snippet_from_args(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        self.process(
            _skill_payload("my-skill", args="Run a full site audit"),
            state_file=tmp_state, db_path=tmp_db,
        )
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        history = tracker.get_history("my-skill")
        assert "Run a full site audit" in history[0].context_snippet

    def test_multiple_calls_create_multiple_rows(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        self.process(_skill_payload("foo", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        self.process(_skill_payload("foo", session_id="s2"), state_file=tmp_state, db_path=tmp_db)
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        history = tracker.get_history("foo")
        assert len(history) == 2

    def test_different_skills_recorded_separately(self, tmp_db, tmp_state):
        from memory_system.skill_provenance import SkillProvenanceTracker
        self.process(_skill_payload("skillA", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        self.process(_skill_payload("skillB", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        tracker = SkillProvenanceTracker(db_path=tmp_db)
        assert len(tracker.get_history("skillA")) == 1
        assert len(tracker.get_history("skillB")) == 1


# ── Hook state — active_skills ────────────────────────────────────────────────

class TestHookState:
    def setup_method(self):
        from memory_system.skill_invocation_recorder import process_tool_event
        self.process = process_tool_event

    def test_appends_to_active_skills(self, tmp_db, tmp_state):
        from memory_system.hook_state import get_session_state
        self.process(_skill_payload("reddit-fetch", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        state = get_session_state(session_id="s1", state_file=tmp_state)
        assert "reddit-fetch" in state["active_skills"]

    def test_accumulates_multiple_skills(self, tmp_db, tmp_state):
        from memory_system.hook_state import get_session_state
        self.process(_skill_payload("skillA", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        self.process(_skill_payload("skillB", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        state = get_session_state(session_id="s1", state_file=tmp_state)
        assert "skillA" in state["active_skills"]
        assert "skillB" in state["active_skills"]

    def test_no_duplicate_in_active_skills(self, tmp_db, tmp_state):
        """Same skill invoked twice should appear only once in active_skills."""
        from memory_system.hook_state import get_session_state
        self.process(_skill_payload("reddit-fetch", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        self.process(_skill_payload("reddit-fetch", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        state = get_session_state(session_id="s1", state_file=tmp_state)
        assert state["active_skills"].count("reddit-fetch") == 1

    def test_different_sessions_tracked_independently(self, tmp_db, tmp_state):
        from memory_system.hook_state import get_session_state
        self.process(_skill_payload("foo", session_id="s1"), state_file=tmp_state, db_path=tmp_db)
        self.process(_skill_payload("bar", session_id="s2"), state_file=tmp_state, db_path=tmp_db)
        s1 = get_session_state(session_id="s1", state_file=tmp_state)
        s2 = get_session_state(session_id="s2", state_file=tmp_state)
        assert s1["active_skills"] == ["foo"]
        assert s2["active_skills"] == ["bar"]

    def test_unknown_session_id_uses_fallback_key(self, tmp_db, tmp_state):
        """When sessionId is absent, state stored under 'unknown' key."""
        from memory_system.hook_state import get_session_state
        payload = {"toolName": "Skill", "toolInput": {"skill": "foo"}}
        self.process(payload, state_file=tmp_state, db_path=tmp_db)
        state = get_session_state(session_id="unknown", state_file=tmp_state)
        assert "foo" in state["active_skills"]
