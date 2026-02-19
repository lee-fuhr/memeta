"""
Tests for the self-test diagnostic system (Spec 25).

Covers:
- Each of the 6 individual health checks (pass and fail scenarios)
- run_all() aggregation logic
- get_report_text() formatting
- Graceful handling of missing files, locked DBs, permission errors
"""

import os
import sqlite3
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_system.config import MemorySystemConfig
from memory_system.self_test import SelfTest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """
    Ensure every test gets its own temp paths via env vars.

    MemorySystemConfig properties read env vars on every access, so the
    env must stay set for the full test lifetime.  monkeypatch handles
    cleanup automatically.
    """
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    monkeypatch.setenv("MEMORY_SYSTEM_MEMORY_DIR", str(memory_dir))
    monkeypatch.setenv("MEMORY_SYSTEM_PROJECT_ID", "test-project")
    monkeypatch.setenv("MEMORY_SYSTEM_INTEL_DB", str(tmp_path / "intelligence.db"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> MemorySystemConfig:
    """Build a MemorySystemConfig using env vars set by the fixture."""
    return MemorySystemConfig()


def _seed_intelligence_db(db_path: Path, *, with_embeddings: bool = False,
                          stale_embeddings: bool = False,
                          with_cb_open: bool = False) -> None:
    """Create an intelligence.db with the tables SelfTest expects."""
    conn = sqlite3.connect(str(db_path))
    try:
        # Core tables that check_db_accessible expects
        for table in ("voice_memories", "image_memories", "code_memories",
                      "decision_journal", "dream_insights"):
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY)")

        if with_embeddings:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    content_hash TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL
                )
            """)
            if stale_embeddings:
                old_date = (datetime.now() - timedelta(days=30)).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?, ?)",
                    ("hash1", b"\x00" * 16, 4, "test", old_date, old_date),
                )
            else:
                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?, ?)",
                    ("hash1", b"\x00" * 16, 4, "test", now, now),
                )

        if with_cb_open:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS circuit_breaker_state (
                    name TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'closed',
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_failure_at INTEGER,
                    opened_at INTEGER,
                    updated_at INTEGER NOT NULL
                )
            """)
            now_ts = int(time.time())
            conn.execute(
                "INSERT OR REPLACE INTO circuit_breaker_state VALUES (?, ?, ?, ?, ?, ?)",
                ("llm_extraction", "open", 5, now_ts, now_ts, now_ts),
            )

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. check_memory_readwrite
# ---------------------------------------------------------------------------

class TestCheckMemoryReadwrite:
    def test_pass_basic_roundtrip(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        result = st.check_memory_readwrite()
        assert result["passed"] is True
        assert result["name"] == "memory_readwrite"
        assert "duration_ms" in result

    def test_result_has_required_keys(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        result = st.check_memory_readwrite()
        for key in ("name", "passed", "message", "duration_ms"):
            assert key in result


# ---------------------------------------------------------------------------
# 2. check_db_accessible
# ---------------------------------------------------------------------------

class TestCheckDbAccessible:
    def test_pass_with_all_tables(self, tmp_path):
        config = _make_config()
        db_path = config.intelligence_db_path
        _seed_intelligence_db(db_path)

        st = SelfTest(config)
        result = st.check_db_accessible()
        assert result["passed"] is True
        assert "tables found" in result["message"]

    def test_fail_missing_db(self, tmp_path):
        config = _make_config()
        # Don't create the DB
        st = SelfTest(config)
        result = st.check_db_accessible()
        assert result["passed"] is False
        assert "not found" in result["message"]

    def test_fail_missing_tables(self, tmp_path):
        config = _make_config()
        db_path = config.intelligence_db_path
        # Create DB with only one table
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE voice_memories (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        st = SelfTest(config)
        result = st.check_db_accessible()
        assert result["passed"] is False
        assert "Missing tables" in result["message"]


# ---------------------------------------------------------------------------
# 3. check_embeddings_fresh
# ---------------------------------------------------------------------------

class TestCheckEmbeddingsFresh:
    def test_pass_with_recent_embeddings(self, tmp_path):
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path, with_embeddings=True)

        st = SelfTest(config)
        result = st.check_embeddings_fresh()
        assert result["passed"] is True
        assert "1 embeddings" in result["message"]

    def test_fail_stale_embeddings(self, tmp_path):
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path,
                              with_embeddings=True, stale_embeddings=True)

        st = SelfTest(config)
        result = st.check_embeddings_fresh()
        assert result["passed"] is False
        assert "No embeddings" in result["message"]

    def test_fail_no_db(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        result = st.check_embeddings_fresh()
        assert result["passed"] is False

    def test_fail_no_embeddings_table(self, tmp_path):
        config = _make_config()
        db_path = config.intelligence_db_path
        # Create DB but without embeddings table
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.commit()
        conn.close()

        st = SelfTest(config)
        result = st.check_embeddings_fresh()
        assert result["passed"] is False
        assert "not found" in result["message"]


# ---------------------------------------------------------------------------
# 4. check_search_functional
# ---------------------------------------------------------------------------

class TestCheckSearchFunctional:
    def test_pass_inmemory_search(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        result = st.check_search_functional()
        assert result["passed"] is True
        assert "functioning" in result["message"]


# ---------------------------------------------------------------------------
# 5. check_circuit_breaker_state
# ---------------------------------------------------------------------------

class TestCheckCircuitBreakerState:
    def test_pass_no_db(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        result = st.check_circuit_breaker_state()
        assert result["passed"] is True

    def test_pass_no_open_breakers(self, tmp_path):
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path)

        st = SelfTest(config)
        result = st.check_circuit_breaker_state()
        assert result["passed"] is True

    def test_fail_open_breaker(self, tmp_path):
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path, with_cb_open=True)

        st = SelfTest(config)
        result = st.check_circuit_breaker_state()
        assert result["passed"] is False
        assert "llm_extraction" in result["message"]


# ---------------------------------------------------------------------------
# 6. check_orphaned_files
# ---------------------------------------------------------------------------

class TestCheckOrphanedFiles:
    def test_pass_with_files(self, tmp_path):
        config = _make_config()
        mem_dir = config.project_memory_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "one.md").write_text("test")
        (mem_dir / "two.md").write_text("test")

        st = SelfTest(config)
        result = st.check_orphaned_files()
        assert result["passed"] is True
        assert "2 memory files" in result["message"]

    def test_fail_missing_dir(self, tmp_path):
        config = _make_config()
        # Do NOT create the memories subdirectory
        st = SelfTest(config)
        result = st.check_orphaned_files()
        assert result["passed"] is False
        assert "not found" in result["message"]

    def test_pass_empty_dir(self, tmp_path):
        config = _make_config()
        mem_dir = config.project_memory_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)

        st = SelfTest(config)
        result = st.check_orphaned_files()
        assert result["passed"] is True
        assert "0 memory files" in result["message"]


