"""
Tests for Feature 23: Memory access pattern tracker.
"""

import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Allow importing from this worktree's src/ when the editable install
# points to a different worktree (main).
try:
    from memory_system.access_tracker import AccessTracker, VALID_ACCESS_TYPES
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from access_tracker import AccessTracker, VALID_ACCESS_TYPES


@pytest.fixture
def tracker(tmp_path):
    """Provide a fresh AccessTracker backed by a temp database."""
    db = tmp_path / "test_access.db"
    t = AccessTracker(db_path=db)
    yield t
    t.close()


# ── Schema / init ──────────────────────────────────────────────────────────


class TestInit:
    def test_creates_table(self, tracker):
        """Table memory_access_log exists after init."""
        cur = tracker.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_access_log'"
        )
        assert cur.fetchone() is not None

    def test_creates_indexes(self, tracker):
        """All three indexes are created."""
        cur = tracker.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        names = {r["name"] for r in cur.fetchall()}
        assert "idx_mal_memory_id" in names
        assert "idx_mal_accessed_at" in names
        assert "idx_mal_access_type" in names

    def test_idempotent_init(self, tmp_path):
        """Creating two trackers on the same DB does not raise."""
        db = tmp_path / "idempotent.db"
        t1 = AccessTracker(db_path=db)
        t2 = AccessTracker(db_path=db)
        t1.close()
        t2.close()


# ── log_access ─────────────────────────────────────────────────────────────


class TestLogAccess:
    def test_returns_positive_id(self, tracker):
        aid = tracker.log_access("mem-1", "search")
        assert isinstance(aid, int)
        assert aid > 0

    def test_increments_id(self, tracker):
        a1 = tracker.log_access("mem-1", "search")
        a2 = tracker.log_access("mem-1", "direct")
        assert a2 > a1

    def test_invalid_access_type_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid access_type"):
            tracker.log_access("mem-1", "invalid_type")

    def test_all_valid_types_accepted(self, tracker):
        for atype in VALID_ACCESS_TYPES:
            aid = tracker.log_access("mem-types", atype)
            assert aid > 0

    def test_query_context_stored(self, tracker):
        tracker.log_access("mem-ctx", "search", query_context="deployment issues")
        history = tracker.get_access_history("mem-ctx")
        assert history[0]["query_context"] == "deployment issues"

    def test_query_context_defaults_none(self, tracker):
        tracker.log_access("mem-ctx2", "direct")
        history = tracker.get_access_history("mem-ctx2")
        assert history[0]["query_context"] is None


# ── get_access_frequency ───────────────────────────────────────────────────


class TestGetAccessFrequency:
    def test_unknown_memory_returns_zeros(self, tracker):
        freq = tracker.get_access_frequency("nonexistent")
        assert freq["total_accesses"] == 0
        assert freq["last_accessed"] is None
        assert all(v == 0 for v in freq["by_type"].values())

    def test_counts_multiple_accesses(self, tracker):
        tracker.log_access("mem-freq", "search")
        tracker.log_access("mem-freq", "search")
        tracker.log_access("mem-freq", "direct")
        freq = tracker.get_access_frequency("mem-freq")
        assert freq["total_accesses"] == 3
        assert freq["by_type"]["search"] == 2
        assert freq["by_type"]["direct"] == 1
        assert freq["by_type"]["briefing"] == 0

    def test_last_accessed_populated(self, tracker):
        tracker.log_access("mem-last", "search")
        freq = tracker.get_access_frequency("mem-last")
        assert freq["last_accessed"] is not None
        # Should parse as valid ISO timestamp
        datetime.fromisoformat(freq["last_accessed"])


# ── get_never_accessed ─────────────────────────────────────────────────────


