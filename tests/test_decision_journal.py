"""Tests for decision journal — Decision Store + legacy wrappers."""

import json
import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone

from memory_system.decision_journal import (
    Decision,
    DecisionStore,
    record_decision,
    track_outcome,
    learn_from_decisions,
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def store(temp_db):
    """Create DecisionStore with temp database."""
    return DecisionStore(temp_db)


# --- DecisionStore._init_db ---

class TestInitDb:
    """Tests for database initialization."""

    def test_creates_table(self, store):
        """_init_db creates the decisions table."""
        import sqlite3
        conn = sqlite3.connect(store._db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='decisions'"
        )
        assert cursor.fetchone() is not None
        conn.close()


# --- record_decision ---

class TestRecordDecision:
    """Tests for recording decisions via DecisionStore."""

    def test_returns_id(self, store):
        """record_decision returns an integer ID."""
        decision_id = store.record_decision(
            decision_text="Use PostgreSQL",
            options_considered=["PostgreSQL", "MySQL", "SQLite"],
            chosen_option="PostgreSQL",
            rationale="Better for complex queries",
        )
        assert isinstance(decision_id, int)
        assert decision_id > 0

    def test_stores_all_fields(self, store):
        """record_decision persists all provided fields."""
        decision_id = store.record_decision(
            decision_text="Use PostgreSQL",
            options_considered=["PostgreSQL", "MySQL"],
            chosen_option="PostgreSQL",
            rationale="Better for complex queries",
            files_affected=["src/db.py", "config.yaml"],
            session_id="sess-abc",
        )
        decisions = store.get_decisions_for_session("sess-abc")
        assert len(decisions) == 1
        d = decisions[0]
        assert d.decision_text == "Use PostgreSQL"
        assert json.loads(d.options_considered) == ["PostgreSQL", "MySQL"]
        assert d.chosen_option == "PostgreSQL"
        assert d.rationale == "Better for complex queries"
        assert json.loads(d.files_affected) == ["src/db.py", "config.yaml"]
        assert d.session_id == "sess-abc"


# --- record_outcome ---

class TestRecordOutcome:
    """Tests for recording outcomes."""

    def test_updates_existing_decision(self, store):
        """record_outcome updates outcome and success for an existing decision."""
        decision_id = store.record_decision(
            decision_text="Use PostgreSQL",
            options_considered=["PostgreSQL", "MySQL"],
            chosen_option="PostgreSQL",
            rationale="Better for complex queries",
        )
        result = store.record_outcome(decision_id, "Worked great, fast queries", True)
        assert result is True

        decisions = store.get_recent_decisions(days_back=1)
        assert len(decisions) == 1
        assert decisions[0].outcome == "Worked great, fast queries"
        assert decisions[0].success is True

    def test_returns_false_for_nonexistent_id(self, store):
        """record_outcome returns False for an ID that doesn't exist."""
        result = store.record_outcome(9999, "Never happened", False)
        assert result is False


# --- get_decisions_for_session ---

class TestGetDecisionsForSession:
    """Tests for session-based decision retrieval."""

    def test_filters_by_session_id(self, store):
        """get_decisions_for_session returns only decisions from that session."""
        store.record_decision("Decision A", ["A"], "A", "reason", session_id="sess-1")
        store.record_decision("Decision B", ["B"], "B", "reason", session_id="sess-2")

        results = store.get_decisions_for_session("sess-1")
        assert len(results) == 1
        assert results[0].decision_text == "Decision A"

    def test_empty_for_unknown_session(self, store):
        """get_decisions_for_session returns empty list for unknown session."""
        results = store.get_decisions_for_session("nonexistent")
        assert results == []


# --- get_decisions_for_file ---

class TestGetDecisionsForFile:
    """Tests for file-based decision retrieval."""

    def test_exact_match(self, store):
        """get_decisions_for_file finds decisions affecting exact file path."""
        store.record_decision(
            "Refactor db", ["A"], "A", "reason",
            files_affected=["src/db.py"],
        )
        results = store.get_decisions_for_file("src/db.py")
        assert len(results) == 1

    def test_prefix_match_directory(self, store):
        """get_decisions_for_file finds decisions affecting files in directory."""
        store.record_decision(
            "Restructure src", ["A"], "A", "reason",
            files_affected=["src/models/user.py", "src/models/order.py"],
        )
        results = store.get_decisions_for_file("src/models/")
        assert len(results) == 1

    def test_no_match_returns_empty(self, store):
        """get_decisions_for_file returns empty when no decisions match."""
        store.record_decision(
            "Change config", ["A"], "A", "reason",
            files_affected=["config.yaml"],
        )
        results = store.get_decisions_for_file("src/unrelated.py")
        assert results == []


# --- get_recent_decisions ---

class TestGetRecentDecisions:
    """Tests for time-based decision retrieval."""

    def test_respects_days_back(self, store):
        """get_recent_decisions only returns decisions within the window."""
        # Insert one recent, one old
        store.record_decision("Recent", ["A"], "A", "reason")

        # Manually insert an old one
        import sqlite3
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        conn = sqlite3.connect(store._db_path)
        conn.execute(
            "INSERT INTO decisions (decision_text, options_considered, chosen_option, rationale, "
            "files_affected, session_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Old decision", "[]", "X", "old reason", "[]", "old-sess", old_ts),
        )
        conn.commit()
        conn.close()

        results = store.get_recent_decisions(days_back=30)
        assert len(results) == 1
        assert results[0].decision_text == "Recent"

    def test_empty_db_returns_empty(self, store):
        """get_recent_decisions on empty DB returns empty list."""
        results = store.get_recent_decisions()
        assert results == []


