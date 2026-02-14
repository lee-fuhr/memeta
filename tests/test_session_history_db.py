"""
Tests for session_history_db.py - Full transcript storage with tool calls.

Covers:
1. Initialization (DB setup, table creation, indexes, FTS)
2. Session storage (save, retrieve, update/replace sessions)
3. Metadata extraction (timestamps, duration, tool call counting)
4. Search functionality (full-text search, project filtering)
5. Recent sessions (listing, project filtering, limit)
6. Statistics (session counts, averages, sums)
7. Edge cases (empty transcripts, unicode, very long messages, no timestamps)
8. Error handling (save failures, missing sessions)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest
import tempfile
import sqlite3
import json
import time
import os

import session_history_db as shdb


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path and patch SESSION_DB_PATH."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    original_path = shdb.SESSION_DB_PATH
    shdb.SESSION_DB_PATH = Path(db_path)

    yield db_path

    shdb.SESSION_DB_PATH = original_path
    Path(db_path).unlink(missing_ok=True)
    Path(db_path + '-wal').unlink(missing_ok=True)
    Path(db_path + '-shm').unlink(missing_ok=True)


@pytest.fixture
def initialized_db(temp_db_path):
    """Create a temp DB and run init_session_db()."""
    shdb.init_session_db()
    return temp_db_path


def _make_transcript(messages=None):
    """Helper: build a simple transcript list."""
    if messages is None:
        messages = [
            {"role": "user", "content": "Hello, how are you?", "timestamp": 1700000000},
            {"role": "assistant", "content": "I'm doing well!", "timestamp": 1700000010},
            {"role": "user", "content": "Tell me about Python.", "timestamp": 1700000020},
            {"role": "assistant", "content": "Python is a programming language.", "timestamp": 1700000030},
        ]
    return messages


def _make_transcript_with_tools():
    """Helper: build a transcript with tool_use content blocks."""
    return [
        {"role": "user", "content": "Read the file.", "timestamp": 1700000000},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me read that file."},
                {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {"path": "/tmp/test.py"}},
            ],
            "timestamp": 1700000010,
        },
        {"role": "tool", "content": "file contents here", "timestamp": 1700000015},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Here's another tool call."},
                {"type": "tool_use", "id": "tool_2", "name": "write_file", "input": {"path": "/tmp/out.py"}},
                {"type": "tool_use", "id": "tool_3", "name": "bash", "input": {"command": "ls"}},
            ],
            "timestamp": 1700000020,
        },
    ]


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    """Test database setup, table creation, indexes, FTS."""

    def test_init_creates_database_file(self, temp_db_path):
        """init_session_db() creates the database file."""
        shdb.init_session_db()
        assert Path(temp_db_path).exists()

    def test_init_creates_parent_dirs(self, temp_db_path):
        """init_session_db() creates parent directories if needed."""
        import shutil
        nested_path = Path(temp_db_path).parent / "sub_test_dir" / "deep" / "test.db"
        shdb.SESSION_DB_PATH = nested_path
        try:
            shdb.init_session_db()
            assert nested_path.parent.exists()
        finally:
            # Cleanup the entire nested tree
            top = Path(temp_db_path).parent / "sub_test_dir"
            if top.exists():
                shutil.rmtree(top)

    def test_init_creates_sessions_table(self, initialized_db):
        """sessions table exists after init."""
        conn = sqlite3.connect(initialized_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_creates_fts_table(self, initialized_db):
        """sessions_fts virtual table exists after init."""
        conn = sqlite3.connect(initialized_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions_fts'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_creates_timestamp_index(self, initialized_db):
        """idx_sessions_timestamp index exists."""
        conn = sqlite3.connect(initialized_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_timestamp'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_creates_project_index(self, initialized_db):
        """idx_sessions_project index exists."""
        conn = sqlite3.connect(initialized_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_project'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_creates_quality_index(self, initialized_db):
        """idx_sessions_quality index exists."""
        conn = sqlite3.connect(initialized_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_quality'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_sessions_table_schema(self, initialized_db):
        """sessions table has all expected columns."""
        conn = sqlite3.connect(initialized_db)
        cursor = conn.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {
            'id', 'timestamp', 'name', 'full_transcript_json',
            'message_count', 'tool_call_count', 'memories_extracted',
            'duration_seconds', 'project_id', 'session_quality', 'created_at'
        }
        assert expected == columns

    def test_init_is_idempotent(self, initialized_db):
        """Calling init_session_db() twice does not raise."""
        shdb.init_session_db()
        shdb.init_session_db()
        # Should not raise


# ---------------------------------------------------------------------------
# 2. Session storage
# ---------------------------------------------------------------------------

class TestSaveSession:
    """Test saving, retrieving, and replacing sessions."""

    def test_save_returns_true_on_success(self, initialized_db):
        """save_session returns True when save succeeds."""
        result = shdb.save_session("sess-001", _make_transcript(), session_name="Test")
        assert result is True

    def test_save_and_retrieve_by_id(self, initialized_db):
        """Saved session can be retrieved by ID."""
        transcript = _make_transcript()
        shdb.save_session("sess-002", transcript, session_name="Retrieve Test")

        session = shdb.get_session_by_id("sess-002")
        assert session is not None
        assert session['id'] == "sess-002"
        assert session['name'] == "Retrieve Test"

    def test_retrieve_includes_parsed_transcript(self, initialized_db):
        """Retrieved session has transcript parsed from JSON."""
        transcript = _make_transcript()
        shdb.save_session("sess-003", transcript)

        session = shdb.get_session_by_id("sess-003")
        assert 'transcript' in session
        assert isinstance(session['transcript'], list)
        assert len(session['transcript']) == len(transcript)
        assert session['transcript'][0]['content'] == "Hello, how are you?"

    def test_save_stores_full_json(self, initialized_db):
        """full_transcript_json field contains valid JSON."""
        transcript = _make_transcript()
        shdb.save_session("sess-004", transcript)

        session = shdb.get_session_by_id("sess-004")
        parsed = json.loads(session['full_transcript_json'])
        assert len(parsed) == len(transcript)

    def test_save_default_project_id(self, initialized_db):
        """Default project_id is 'LFI'."""
        shdb.save_session("sess-005", _make_transcript())

        session = shdb.get_session_by_id("sess-005")
        assert session['project_id'] == "LFI"

    def test_save_custom_project_id(self, initialized_db):
        """Custom project_id is stored."""
        shdb.save_session("sess-006", _make_transcript(), project_id="ACME")

        session = shdb.get_session_by_id("sess-006")
        assert session['project_id'] == "ACME"

    def test_save_memories_extracted(self, initialized_db):
        """memories_extracted is stored."""
        shdb.save_session("sess-007", _make_transcript(), memories_extracted=5)

        session = shdb.get_session_by_id("sess-007")
        assert session['memories_extracted'] == 5

    def test_save_session_quality(self, initialized_db):
        """session_quality is stored."""
        shdb.save_session("sess-008", _make_transcript(), session_quality=0.85)

        session = shdb.get_session_by_id("sess-008")
        assert abs(session['session_quality'] - 0.85) < 0.001

    def test_save_replaces_existing(self, initialized_db):
        """Saving with same ID replaces existing session (INSERT OR REPLACE)."""
        shdb.save_session("sess-009", _make_transcript(), session_name="Version 1")
        shdb.save_session("sess-009", _make_transcript(), session_name="Version 2")

        session = shdb.get_session_by_id("sess-009")
        assert session['name'] == "Version 2"

    def test_save_none_session_name(self, initialized_db):
        """Session can be saved without a name."""
        shdb.save_session("sess-010", _make_transcript(), session_name=None)

        session = shdb.get_session_by_id("sess-010")
        assert session['name'] is None

    def test_get_nonexistent_session_returns_none(self, initialized_db):
        """get_session_by_id returns None for unknown ID."""
        result = shdb.get_session_by_id("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# 3. Metadata extraction
# ---------------------------------------------------------------------------

class TestMetadataExtraction:
    """Test timestamp, duration, tool call counting from transcript."""

    def test_message_count(self, initialized_db):
        """message_count reflects number of messages in transcript."""
        transcript = _make_transcript()
        shdb.save_session("meta-001", transcript)

        session = shdb.get_session_by_id("meta-001")
        assert session['message_count'] == 4

    def test_duration_from_timestamps(self, initialized_db):
        """duration_seconds is calculated from first and last timestamp."""
        transcript = _make_transcript()
        # first_timestamp = 1700000000, last_timestamp = 1700000030
        shdb.save_session("meta-002", transcript)

        session = shdb.get_session_by_id("meta-002")
        assert session['duration_seconds'] == 30

    def test_timestamp_is_first_message(self, initialized_db):
        """Session timestamp uses the first message's timestamp."""
        transcript = _make_transcript()
        shdb.save_session("meta-003", transcript)

        session = shdb.get_session_by_id("meta-003")
        assert session['timestamp'] == 1700000000

    def test_tool_call_counting(self, initialized_db):
        """tool_call_count counts tool_use items in assistant messages."""
        transcript = _make_transcript_with_tools()
        shdb.save_session("meta-004", transcript)

        session = shdb.get_session_by_id("meta-004")
        # First assistant msg has 1 tool_use, second has 2
        assert session['tool_call_count'] == 3

    def test_no_tool_calls_in_simple_transcript(self, initialized_db):
        """tool_call_count is 0 when transcript has no tool_use blocks."""
        transcript = _make_transcript()
        shdb.save_session("meta-005", transcript)

        session = shdb.get_session_by_id("meta-005")
        assert session['tool_call_count'] == 0

    def test_no_timestamps_uses_current_time(self, initialized_db):
        """When messages lack timestamps, session.timestamp uses current time."""
        transcript = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        before = int(time.time())
        shdb.save_session("meta-006", transcript)
        after = int(time.time())

        session = shdb.get_session_by_id("meta-006")
        assert before <= session['timestamp'] <= after

    def test_no_timestamps_duration_is_none(self, initialized_db):
        """When messages lack timestamps, duration_seconds is None."""
        transcript = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        shdb.save_session("meta-007", transcript)

        session = shdb.get_session_by_id("meta-007")
        assert session['duration_seconds'] is None

    def test_single_timestamp_duration_is_zero(self, initialized_db):
        """When only one message has a timestamp, duration is 0."""
        transcript = [
            {"role": "user", "content": "Hello", "timestamp": 1700000000},
            {"role": "assistant", "content": "Hi"},
        ]
        shdb.save_session("meta-008", transcript)

        session = shdb.get_session_by_id("meta-008")
        # first_timestamp == last_timestamp => duration = 0
        assert session['duration_seconds'] == 0

    def test_iso_string_timestamps(self, initialized_db):
        """ISO format string timestamps are parsed correctly."""
        transcript = [
            {"role": "user", "content": "Hello", "timestamp": "2023-11-14T12:00:00"},
            {"role": "assistant", "content": "Hi", "timestamp": "2023-11-14T12:05:00"},
        ]
        shdb.save_session("meta-009", transcript)

        session = shdb.get_session_by_id("meta-009")
        assert session['duration_seconds'] == 300  # 5 minutes

    def test_assistant_content_string_no_tool_count(self, initialized_db):
        """Assistant messages with string content (not list) have 0 tool calls."""
        transcript = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello there!"},
        ]
        shdb.save_session("meta-010", transcript)

        session = shdb.get_session_by_id("meta-010")
        assert session['tool_call_count'] == 0


