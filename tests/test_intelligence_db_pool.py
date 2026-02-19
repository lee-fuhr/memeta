"""
Tests for IntelligenceDB connection pooling refactor.

Verifies that IntelligenceDB uses db_pool.py for connection management
instead of raw sqlite3.connect() calls, while maintaining full
backward compatibility with existing code that uses db.conn.
"""

import sys
import os

# In a git worktree setup, the editable install may resolve to the main
# worktree's src/ instead of this worktree's src/. Patch the editable
# finder to use this worktree's source before any memory_system imports.
_this_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
try:
    import __editable___total_rekall_0_18_0_finder as _finder
    _finder.MAPPING["memory_system"] = _this_src
except ImportError:
    pass

# Clear any cached memory_system imports so they reload from the patched path
for _mod in list(sys.modules):
    if _mod.startswith("memory_system"):
        del sys.modules[_mod]

import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from memory_system.intelligence_db import IntelligenceDB
from memory_system.db_pool import PooledConnection, close_all_pools


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database path for testing."""
    db_path = tmp_path / "test_pool.db"
    yield db_path
    # Clean up pool state between tests
    close_all_pools()


@pytest.fixture
def temp_db_2(tmp_path):
    """Create a second temporary database path for concurrent tests."""
    db_path = tmp_path / "test_pool_2.db"
    yield db_path
    close_all_pools()


class TestPooledConnectionUsage:
    """Verify IntelligenceDB uses PooledConnection instead of raw sqlite3."""

    def test_conn_is_pooled_connection(self, temp_db):
        """self.conn should be a PooledConnection, not a raw sqlite3.Connection."""
        db = IntelligenceDB(temp_db)
        try:
            assert isinstance(db.conn, PooledConnection), (
                f"Expected PooledConnection, got {type(db.conn).__name__}"
            )
            # Verify it is NOT a raw sqlite3.Connection
            assert not isinstance(db.conn, sqlite3.Connection)
        finally:
            db.close()

    def test_conn_is_none_after_close(self, temp_db):
        """After close(), self.conn should be None."""
        db = IntelligenceDB(temp_db)
        db.close()
        assert db.conn is None


class TestBasicOperations:
    """Verify basic CRUD operations work through the pooled connection."""

    def test_insert_and_read(self, temp_db):
        """Can insert and read data through the pooled connection."""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()
            cursor.execute("""
                INSERT INTO voice_memories
                (audio_path, transcript, created_at)
                VALUES (?, ?, ?)
            """, ("/test.m4a", "Hello world", "2026-02-18T10:00:00"))
            db.conn.commit()

            cursor.execute("SELECT * FROM voice_memories WHERE id = 1")
            row = cursor.fetchone()
            assert row["audio_path"] == "/test.m4a"
            assert row["transcript"] == "Hello world"

    def test_row_factory_set(self, temp_db):
        """Row factory should be sqlite3.Row for dict-like access."""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()
            cursor.execute("""
                INSERT INTO code_memories
                (snippet, language, created_at)
                VALUES (?, ?, ?)
            """, ("print('hi')", "python", "2026-02-18T10:00:00"))
            db.conn.commit()

            cursor.execute("SELECT * FROM code_memories WHERE id = 1")
            row = cursor.fetchone()
            # sqlite3.Row allows dict-like key access
            assert row["snippet"] == "print('hi')"
            assert row["language"] == "python"


class TestConnectionLeaks:
    """Verify connections are properly managed and not leaked."""

    def test_100_sequential_operations(self, temp_db):
        """100 sequential create/close cycles should not leak connections."""
        for i in range(100):
            db = IntelligenceDB(temp_db)
            cursor = db.conn.cursor()
            cursor.execute("""
                INSERT INTO decision_journal
                (decision, options_considered, chosen_option, rationale, decided_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                f"Decision {i}",
                '["A", "B"]',
                "A",
                "Rationale",
                "2026-02-18T10:00:00",
            ))
            db.conn.commit()
            db.close()

        # Verify all 100 rows were written (no data loss)
        db = IntelligenceDB(temp_db)
        try:
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM decision_journal")
            count = cursor.fetchone()[0]
            assert count == 100
        finally:
            db.close()


class TestContextManager:
    """Verify context manager protocol works with pooled connections."""

    def test_with_statement(self, temp_db):
        """Context manager should work: conn available inside, None after."""
        with IntelligenceDB(temp_db) as db:
            assert db.conn is not None
            assert isinstance(db.conn, PooledConnection)
            # Operations should work inside the block
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM voice_memories")
            count = cursor.fetchone()[0]
            assert count == 0

        # After exiting, conn should be returned to pool
        assert db.conn is None

    def test_nested_context_managers(self, temp_db):
        """Multiple context manager usages on the same db_path should work."""
        with IntelligenceDB(temp_db) as db1:
            db1.conn.cursor().execute("""
                INSERT INTO ab_tests
                (test_name, strategy_a_name, strategy_b_name, started_at)
                VALUES (?, ?, ?, ?)
            """, ("Test 1", "A", "B", "2026-02-18"))
            db1.conn.commit()

        # Second usage should get a (possibly reused) pooled connection
        with IntelligenceDB(temp_db) as db2:
            cursor = db2.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ab_tests")
            count = cursor.fetchone()[0]
            assert count == 1