class TestGetNeverAccessed:
    def test_empty_db_returns_empty(self, tracker):
        result = tracker.get_never_accessed(days=90)
        assert result == []

    def test_recent_access_not_returned(self, tracker):
        tracker.log_access("mem-fresh", "search")
        result = tracker.get_never_accessed(days=90)
        assert "mem-fresh" not in result

    def test_old_access_returned(self, tracker):
        # Insert a record with a manually backdated timestamp
        old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        cur = tracker.conn.cursor()
        cur.execute(
            "INSERT INTO memory_access_log (memory_id, accessed_at, access_type) "
            "VALUES (?, ?, ?)",
            ("mem-old", old_ts, "search"),
        )
        tracker.conn.commit()

        result = tracker.get_never_accessed(days=90)
        assert "mem-old" in result

    def test_mixed_old_and_new(self, tracker):
        # Old access
        old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        cur = tracker.conn.cursor()
        cur.execute(
            "INSERT INTO memory_access_log (memory_id, accessed_at, access_type) "
            "VALUES (?, ?, ?)",
            ("mem-stale", old_ts, "direct"),
        )
        tracker.conn.commit()

        # Fresh access
        tracker.log_access("mem-active", "briefing")

        stale = tracker.get_never_accessed(days=90)
        assert "mem-stale" in stale
        assert "mem-active" not in stale


# ── get_most_accessed ──────────────────────────────────────────────────────


class TestGetMostAccessed:
    def test_empty_returns_empty(self, tracker):
        assert tracker.get_most_accessed() == []

    def test_sorted_descending(self, tracker):
        # mem-a: 1 access, mem-b: 3 accesses
        tracker.log_access("mem-a", "search")
        for _ in range(3):
            tracker.log_access("mem-b", "search")

        top = tracker.get_most_accessed(limit=10)
        assert top[0]["memory_id"] == "mem-b"
        assert top[0]["total_accesses"] == 3
        assert top[1]["memory_id"] == "mem-a"
        assert top[1]["total_accesses"] == 1

    def test_limit_respected(self, tracker):
        for i in range(5):
            tracker.log_access(f"mem-{i}", "search")
        top = tracker.get_most_accessed(limit=2)
        assert len(top) == 2


# ── get_access_history ─────────────────────────────────────────────────────


class TestGetAccessHistory:
    def test_empty_for_unknown(self, tracker):
        assert tracker.get_access_history("nope") == []

    def test_returns_newest_first(self, tracker):
        tracker.log_access("mem-h", "search", query_context="q1")
        tracker.log_access("mem-h", "direct", query_context="q2")

        history = tracker.get_access_history("mem-h")
        assert len(history) == 2
        # newest first
        assert history[0]["access_type"] == "direct"
        assert history[1]["access_type"] == "search"

    def test_limit_respected(self, tracker):
        for i in range(10):
            tracker.log_access("mem-hlim", "search")
        history = tracker.get_access_history("mem-hlim", limit=3)
        assert len(history) == 3


# ── get_stats ──────────────────────────────────────────────────────────────


class TestGetStats:
    def test_empty_stats(self, tracker):
        stats = tracker.get_stats()
        assert stats["total_accesses"] == 0
        assert stats["unique_memories_accessed"] == 0
        assert all(v == 0 for v in stats["by_type"].values())

    def test_populated_stats(self, tracker):
        tracker.log_access("mem-s1", "search")
        tracker.log_access("mem-s1", "search")
        tracker.log_access("mem-s2", "direct")
        tracker.log_access("mem-s3", "briefing")

        stats = tracker.get_stats()
        assert stats["total_accesses"] == 4
        assert stats["unique_memories_accessed"] == 3
        assert stats["by_type"]["search"] == 2
        assert stats["by_type"]["direct"] == 1
        assert stats["by_type"]["briefing"] == 1
        assert stats["by_type"]["consolidation"] == 0
        assert stats["by_type"]["maintenance"] == 0


# ── Context manager ───────────────────────────────────────────────────────


class TestContextManager:
    def test_context_manager(self, tmp_path):
        db = tmp_path / "ctx.db"
        with AccessTracker(db_path=db) as t:
            t.log_access("mem-cm", "search")
            freq = t.get_access_frequency("mem-cm")
            assert freq["total_accesses"] == 1
