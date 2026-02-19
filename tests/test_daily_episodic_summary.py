"""
Tests for daily_episodic_summary.py — daily YYYY-MM-DD.md summary generation.

Covers:
1. Generate summary with mocked API — file created with LLM content
2. Generate summary with no sessions — graceful "No sessions today."
3. Generate summary with API failure — fallback message written
4. load_recent() with no files — returns empty string
5. load_recent() with existing files — returns concatenated content
6. Date parameter works correctly
7. Output directory auto-created if missing
8. Multiple sessions are aggregated
9. Content is capped at 6000 chars
10. load_daily_context() convenience function
11. load_recent() with partial days
12. generate() overwrites existing file
"""

import json
import os
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memory_system.daily_episodic_summary import (
    DailyEpisodicSummary,
    load_daily_context,
    MAX_CONTENT_CHARS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_output_dir(tmp_path):
    """Temporary directory for summary output files."""
    d = tmp_path / "daily-summaries"
    d.mkdir()
    return d


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary session-history SQLite database with schema."""
    db_path = str(tmp_path / "session-history.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            name TEXT,
            full_transcript_json TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            memories_extracted INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            project_id TEXT DEFAULT 'LFI',
            session_quality REAL DEFAULT 0.0,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)
    conn.commit()
    conn.close()
    return db_path


def _insert_session(db_path: str, session_id: str, ts: int, name: str, messages: list):
    """Helper: insert a session row into the temp DB."""
    transcript_json = json.dumps(messages)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO sessions (id, timestamp, name, full_transcript_json, message_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, ts, name, transcript_json, len(messages)),
    )
    conn.commit()
    conn.close()


def _ts_for_date(d: date, hour: int = 12) -> int:
    """Return a unix timestamp for the given date at the given hour."""
    return int(datetime(d.year, d.month, d.day, hour, 0, 0).timestamp())


# ---------------------------------------------------------------------------
# 1. Generate summary with mocked API — file created
# ---------------------------------------------------------------------------

class TestGenerateWithMockedAPI:

    def test_generate_creates_file_with_llm_content(self, tmp_output_dir, tmp_db):
        """generate() creates a YYYY-MM-DD.md file with LLM summary content."""
        today = date.today()
        _insert_session(
            tmp_db, "s1", _ts_for_date(today), "Test session",
            [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there"}],
        )

        with patch("memory_system.daily_episodic_summary.ask_claude", return_value="Summary of work done today."):
            summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
            path = summary.generate(target_date=today)

        assert path.exists()
        content = path.read_text()
        assert today.isoformat() in content
        assert "Summary of work done today." in content


# ---------------------------------------------------------------------------
# 2. Generate summary with no sessions
# ---------------------------------------------------------------------------

class TestGenerateNoSessions:

    def test_generate_no_sessions_writes_placeholder(self, tmp_output_dir, tmp_db):
        """generate() writes 'No sessions today.' when DB has no sessions for the date."""
        target = date(2025, 6, 15)
        summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
        path = summary.generate(target_date=target)

        assert path.exists()
        content = path.read_text()
        assert "No sessions today." in content
        assert "2025-06-15" in content


# ---------------------------------------------------------------------------
# 3. Generate summary with API failure
# ---------------------------------------------------------------------------

class TestGenerateAPIFailure:

    def test_generate_api_failure_writes_fallback(self, tmp_output_dir, tmp_db):
        """generate() writes fallback message when LLM call fails."""
        today = date.today()
        _insert_session(
            tmp_db, "s-fail", _ts_for_date(today), "Fail session",
            [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}],
        )

        with patch("memory_system.daily_episodic_summary.ask_claude", side_effect=RuntimeError("API down")):
            summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
            path = summary.generate(target_date=today)

        content = path.read_text()
        assert "Summary unavailable:" in content


# ---------------------------------------------------------------------------
# 4. load_recent() with no files
# ---------------------------------------------------------------------------

class TestLoadRecentNoFiles:

    def test_load_recent_no_files_returns_empty(self, tmp_output_dir):
        """load_recent() returns empty string when no summary files exist."""
        summary = DailyEpisodicSummary(output_dir=tmp_output_dir)
        result = summary.load_recent(days=2)
        assert result == ""

    def test_load_recent_nonexistent_dir_returns_empty(self, tmp_path):
        """load_recent() returns empty string when output_dir doesn't exist."""
        missing = tmp_path / "does-not-exist"
        summary = DailyEpisodicSummary(output_dir=missing)
        result = summary.load_recent(days=2)
        assert result == ""


# ---------------------------------------------------------------------------
# 5. load_recent() with existing files
# ---------------------------------------------------------------------------

class TestLoadRecentWithFiles:

    def test_load_recent_returns_both_days(self, tmp_output_dir):
        """load_recent(days=2) returns content from both days when files exist."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        day_before = today - timedelta(days=2)

        (tmp_output_dir / f"{yesterday.isoformat()}.md").write_text("# Yesterday\n\nDid stuff.\n")
        (tmp_output_dir / f"{day_before.isoformat()}.md").write_text("# Day before\n\nAlso did stuff.\n")

        summary = DailyEpisodicSummary(output_dir=tmp_output_dir)
        result = summary.load_recent(days=2)

        assert "Yesterday" in result
        assert "Day before" in result
        # Older day should come first (chronological order)
        assert result.index("Day before") < result.index("Yesterday")


# ---------------------------------------------------------------------------
# 6. Date parameter works correctly
# ---------------------------------------------------------------------------

class TestDateParameter:

    def test_generate_specific_date(self, tmp_output_dir, tmp_db):
        """generate(date=...) creates file named for that date."""
        target = date(2025, 3, 14)
        _insert_session(
            tmp_db, "s-pi", _ts_for_date(target), "Pi day session",
            [{"role": "user", "content": "What is pi?"}, {"role": "assistant", "content": "3.14159..."}],
        )

        with patch("memory_system.daily_episodic_summary.ask_claude", return_value="Discussed pi."):
            summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
            path = summary.generate(target_date=target)

        assert path.name == "2025-03-14.md"
        assert "2025-03-14" in path.read_text()

    def test_generate_defaults_to_today(self, tmp_output_dir, tmp_db):
        """generate() without date argument defaults to today."""
        today = date.today()
        # No sessions for today => "No sessions today." placeholder
        summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
        path = summary.generate()
        assert path.name == f"{today.isoformat()}.md"


# ---------------------------------------------------------------------------
# 7. Output directory auto-created if missing
# ---------------------------------------------------------------------------

class TestOutputDirAutoCreation:

    def test_generate_creates_output_dir(self, tmp_path, tmp_db):
        """generate() creates output_dir if it doesn't exist."""
        missing = tmp_path / "auto" / "nested" / "summaries"
        assert not missing.exists()

        summary = DailyEpisodicSummary(output_dir=missing, db_path=tmp_db)
        path = summary.generate()

        assert missing.exists()
        assert path.exists()


# ---------------------------------------------------------------------------
# 8. Multiple sessions are aggregated
# ---------------------------------------------------------------------------

class TestMultipleSessionAggregation:

    def test_multiple_sessions_aggregated(self, tmp_output_dir, tmp_db):
        """generate() aggregates content from multiple sessions on the same day."""
        target = date(2025, 7, 4)
        _insert_session(
            tmp_db, "s-morning", _ts_for_date(target, 9), "Morning session",
            [{"role": "user", "content": "Working on feature A"}, {"role": "assistant", "content": "Done."}],
        )
        _insert_session(
            tmp_db, "s-afternoon", _ts_for_date(target, 14), "Afternoon session",
            [{"role": "user", "content": "Working on feature B"}, {"role": "assistant", "content": "Done."}],
        )

        captured_prompt = {}

        def fake_ask(prompt, **kwargs):
            captured_prompt["text"] = prompt
            return "Worked on features A and B."

        with patch("memory_system.daily_episodic_summary.ask_claude", side_effect=fake_ask):
            summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
            path = summary.generate(target_date=target)

        # Both sessions should appear in the prompt sent to LLM
        prompt_text = captured_prompt["text"]
        assert "Morning session" in prompt_text
        assert "Afternoon session" in prompt_text


# ---------------------------------------------------------------------------
# 9. Content is capped at 6000 chars
# ---------------------------------------------------------------------------

class TestContentCap:

    def test_content_capped_at_max(self, tmp_output_dir, tmp_db):
        """Session content sent to LLM is capped at MAX_CONTENT_CHARS."""
        target = date(2025, 8, 1)
        # Create a session with very long content
        big_content = "x" * 10000
        _insert_session(
            tmp_db, "s-big", _ts_for_date(target), "Big session",
            [{"role": "user", "content": big_content}],
        )

        captured_prompt = {}

        def fake_ask(prompt, **kwargs):
            captured_prompt["text"] = prompt
            return "Summary."

        with patch("memory_system.daily_episodic_summary.ask_claude", side_effect=fake_ask):
            summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
            summary.generate(target_date=target)

        # The sessions content portion in the prompt should be capped
        # The prompt template adds text around it, but the session content
        # portion passed to the template should not exceed MAX_CONTENT_CHARS
        prompt_text = captured_prompt["text"]
        # Find everything after "Sessions:\n"
        sessions_idx = prompt_text.index("Sessions:\n") + len("Sessions:\n")
        session_content = prompt_text[sessions_idx:]
        assert len(session_content) <= MAX_CONTENT_CHARS


# ---------------------------------------------------------------------------
# 10. load_daily_context() convenience function
# ---------------------------------------------------------------------------

class TestLoadDailyContext:

    def test_load_daily_context_calls_load_recent(self, tmp_path):
        """load_daily_context() delegates to DailyEpisodicSummary.load_recent(days=2)."""
        with patch("memory_system.daily_episodic_summary.DailyEpisodicSummary.load_recent", return_value="context data") as mock_lr:
            result = load_daily_context()
        mock_lr.assert_called_once_with(days=2)
        assert result == "context data"


# ---------------------------------------------------------------------------
# 11. load_recent() with partial days
# ---------------------------------------------------------------------------

class TestLoadRecentPartialDays:

    def test_load_recent_only_one_day_exists(self, tmp_output_dir):
        """load_recent(days=3) works when only 1 of 3 days has a file."""
        yesterday = date.today() - timedelta(days=1)
        (tmp_output_dir / f"{yesterday.isoformat()}.md").write_text("# Yesterday\n\nWork done.\n")

        summary = DailyEpisodicSummary(output_dir=tmp_output_dir)
        result = summary.load_recent(days=3)

        assert "Yesterday" in result
        assert "Work done." in result


# ---------------------------------------------------------------------------
# 12. generate() overwrites existing file
# ---------------------------------------------------------------------------

class TestGenerateOverwrite:

    def test_generate_overwrites_existing_file(self, tmp_output_dir, tmp_db):
        """generate() overwrites an existing summary file for the same date."""
        target = date(2025, 9, 1)

        # Write an old summary
        old_path = tmp_output_dir / f"{target.isoformat()}.md"
        old_path.write_text("# Old summary\n\nOld content.\n")

        # No sessions => writes "No sessions today."
        summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
        path = summary.generate(target_date=target)

        content = path.read_text()
        assert "Old content." not in content
        assert "No sessions today." in content


# ---------------------------------------------------------------------------
# 13. Database connection error handled gracefully
# ---------------------------------------------------------------------------

class TestDBError:

    def test_generate_with_bad_db_path(self, tmp_output_dir):
        """generate() handles database errors gracefully (no sessions found)."""
        summary = DailyEpisodicSummary(
            output_dir=tmp_output_dir,
            db_path="/nonexistent/path/to.db",
        )
        path = summary.generate()
        assert path.exists()
        assert "No sessions today." in path.read_text()


# ---------------------------------------------------------------------------
# 14. Empty LLM response triggers fallback
# ---------------------------------------------------------------------------

class TestEmptyLLMResponse:

    def test_empty_llm_response_triggers_fallback(self, tmp_output_dir, tmp_db):
        """generate() treats empty LLM response as failure and writes fallback."""
        today = date.today()
        _insert_session(
            tmp_db, "s-empty-resp", _ts_for_date(today), "Session",
            [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}],
        )

        with patch("memory_system.daily_episodic_summary.ask_claude", return_value=""):
            summary = DailyEpisodicSummary(output_dir=tmp_output_dir, db_path=tmp_db)
            path = summary.generate(target_date=today)

        content = path.read_text()
        assert "Summary unavailable:" in content


# ---------------------------------------------------------------------------
# 15. load_daily_context() exists in session_consolidator
# ---------------------------------------------------------------------------

class TestSessionConsolidatorIntegration:

    def test_load_daily_context_importable_from_session_consolidator(self):
        """load_daily_context() is importable from session_consolidator module."""
        from memory_system.session_consolidator import load_daily_context as sc_ldc
        assert callable(sc_ldc)

    def test_load_daily_context_in_session_consolidator_delegates(self):
        """load_daily_context() in session_consolidator delegates to DailyEpisodicSummary."""
        with patch(
            "memory_system.daily_episodic_summary.DailyEpisodicSummary.load_recent",
            return_value="delegated content",
        ) as mock_lr:
            from memory_system.session_consolidator import load_daily_context as sc_ldc
            result = sc_ldc(days=3)
        mock_lr.assert_called_once_with(days=3)
        assert result == "delegated content"