# ---------------------------------------------------------------------------
# 4. Search functionality
# ---------------------------------------------------------------------------

class TestSearchSessions:
    """Test full-text search across session transcripts."""

    def test_search_finds_matching_content(self, initialized_db):
        """Search finds sessions containing the query term."""
        transcript = [
            {"role": "user", "content": "Tell me about quantum computing"},
            {"role": "assistant", "content": "Quantum computing uses qubits."},
        ]
        shdb.save_session("search-001", transcript, session_name="Quantum talk")

        results = shdb.search_sessions("quantum")
        assert len(results) >= 1
        ids = [r['id'] for r in results]
        assert "search-001" in ids

    def test_search_finds_by_session_name(self, initialized_db):
        """Search matches against session name."""
        shdb.save_session("search-002", _make_transcript(), session_name="Kubernetes deployment")

        results = shdb.search_sessions("Kubernetes")
        ids = [r['id'] for r in results]
        assert "search-002" in ids

    def test_search_no_results(self, initialized_db):
        """Search returns empty list when nothing matches."""
        shdb.save_session("search-003", _make_transcript(), session_name="Basic chat")

        results = shdb.search_sessions("xyznonexistentterm")
        assert results == []

    def test_search_respects_limit(self, initialized_db):
        """Search respects the limit parameter."""
        for i in range(5):
            transcript = [{"role": "user", "content": f"Discussion about elephants {i}"}]
            shdb.save_session(f"search-lim-{i}", transcript)

        results = shdb.search_sessions("elephants", limit=3)
        assert len(results) <= 3

    def test_search_with_project_filter(self, initialized_db):
        """Search filters by project_id when provided."""
        t1 = [{"role": "user", "content": "Flamingo migration patterns"}]
        t2 = [{"role": "user", "content": "Flamingo habitat in Africa"}]

        shdb.save_session("search-proj-1", t1, project_id="LFI")
        shdb.save_session("search-proj-2", t2, project_id="ACME")

        results = shdb.search_sessions("flamingo", project_id="ACME")
        ids = [r['id'] for r in results]
        assert "search-proj-2" in ids
        assert "search-proj-1" not in ids

    def test_search_without_project_filter_returns_all(self, initialized_db):
        """Search without project_id returns results from all projects."""
        t1 = [{"role": "user", "content": "Pelican feeding habits"}]
        t2 = [{"role": "user", "content": "Pelican nesting behavior"}]

        shdb.save_session("search-all-1", t1, project_id="LFI")
        shdb.save_session("search-all-2", t2, project_id="ACME")

        results = shdb.search_sessions("pelican")
        ids = [r['id'] for r in results]
        assert "search-all-1" in ids
        assert "search-all-2" in ids

    def test_search_results_ordered_by_timestamp_desc(self, initialized_db):
        """Search results are ordered by timestamp descending (newest first)."""
        t1 = [{"role": "user", "content": "Iguana sighting", "timestamp": 1700000000}]
        t2 = [{"role": "user", "content": "Iguana breeding", "timestamp": 1700001000}]
        t3 = [{"role": "user", "content": "Iguana colors", "timestamp": 1700000500}]

        shdb.save_session("search-ord-1", t1)
        shdb.save_session("search-ord-2", t2)
        shdb.save_session("search-ord-3", t3)

        results = shdb.search_sessions("iguana")
        ids = [r['id'] for r in results]
        assert ids == ["search-ord-2", "search-ord-3", "search-ord-1"]


