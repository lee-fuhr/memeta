"""
Tests for session summary module — "Where was I?" resumption cards.

Covers:
- get_summaries_dir() path resolution and creation
- generate_summary() heuristic extraction from JSONL transcripts
- save_summary() atomic writes with .tmp + rename
- load_summary() with valid, missing, and corrupt files
- get_latest_summary() scanning by generated_at timestamp
- format_resumption_card() human-readable output
- cleanup_old_summaries() age-based pruning
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memory_system.session_summary import (
    DEFAULT_SUMMARIES_DIR,
    MAX_FILES_TRACKED,
    MAX_SUMMARY_LENGTH,
    cleanup_old_summaries,
    format_resumption_card,
    generate_summary,
    get_latest_summary,
    get_summaries_dir,
    load_summary,
    save_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_transcript_line(role: str, content, msg_type: str = None) -> str:
    """Build a single JSONL line mimicking Claude session transcript format."""
    if role == "human":
        obj = {"type": "human", "message": {"content": content}}
    elif role == "assistant":
        if isinstance(content, str):
            # Simple text-only assistant message
            obj = {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": content}],
                },
            }
        elif isinstance(content, list):
            # Pre-built content blocks (e.g., mix of text + tool_use)
            obj = {"type": "assistant", "message": {"content": content}}
        else:
            raise ValueError(f"Unexpected content type: {type(content)}")
    else:
        raise ValueError(f"Unknown role: {role}")
    return json.dumps(obj)


def _build_transcript(lines: list[str]) -> str:
    """Join JSONL lines with newlines."""
    return "\n".join(lines)


def _make_summary(
    session_id: str = "test-session-abc",
    summary: str = "Worked on session summary module.",
    open_questions: list[str] | None = None,
    files_touched: list[str] | None = None,
    generated_at: str | None = None,
) -> dict:
    """Build a well-formed summary dict for tests."""
    return {
        "session_id": session_id,
        "summary": summary,
        "open_questions": open_questions or [],
        "files_touched": files_touched or [],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# TestGetSummariesDir
# ---------------------------------------------------------------------------

class TestGetSummariesDir:
    def test_returns_default_path(self):
        result = get_summaries_dir()
        assert result == DEFAULT_SUMMARIES_DIR
        assert isinstance(result, Path)

    def test_creates_directory(self, tmp_path):
        target = tmp_path / "summaries"
        assert not target.exists()
        result = get_summaries_dir(target)
        assert result == target
        assert target.is_dir()


# ---------------------------------------------------------------------------
# TestGenerateSummary
# ---------------------------------------------------------------------------

class TestGenerateSummary:
    def test_extracts_summary_from_transcript(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Let's refactor the config module."),
            _make_transcript_line("assistant", "I'll restructure the config to use dataclasses."),
            _make_transcript_line("human", "Looks good. Also fix the imports."),
            _make_transcript_line("assistant", "Done. I've updated all import paths."),
        ])
        result = generate_summary(transcript, session_id="sess-001")
        assert "summary" in result
        assert len(result["summary"]) > 0
        assert result["session_id"] == "sess-001"

    def test_extracts_open_questions(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Should we use SQLite or JSON for storage?"),
            _make_transcript_line("assistant", "Good question. Let me think about that."),
            _make_transcript_line("human", "TODO: benchmark both approaches."),
            _make_transcript_line("assistant", "We need to decide on the schema first."),
        ])
        result = generate_summary(transcript)
        assert len(result["open_questions"]) > 0
        # Should find the question mark line and the TODO
        found_question = any("SQLite" in q or "storage" in q for q in result["open_questions"])
        found_todo = any("benchmark" in q.lower() for q in result["open_questions"])
        assert found_question or found_todo

    def test_extracts_files_touched(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Edit /Users/lee/project/src/config.py"),
            _make_transcript_line("assistant", "I updated src/config.py and tests/test_config.py"),
            _make_transcript_line("human", "Check the README.md too"),
        ])
        result = generate_summary(transcript)
        assert len(result["files_touched"]) > 0
        paths = result["files_touched"]
        assert any("config.py" in p for p in paths)

    def test_handles_empty_transcript(self):
        result = generate_summary("")
        assert result["summary"] == ""
        assert result["open_questions"] == []
        assert result["files_touched"] == []

    def test_handles_tool_only_transcript(self):
        """Transcript with only tool_use blocks should produce empty summary."""
        tool_content = [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/foo.py"}},
        ]
        transcript = _build_transcript([
            _make_transcript_line("assistant", tool_content),
        ])
        result = generate_summary(transcript)
        # Summary should be empty or very short since no substantive text
        assert len(result["summary"]) <= MAX_SUMMARY_LENGTH

    def test_truncates_long_summary(self):
        # Build a transcript with very long messages
        long_msg = "This is a detailed explanation. " * 100
        transcript = _build_transcript([
            _make_transcript_line("human", long_msg),
            _make_transcript_line("assistant", long_msg),
        ])
        result = generate_summary(transcript)
        assert len(result["summary"]) <= MAX_SUMMARY_LENGTH

    def test_limits_files_touched(self):
        # Mention more than MAX_FILES_TRACKED file paths
        lines = []
        for i in range(20):
            lines.append(
                _make_transcript_line("human", f"Edit /Users/lee/project/file{i}.py")
            )
        transcript = _build_transcript(lines)
        result = generate_summary(transcript)
        assert len(result["files_touched"]) <= MAX_FILES_TRACKED

    def test_includes_generated_at(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Hello"),
        ])
        before = datetime.now(timezone.utc).isoformat()
        result = generate_summary(transcript)
        after = datetime.now(timezone.utc).isoformat()
        assert "generated_at" in result
        assert before <= result["generated_at"] <= after

    def test_generates_session_id_when_none(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Hello"),
        ])
        result = generate_summary(transcript, session_id=None)
        assert result["session_id"] is not None
        assert len(result["session_id"]) > 0

    def test_truncates_huge_transcript(self):
        """Transcripts larger than MAX_TRANSCRIPT_BYTES are tail-truncated."""
        # Build a transcript that exceeds the 2 MB limit
        lines = []
        for i in range(5000):
            lines.append(
                _make_transcript_line("human", f"Message number {i} " + "x" * 400)
            )
        transcript = _build_transcript(lines)
        assert len(transcript) > 2 * 1024 * 1024, "Test needs transcript > 2 MB"

        result = generate_summary(transcript, session_id="huge-sess")
        # Should still produce a valid summary (not crash or OOM)
        assert result["session_id"] == "huge-sess"
        assert isinstance(result["summary"], str)
        assert isinstance(result["open_questions"], list)
        assert isinstance(result["files_touched"], list)


# ---------------------------------------------------------------------------
# TestSaveSummary
# ---------------------------------------------------------------------------

class TestSaveSummary:
    def test_saves_valid_json(self, tmp_path):
        summary = _make_summary()
        path = save_summary(summary, session_id="sess-save", summaries_dir=tmp_path)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["session_id"] == "test-session-abc"
        assert loaded["summary"] == summary["summary"]

    def test_atomic_write(self, tmp_path):
        """No .tmp file should remain after save completes."""
        summary = _make_summary()
        save_summary(summary, session_id="sess-atomic", summaries_dir=tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        summary = _make_summary()
        path = save_summary(summary, session_id="sess-nested", summaries_dir=nested)
        assert path.exists()
        assert nested.is_dir()

    def test_custom_path(self, tmp_path):
        custom_dir = tmp_path / "custom-summaries"
        summary = _make_summary()
        path = save_summary(summary, session_id="sess-custom", summaries_dir=custom_dir)
        assert path.parent == custom_dir
        assert path.name == "sess-custom.json"


# ---------------------------------------------------------------------------
# TestLoadSummary
# ---------------------------------------------------------------------------

class TestLoadSummary:
    def test_loads_valid_summary(self, tmp_path):
        summary = _make_summary(session_id="sess-load")
        save_summary(summary, session_id="sess-load", summaries_dir=tmp_path)
        loaded = load_summary("sess-load", summaries_dir=tmp_path)
        assert loaded is not None
        assert loaded["session_id"] == "sess-load"

    def test_returns_none_missing(self, tmp_path):
        result = load_summary("nonexistent-session", summaries_dir=tmp_path)
        assert result is None

    def test_returns_none_corrupt(self, tmp_path):
        corrupt_file = tmp_path / "corrupt-sess.json"
        corrupt_file.write_text("{{{{not json at all!!!!")
        result = load_summary("corrupt-sess", summaries_dir=tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# TestGetLatestSummary
# ---------------------------------------------------------------------------

class TestGetLatestSummary:
    def test_returns_newest(self, tmp_path):
        old = _make_summary(
            session_id="old",
            generated_at="2025-01-01T00:00:00+00:00",
        )
        new = _make_summary(
            session_id="new",
            summary="Latest work",
            generated_at="2026-02-28T12:00:00+00:00",
        )
        save_summary(old, session_id="old", summaries_dir=tmp_path)
        save_summary(new, session_id="new", summaries_dir=tmp_path)
        latest = get_latest_summary(summaries_dir=tmp_path)
        assert latest is not None
        assert latest["session_id"] == "new"

    def test_returns_none_empty_dir(self, tmp_path):
        result = get_latest_summary(summaries_dir=tmp_path)
        assert result is None

    def test_handles_multiple_summaries(self, tmp_path):
        """Correctly picks newest from 5+ summaries."""
        for i in range(5):
            ts = f"2026-01-{10 + i:02d}T00:00:00+00:00"
            s = _make_summary(session_id=f"sess-{i}", generated_at=ts)
            save_summary(s, session_id=f"sess-{i}", summaries_dir=tmp_path)
        latest = get_latest_summary(summaries_dir=tmp_path)
        assert latest["session_id"] == "sess-4"


# ---------------------------------------------------------------------------
# TestFormatResumptionCard
# ---------------------------------------------------------------------------

class TestFormatResumptionCard:
    def test_formats_complete_card(self):
        summary = _make_summary(
            session_id="abc123def456",
            summary="Refactored config module to use dataclasses.",
            open_questions=["Should we add env var support?", "Need to benchmark."],
            files_touched=["src/config.py", "tests/test_config.py"],
            generated_at="2026-02-28T10:30:00+00:00",
        )
        card = format_resumption_card(summary)
        assert "# Project state" in card
        assert "abc123def456" in card
        assert "Refactored config" in card
        assert "env var" in card
        assert "benchmark" in card

    def test_handles_empty_fields(self):
        summary = _make_summary(
            summary="",
            open_questions=[],
            files_touched=[],
        )
        card = format_resumption_card(summary)
        assert isinstance(card, str)
        assert "# Project state" in card
        # Should not crash on empty fields

    def test_includes_session_id(self):
        summary = _make_summary(session_id="session-xyz-789012")
        card = format_resumption_card(summary)
        # Should include truncated session_id
        assert "session-xyz-" in card


# ---------------------------------------------------------------------------
# TestCleanupOldSummaries
# ---------------------------------------------------------------------------

class TestCleanupOldSummaries:
    def test_removes_old_files(self, tmp_path):
        # Create a file with old timestamp
        old_summary = _make_summary(
            session_id="old-sess",
            generated_at="2020-01-01T00:00:00+00:00",
        )
        path = save_summary(old_summary, session_id="old-sess", summaries_dir=tmp_path)
        # Set mtime to 60 days ago
        old_time = time.time() - (60 * 86400)
        os.utime(path, (old_time, old_time))
        removed = cleanup_old_summaries(summaries_dir=tmp_path, max_age_days=30)
        assert removed >= 1
        assert not path.exists()

    def test_keeps_recent_files(self, tmp_path):
        recent = _make_summary(session_id="recent-sess")
        path = save_summary(recent, session_id="recent-sess", summaries_dir=tmp_path)
        removed = cleanup_old_summaries(summaries_dir=tmp_path, max_age_days=30)
        assert removed == 0
        assert path.exists()

    def test_returns_count(self, tmp_path):
        # Create 3 old files
        for i in range(3):
            s = _make_summary(session_id=f"old-{i}")
            p = save_summary(s, session_id=f"old-{i}", summaries_dir=tmp_path)
            old_time = time.time() - (60 * 86400)
            os.utime(p, (old_time, old_time))
        # Create 2 recent files
        for i in range(2):
            s = _make_summary(session_id=f"recent-{i}")
            save_summary(s, session_id=f"recent-{i}", summaries_dir=tmp_path)

        removed = cleanup_old_summaries(summaries_dir=tmp_path, max_age_days=30)
        assert removed == 3
        # 2 recent files should remain
        remaining = list(tmp_path.glob("*.json"))
        assert len(remaining) == 2
