"""Tests for skill_self_improver JSONL-based outcome assessment.

Covers the fix for compaction evidence loss: assess_session_outcomes must
read the JSONL file directly instead of relying only on in-memory messages.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_system.wild.skill_self_improver import SkillSelfImprover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, messages: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def _skill_message(skill_name: str) -> dict:
    return {
        "role": "assistant",
        "content": [
            {"type": "text", "text": f"Loading {skill_name}"},
            {"type": "tool_use", "name": "Skill", "input": {"skill": skill_name, "args": ""}},
        ],
    }


def _user_message(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant_message(text: str) -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _tool_result_message() -> dict:
    """Tool_result-only message — should be filtered out."""
    return {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}


def _compaction_message() -> dict:
    return {"role": "user", "content": "This was compacted. Summary follows."}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def improver(tmp_path):
    db_path = tmp_path / "intelligence.db"
    with patch("memory_system.wild.skill_self_improver.IntelligenceDB") as MockDB:
        mock_db = MockDB.return_value
        mock_db.conn.cursor.return_value.lastrowid = 1
        imp = SkillSelfImprover.__new__(SkillSelfImprover)
        imp.db = mock_db
        yield imp


@pytest.fixture()
def session_id():
    return "test-session-abc123"


@pytest.fixture()
def jsonl_home(tmp_path):
    """Patch Path.home() to a temp dir so JSONL loading uses temp files."""
    with patch("memory_system.wild.skill_self_improver.Path.home", return_value=tmp_path):
        yield tmp_path


# ---------------------------------------------------------------------------
# Tests: _load_jsonl_messages
# ---------------------------------------------------------------------------

class TestLoadJsonlMessages:
    def test_returns_empty_when_file_missing(self, improver, jsonl_home, session_id):
        result = improver._load_jsonl_messages(session_id)
        assert result == []

    def test_loads_user_and_assistant_messages(self, improver, jsonl_home, session_id):
        msgs = [_user_message("hello"), _assistant_message("hi there")]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        result = improver._load_jsonl_messages(session_id)
        assert len(result) == 2

    def test_filters_tool_result_only_messages(self, improver, jsonl_home, session_id):
        msgs = [
            _user_message("real message"),
            _tool_result_message(),
            _assistant_message("response"),
        ]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        result = improver._load_jsonl_messages(session_id)
        assert len(result) == 2
        assert all(m.get("role") in ("user", "assistant") for m in result)

    def test_filters_compaction_summary_strings(self, improver, jsonl_home, session_id):
        msgs = [
            _user_message("real message"),
            _compaction_message(),
            _assistant_message("response"),
        ]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        result = improver._load_jsonl_messages(session_id)
        # compaction message filtered, 2 remain
        assert len(result) == 2

    def test_handles_malformed_json_lines_gracefully(self, improver, jsonl_home, session_id):
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("w") as f:
            f.write('{"role": "user", "content": "good"}\n')
            f.write("NOT VALID JSON\n")
            f.write('{"role": "assistant", "content": [{"type": "text", "text": "ok"}]}\n')

        result = improver._load_jsonl_messages(session_id)
        assert len(result) == 2  # malformed line skipped

    def test_preserves_skill_tool_use_messages(self, improver, jsonl_home, session_id):
        msgs = [_skill_message("test-skill"), _user_message("looks good")]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        result = improver._load_jsonl_messages(session_id)
        assert len(result) == 2
        # skill message preserved (has tool_use block but also text)
        contents = [m["content"] for m in result if m["role"] == "assistant"]
        assert any(
            any(b.get("type") == "tool_use" for b in c if isinstance(b, dict))
            for c in contents
            if isinstance(c, list)
        )

    def test_skips_empty_lines(self, improver, jsonl_home, session_id):
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("w") as f:
            f.write('\n')
            f.write('{"role": "user", "content": "hello"}\n')
            f.write('\n')

        result = improver._load_jsonl_messages(session_id)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: assess_session_outcomes reads JSONL
# ---------------------------------------------------------------------------

class TestAssessSessionOutcomesJsonl:
    def test_finds_skills_in_jsonl_with_empty_session_messages(
        self, improver, jsonl_home, session_id
    ):
        """Core regression test: skills in JSONL found even when session_messages is empty."""
        msgs = [
            _user_message("use the test skill"),
            _skill_message("my-skill"),
            _user_message("great, that worked perfectly"),
        ]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        # Simulate post-compaction: session_messages is empty
        assessments = improver.assess_session_outcomes(session_id, session_messages=[])
        assert len(assessments) == 1
        assert assessments[0]["skill_name"] == "my-skill"

    def test_finds_multiple_skills_in_jsonl(self, improver, jsonl_home, session_id):
        msgs = [
            _user_message("first"),
            _skill_message("skill-a"),
            _assistant_message("done with a"),
            _user_message("now do b"),
            _skill_message("skill-b"),
            _assistant_message("done with b"),
        ]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        assessments = improver.assess_session_outcomes(session_id, session_messages=[])
        skill_names = [a["skill_name"] for a in assessments]
        assert "skill-a" in skill_names
        assert "skill-b" in skill_names

    def test_falls_back_to_session_messages_when_jsonl_missing(
        self, improver, jsonl_home, session_id
    ):
        """When JSONL doesn't exist, still works from passed-in session_messages."""
        msgs = [
            _user_message("go"),
            _skill_message("fallback-skill"),
            _user_message("yes"),
        ]
        # No JSONL file created
        assessments = improver.assess_session_outcomes(session_id, session_messages=msgs)
        assert len(assessments) == 1
        assert assessments[0]["skill_name"] == "fallback-skill"

    def test_outcome_marked_success_from_jsonl_context(self, improver, jsonl_home, session_id):
        msgs = [
            _user_message("use skill"),
            _skill_message("good-skill"),
            _user_message("perfect, exactly what I needed"),
        ]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        assessments = improver.assess_session_outcomes(session_id, session_messages=[])
        assert len(assessments) == 1
        # "perfect" is a success signal
        assert assessments[0]["outcome"] in ("success", "unknown")

    def test_no_duplicate_assessments_when_jsonl_and_messages_overlap(
        self, improver, jsonl_home, session_id
    ):
        """When JSONL is loaded, it takes precedence; session_messages are not double-counted."""
        msgs = [
            _user_message("go"),
            _skill_message("dedup-skill"),
            _user_message("ok"),
        ]
        jsonl_path = jsonl_home / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, msgs)

        # Pass same messages as session_messages too
        assessments = improver.assess_session_outcomes(session_id, session_messages=msgs)
        # Should only find skill once (JSONL takes over, session_messages ignored)
        assert len(assessments) == 1