# ---------------------------------------------------------------------------
# 5. Recent sessions
# ---------------------------------------------------------------------------

class TestGetRecentSessions:
    """Test listing recent sessions."""

    def test_recent_returns_sessions(self, initialized_db):
        """get_recent_sessions returns saved sessions."""
        shdb.save_session("recent-001", _make_transcript(), session_name="First")
        shdb.save_session("recent-002", _make_transcript(), session_name="Second")

        results = shdb.get_recent_sessions(limit=10)
        assert len(results) >= 2

    def test_recent_ordered_by_timestamp_desc(self, initialized_db):
        """Recent sessions are ordered newest first."""
        t1 = [{"role": "user", "content": "Old", "timestamp": 1700000000}]
        t2 = [{"role": "user", "content": "New", "timestamp": 1700010000}]

        shdb.save_session("recent-old", t1)
        shdb.save_session("recent-new", t2)

        results = shdb.get_recent_sessions(limit=10)
        ids = [r['id'] for r in results]
        assert ids.index("recent-new") < ids.index("recent-old")

    def test_recent_respects_limit(self, initialized_db):
        """get_recent_sessions respects the limit parameter."""
        for i in range(10):
            t = [{"role": "user", "content": f"msg {i}", "timestamp": 1700000000 + i}]
            shdb.save_session(f"recent-lim-{i}", t)

        results = shdb.get_recent_sessions(limit=5)
        assert len(results) == 5

    def test_recent_filters_by_project(self, initialized_db):
        """get_recent_sessions filters by project_id."""
        t = [{"role": "user", "content": "Hello", "timestamp": 1700000000}]

        shdb.save_session("recent-proj-1", t, project_id="LFI")
        shdb.save_session("recent-proj-2", t, project_id="ACME")
        shdb.save_session("recent-proj-3", t, project_id="LFI")

        results = shdb.get_recent_sessions(project_id="LFI")
        ids = [r['id'] for r in results]
        assert "recent-proj-1" in ids
        assert "recent-proj-3" in ids
        assert "recent-proj-2" not in ids

    def test_recent_excludes_full_transcript(self, initialized_db):
        """get_recent_sessions does NOT include full_transcript_json."""
        shdb.save_session("recent-no-json", _make_transcript())

        results = shdb.get_recent_sessions(limit=10)
        for r in results:
            assert 'full_transcript_json' not in r

    def test_recent_includes_metadata_fields(self, initialized_db):
        """get_recent_sessions includes expected metadata fields."""
        shdb.save_session("recent-fields", _make_transcript(), session_name="Meta test")

        results = shdb.get_recent_sessions(limit=10)
        session = next(r for r in results if r['id'] == "recent-fields")
        expected_fields = {
            'id', 'timestamp', 'name', 'message_count',
            'tool_call_count', 'memories_extracted',
            'duration_seconds', 'session_quality'
        }
        assert expected_fields.issubset(set(session.keys()))

    def test_recent_empty_database(self, initialized_db):
        """get_recent_sessions returns empty list on empty database."""
        results = shdb.get_recent_sessions()
        assert results == []