class TestConcurrentInstances:
    """Verify two IntelligenceDB instances don't interfere."""

    def test_two_instances_different_dbs(self, temp_db, temp_db_2):
        """Two instances pointing to different databases operate independently."""
        db1 = IntelligenceDB(temp_db)
        db2 = IntelligenceDB(temp_db_2)

        try:
            # Write to db1
            db1.conn.cursor().execute("""
                INSERT INTO dream_insights
                (run_date, memories_analyzed, new_connections, runtime_seconds)
                VALUES (?, ?, ?, ?)
            """, ("2026-02-18", 50, 3, 10.5))
            db1.conn.commit()

            # db2 should have no rows
            cursor2 = db2.conn.cursor()
            cursor2.execute("SELECT COUNT(*) FROM dream_insights")
            assert cursor2.fetchone()[0] == 0

            # db1 should have 1 row
            cursor1 = db1.conn.cursor()
            cursor1.execute("SELECT COUNT(*) FROM dream_insights")
            assert cursor1.fetchone()[0] == 1
        finally:
            db1.close()
            db2.close()

    def test_two_instances_same_db(self, temp_db):
        """Two instances on the same database can both read/write."""
        db1 = IntelligenceDB(temp_db)
        db2 = IntelligenceDB(temp_db)

        try:
            # Write via db1
            db1.conn.cursor().execute("""
                INSERT INTO cross_system_imports
                (source_system, pattern_type, pattern_description, imported_at)
                VALUES (?, ?, ?, ?)
            """, ("System A", "workflow", "Pattern 1", "2026-02-18"))
            db1.conn.commit()

            # Read via db2
            cursor2 = db2.conn.cursor()
            cursor2.execute("SELECT COUNT(*) FROM cross_system_imports")
            assert cursor2.fetchone()[0] == 1
        finally:
            db1.close()
            db2.close()


class TestSchemaCreation:
    """Verify schema is created correctly on first use."""

    def test_schema_on_fresh_db(self, tmp_path):
        """Schema should be created on a brand new database path."""
        fresh_path = tmp_path / "brand_new.db"
        assert not fresh_path.exists()

        db = IntelligenceDB(fresh_path)
        try:
            assert fresh_path.exists()

            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            expected_tables = {
                "voice_memories",
                "image_memories",
                "code_memories",
                "decision_journal",
                "ab_tests",
                "cross_system_imports",
                "dream_insights",
                "temporal_patterns",
                "memory_access_log",
                "memory_clusters",
                "memory_summaries",
            }
            assert expected_tables.issubset(tables)
        finally:
            db.close()
            close_all_pools()


class TestErrorRecovery:
    """Verify operations work after errors."""

    def test_operation_after_failed_query(self, temp_db):
        """A successful operation should work after a failed query."""
        db = IntelligenceDB(temp_db)
        try:
            # Trigger an error (query a non-existent table)
            with pytest.raises(sqlite3.OperationalError):
                db.conn.cursor().execute("SELECT * FROM nonexistent_table")

            # Subsequent operations should still work
            cursor = db.conn.cursor()
            cursor.execute("""
                INSERT INTO image_memories
                (image_path, created_at)
                VALUES (?, ?)
            """, ("/test.png", "2026-02-18T10:00:00"))
            db.conn.commit()

            cursor.execute("SELECT COUNT(*) FROM image_memories")
            assert cursor.fetchone()[0] == 1
        finally:
            db.close()


class TestCloseIdempotency:
    """Verify close() is safe to call multiple times."""

    def test_close_called_twice(self, temp_db):
        """Calling close() twice should not raise an error."""
        db = IntelligenceDB(temp_db)
        db.close()
        db.close()  # Should not raise
        assert db.conn is None

    def test_close_called_three_times(self, temp_db):
        """Calling close() three times should not raise an error."""
        db = IntelligenceDB(temp_db)
        db.close()
        db.close()
        db.close()
        assert db.conn is None


class TestThreadSafety:
    """Verify pooled connections work across threads."""

    def test_threaded_inserts(self, temp_db):
        """Multiple threads inserting via separate IntelligenceDB instances."""
        errors = []
        rows_per_thread = 10
        num_threads = 4

        def insert_rows(thread_id):
            try:
                db = IntelligenceDB(temp_db)
                try:
                    for i in range(rows_per_thread):
                        db.conn.cursor().execute("""
                            INSERT INTO code_memories
                            (snippet, language, created_at)
                            VALUES (?, ?, ?)
                        """, (
                            f"Thread {thread_id} snippet {i}",
                            "python",
                            "2026-02-18T10:00:00",
                        ))
                        db.conn.commit()
                finally:
                    db.close()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=insert_rows, args=(t,))
            for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Thread errors: {errors}"

        # Verify total row count
        db = IntelligenceDB(temp_db)
        try:
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM code_memories")
            count = cursor.fetchone()[0]
            assert count == num_threads * rows_per_thread
        finally:
            db.close()