# ---------------------------------------------------------------------------
# 7. run_all aggregation
# ---------------------------------------------------------------------------

class TestRunAll:
    def test_run_all_returns_correct_structure(self, tmp_path):
        config = _make_config()
        # Seed enough for most checks to pass
        _seed_intelligence_db(config.intelligence_db_path, with_embeddings=True)
        mem_dir = config.project_memory_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)

        st = SelfTest(config)
        report = st.run_all()

        assert "passed" in report
        assert "checks" in report
        assert "total_duration_ms" in report
        assert "summary" in report
        assert "timestamp" in report
        assert len(report["checks"]) == 6

    def test_run_all_passes_when_all_green(self, tmp_path):
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path, with_embeddings=True)
        mem_dir = config.project_memory_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)

        st = SelfTest(config)
        report = st.run_all()
        assert report["passed"] is True
        assert report["summary"] == "6/6 checks passed"

    def test_run_all_fails_when_any_fail(self, tmp_path):
        config = _make_config()
        # Don't create DB or memory dir — multiple checks will fail
        st = SelfTest(config)
        report = st.run_all()
        assert report["passed"] is False
        assert "6/6" not in report["summary"]


# ---------------------------------------------------------------------------
# 8. get_report_text formatting
# ---------------------------------------------------------------------------

class TestGetReportText:
    def test_report_text_contains_all_checks(self, tmp_path):
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path, with_embeddings=True)
        mem_dir = config.project_memory_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)

        st = SelfTest(config)
        st.run_all()
        text = st.get_report_text()

        assert "Total Rekall self-test report" in text
        assert "memory_readwrite" in text
        assert "db_accessible" in text
        assert "embeddings_fresh" in text
        assert "search_functional" in text
        assert "circuit_breaker_state" in text
        assert "orphaned_files" in text

    def test_report_text_without_prior_run(self, tmp_path):
        """get_report_text auto-calls run_all if needed."""
        config = _make_config()
        _seed_intelligence_db(config.intelligence_db_path, with_embeddings=True)
        mem_dir = config.project_memory_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)

        st = SelfTest(config)
        text = st.get_report_text()  # No prior run_all()
        assert "Total Rekall self-test report" in text

    def test_report_shows_pass_fail_labels(self, tmp_path):
        config = _make_config()
        # Create conditions for mixed results
        _seed_intelligence_db(config.intelligence_db_path, with_embeddings=True)
        # No memories dir — orphaned_files will fail
        st = SelfTest(config)
        st.run_all()
        text = st.get_report_text()
        assert "[PASS]" in text
        assert "[FAIL]" in text


# ---------------------------------------------------------------------------
# 9. Duration tracking
# ---------------------------------------------------------------------------

class TestDurationTracking:
    def test_duration_is_positive(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        result = st.check_memory_readwrite()
        assert result["duration_ms"] >= 0

    def test_total_duration_is_positive(self, tmp_path):
        config = _make_config()
        st = SelfTest(config)
        report = st.run_all()
        assert report["total_duration_ms"] >= 0