# --- learn_from_decisions (DecisionStore method) ---

class TestLearnFromDecisionsStore:
    """Tests for DecisionStore.learn_from_decisions."""

    def test_returns_correct_stats(self, store):
        """learn_from_decisions returns dict with total, successful, success_rate, pending_outcome."""
        id1 = store.record_decision("D1", ["A"], "A", "reason")
        id2 = store.record_decision("D2", ["B"], "B", "reason")
        id3 = store.record_decision("D3", ["C"], "C", "reason")

        store.record_outcome(id1, "Great", True)
        store.record_outcome(id2, "Bad", False)
        # id3 has no outcome yet

        stats = store.learn_from_decisions()
        assert stats["total"] == 3
        assert stats["successful"] == 1
        assert stats["success_rate"] == pytest.approx(1 / 3)
        assert stats["pending_outcome"] == 1


# --- Legacy wrappers ---

class TestLegacyWrappers:
    """Tests for backward-compatible module-level functions."""

    def test_learn_from_decisions_legacy_dict_shape(self):
        """Legacy learn_from_decisions returns expected dict shape."""
        decisions = [
            {"outcome": {"success": True}},
            {"outcome": {"success": False}},
            {"outcome": None},
        ]
        result = learn_from_decisions(decisions)
        assert "total" in result
        assert "successful" in result
        assert "success_rate" in result
        assert result["total"] == 3
        assert result["successful"] == 1

    def test_record_decision_legacy_returns_dict(self):
        """Legacy record_decision returns dict with expected keys."""
        result = record_decision("Use X", ["X", "Y"], "X", "Because")
        assert isinstance(result, dict)
        assert result["type"] == "decision"
        assert result["decision"] == "Use X"
        assert result["options"] == ["X", "Y"]
        assert result["chosen"] == "X"
        assert result["rationale"] == "Because"
        assert "timestamp" in result
        assert result["outcome"] is None


# --- Integration ---

class TestDecisionStoreIntegration:
    """Integration test: record -> outcome -> learn pipeline."""

    def test_record_outcome_learn_pipeline(self, store):
        """Full pipeline: record decisions, add outcomes, analyze."""
        id1 = store.record_decision(
            "Use FAISS for vectors", ["FAISS", "Annoy", "Pinecone"],
            "FAISS", "Local, fast, no external deps",
            files_affected=["src/vector_store.py"],
            session_id="sess-pipeline",
        )
        id2 = store.record_decision(
            "Use SQLite for metadata", ["SQLite", "PostgreSQL"],
            "SQLite", "Simple, embedded",
            files_affected=["src/db.py"],
            session_id="sess-pipeline",
        )

        # Record outcomes
        store.record_outcome(id1, "FAISS works perfectly", True)
        store.record_outcome(id2, "SQLite hitting lock contention", False)

        # Verify session query
        session_decisions = store.get_decisions_for_session("sess-pipeline")
        assert len(session_decisions) == 2

        # Verify file query
        file_decisions = store.get_decisions_for_file("src/vector_store.py")
        assert len(file_decisions) == 1
        assert file_decisions[0].decision_text == "Use FAISS for vectors"

        # Learn
        stats = store.learn_from_decisions()
        assert stats["total"] == 2
        assert stats["successful"] == 1
        assert stats["success_rate"] == pytest.approx(0.5)
        assert stats["pending_outcome"] == 0