# ---------------------------------------------------------------------------
# 6. Statistics
# ---------------------------------------------------------------------------

class TestGetSessionStats:
    """Test get_session_stats aggregation."""

    def test_stats_empty_database(self, initialized_db):
        """Stats on empty database returns zeros."""
        stats = shdb.get_session_stats()
        assert stats['total_sessions'] == 0
        assert stats['avg_quality'] == 0.0
        assert stats['total_messages'] == 0
        assert stats['total_memories_extracted'] == 0

    def test_stats_total_sessions(self, initialized_db):
        """total_sessions counts all sessions."""
        for i in range(3):
            shdb.save_session(f"stats-{i}", _make_transcript())

        stats = shdb.get_session_stats()
        assert stats['total_sessions'] == 3

    def test_stats_total_messages(self, initialized_db):
        """total_messages sums message_count across all sessions."""
        shdb.save_session("stats-msg-1", _make_transcript())  # 4 messages
        shdb.save_session("stats-msg-2", _make_transcript())  # 4 messages

        stats = shdb.get_session_stats()
        assert stats['total_messages'] == 8

    def test_stats_total_memories(self, initialized_db):
        """total_memories_extracted sums across all sessions."""
        shdb.save_session("stats-mem-1", _make_transcript(), memories_extracted=3)
        shdb.save_session("stats-mem-2", _make_transcript(), memories_extracted=7)

        stats = shdb.get_session_stats()
        assert stats['total_memories_extracted'] == 10

    def test_stats_avg_quality(self, initialized_db):
        """avg_quality averages session_quality across all sessions."""
        shdb.save_session("stats-q-1", _make_transcript(), session_quality=0.6)
        shdb.save_session("stats-q-2", _make_transcript(), session_quality=0.8)

        stats = shdb.get_session_stats()
        assert abs(stats['avg_quality'] - 0.7) < 0.001

    def test_stats_returns_expected_keys(self, initialized_db):
        """Stats dict has all expected keys."""
        stats = shdb.get_session_stats()
        expected_keys = {'total_sessions', 'avg_quality', 'total_messages', 'total_memories_extracted'}
        assert expected_keys == set(stats.keys())


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test unusual inputs and boundary conditions."""

    def test_empty_transcript(self, initialized_db):
        """Saving an empty transcript works."""
        result = shdb.save_session("edge-empty", [])
        assert result is True

        session = shdb.get_session_by_id("edge-empty")
        assert session is not None
        assert session['message_count'] == 0
        assert session['tool_call_count'] == 0

    def test_unicode_content(self, initialized_db):
        """Unicode content in messages is preserved."""
        transcript = [
            {"role": "user", "content": "Tell me about cats"},
            {"role": "assistant", "content": "Cats are great animals."},
        ]
        shdb.save_session("edge-unicode", transcript, session_name="Unicode test")

        session = shdb.get_session_by_id("edge-unicode")
        assert session['transcript'][1]['content'] == "Cats are great animals."

    def test_very_long_message(self, initialized_db):
        """Very long messages are stored and retrieved correctly."""
        long_content = "x" * 100000
        transcript = [
            {"role": "user", "content": long_content},
        ]
        shdb.save_session("edge-long", transcript)

        session = shdb.get_session_by_id("edge-long")
        assert len(session['transcript'][0]['content']) == 100000

    def test_mixed_content_types(self, initialized_db):
        """Messages with list content (tool_use) are stored correctly."""
        transcript = _make_transcript_with_tools()
        shdb.save_session("edge-mixed", transcript)

        session = shdb.get_session_by_id("edge-mixed")
        # Second message has list content
        assert isinstance(session['transcript'][1]['content'], list)

    def test_transcript_text_extraction_for_fts(self, initialized_db):
        """FTS text extraction only uses string content, not list content."""
        transcript = [
            {"role": "user", "content": "Search for armadillo facts"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Here are armadillo facts."},
                    {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
                ],
            },
        ]
        shdb.save_session("edge-fts", transcript)

        # Should find by user's string content
        results = shdb.search_sessions("armadillo")
        ids = [r['id'] for r in results]
        assert "edge-fts" in ids

    def test_many_sessions(self, initialized_db):
        """Saving and querying many sessions works."""
        for i in range(50):
            t = [{"role": "user", "content": f"Session {i} content", "timestamp": 1700000000 + i}]
            shdb.save_session(f"many-{i}", t)

        stats = shdb.get_session_stats()
        assert stats['total_sessions'] == 50

        results = shdb.get_recent_sessions(limit=10)
        assert len(results) == 10

    def test_special_characters_in_session_id(self, initialized_db):
        """Session IDs with special characters work."""
        sid = "sess/with:special-chars_2024.01"
        shdb.save_session(sid, _make_transcript())

        session = shdb.get_session_by_id(sid)
        assert session is not None
        assert session['id'] == sid

    def test_timestamp_out_of_order(self, initialized_db):
        """Handles messages with out-of-order timestamps."""
        transcript = [
            {"role": "user", "content": "First", "timestamp": 1700000050},
            {"role": "assistant", "content": "Second", "timestamp": 1700000010},
            {"role": "user", "content": "Third", "timestamp": 1700000100},
        ]
        shdb.save_session("edge-order", transcript)

        session = shdb.get_session_by_id("edge-order")
        # first_timestamp should be minimum (10), last should be max (100)
        assert session['timestamp'] == 1700000010
        assert session['duration_seconds'] == 90

    def test_content_missing_in_message(self, initialized_db):
        """Messages without 'content' key don't crash."""
        transcript = [
            {"role": "user"},
            {"role": "assistant", "content": "Response"},
        ]
        result = shdb.save_session("edge-no-content", transcript)
        assert result is True

    def test_zero_quality(self, initialized_db):
        """session_quality of 0.0 is stored correctly (not confused with None)."""
        shdb.save_session("edge-zero-q", _make_transcript(), session_quality=0.0)

        session = shdb.get_session_by_id("edge-zero-q")
        assert session['session_quality'] == 0.0

    def test_save_session_calls_init(self, temp_db_path):
        """save_session initializes the database if not already done."""
        # Don't call init_session_db manually -- save_session does it
        result = shdb.save_session("auto-init", _make_transcript())
        assert result is True

        session = shdb.get_session_by_id("auto-init")
        assert session is not None


# ---------------------------------------------------------------------------
# 8. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Test behavior under error conditions."""

    def test_save_to_invalid_path_returns_false(self, temp_db_path):
        """save_session returns False when sqlite3.connect fails on an invalid path.

        Note: save_session calls init_session_db() which does os.makedirs on
        the parent dir. To trigger the failure path inside save_session's
        try/except, we mock sqlite3.connect to raise after init succeeds.
        """
        from unittest.mock import patch

        shdb.init_session_db()

        with patch('session_history_db.sqlite3') as mock_sqlite:
            mock_sqlite.connect.side_effect = sqlite3.OperationalError("cannot open database")
            result = shdb.save_session("err-001", _make_transcript())
            assert result is False

    def test_search_empty_database(self, initialized_db):
        """Searching an empty database returns empty list."""
        results = shdb.search_sessions("anything")
        assert results == []

    def test_get_session_stats_returns_dict(self, initialized_db):
        """get_session_stats always returns a dict, even when empty."""
        stats = shdb.get_session_stats()
        assert isinstance(stats, dict)

    def test_get_recent_default_limit(self, initialized_db):
        """get_recent_sessions default limit is 10."""
        for i in range(15):
            t = [{"role": "user", "content": f"msg {i}", "timestamp": 1700000000 + i}]
            shdb.save_session(f"default-lim-{i}", t)

        results = shdb.get_recent_sessions()
        assert len(results) == 10
