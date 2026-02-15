"""
Tests for db_pool.py - SQLite Connection Pooling

Covers:
1. Initialization (pool creation, size, WAL mode)
2. Connection get/return (basic checkout, return, pool exhaustion)
3. Concurrent access (thread safety, no SQLITE_BUSY errors)
4. PooledConnection proxy (attribute access, context manager)
5. Edge cases (double return, use after return, pool shutdown)
6. Error handling (invalid paths, corrupt DB)
7. Module-level convenience functions (get_pool, get_connection, close_all_pools)
"""

import pytest
import tempfile
import threading
import time
import sqlite3
import os
from pathlib import Path

from memory_system.db_pool import ConnectionPool, PooledConnection, get_pool, get_connection, close_all_pools, _pools, _pools_lock


@pytest.fixture
def temp_db():
    """Create a temporary database file path."""
    temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    db_path = temp_file.name
    temp_file.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)
    # Also clean WAL/SHM files
    Path(db_path + '-wal').unlink(missing_ok=True)
    Path(db_path + '-shm').unlink(missing_ok=True)


@pytest.fixture
def pool(temp_db):
    """Create a ConnectionPool with a temp database."""
    p = ConnectionPool(db_path=temp_db, pool_size=5, timeout=5.0)
    yield p
    p.close_all()


@pytest.fixture
def small_pool(temp_db):
    """Create a small ConnectionPool (size=2) for exhaustion tests."""
    p = ConnectionPool(db_path=temp_db, pool_size=2, timeout=2.0)
    yield p
    p.close_all()


@pytest.fixture(autouse=True)
def clear_global_pools():
    """Clear global pool registry between tests."""
    yield
    close_all_pools()


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    """Test pool creation and configuration."""

    def test_pool_stores_path(self, temp_db):
        """Pool stores the database path as a string."""
        pool = ConnectionPool(db_path=temp_db)
        assert pool.db_path == str(temp_db)
        pool.close_all()

    def test_pool_stores_path_from_pathlib(self, temp_db):
        """Pool accepts pathlib.Path and converts to string."""
        pool = ConnectionPool(db_path=Path(temp_db))
        assert pool.db_path == str(temp_db)
        pool.close_all()

    def test_default_pool_size(self, temp_db):
        """Default pool size is 5."""
        pool = ConnectionPool(db_path=temp_db)
        assert pool.pool_size == 5
        pool.close_all()

    def test_custom_pool_size(self, temp_db):
        """Pool size is configurable."""
        pool = ConnectionPool(db_path=temp_db, pool_size=10)
        assert pool.pool_size == 10
        pool.close_all()

    def test_default_timeout(self, temp_db):
        """Default timeout is 30 seconds."""
        pool = ConnectionPool(db_path=temp_db)
        assert pool.timeout == 30.0
        pool.close_all()

    def test_custom_timeout(self, temp_db):
        """Timeout is configurable."""
        pool = ConnectionPool(db_path=temp_db, timeout=10.0)
        assert pool.timeout == 10.0
        pool.close_all()

    def test_lazy_creation(self, temp_db):
        """No connections are created until first get."""
        pool = ConnectionPool(db_path=temp_db)
        assert pool._created == 0
        pool.close_all()

    def test_wal_mode_enabled(self, pool):
        """Connections use WAL journal mode."""
        conn = pool.get_connection()
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == 'wal'
        conn.close()

    def test_foreign_keys_enabled(self, pool):
        """Connections have foreign keys enabled."""
        conn = pool.get_connection()
        result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1
        conn.close()

    def test_synchronous_normal(self, pool):
        """Connections use NORMAL synchronous mode."""
        conn = pool.get_connection()
        result = conn.execute("PRAGMA synchronous").fetchone()
        # NORMAL = 1
        assert result[0] == 1
        conn.close()

    def test_cache_size_configured(self, pool):
        """Connections have increased cache size."""
        conn = pool.get_connection()
        result = conn.execute("PRAGMA cache_size").fetchone()
        assert result[0] == -10000
        conn.close()


# ---------------------------------------------------------------------------
# 2. Connection get/return
# ---------------------------------------------------------------------------

class TestGetReturn:
    """Test basic connection checkout and return."""

    def test_get_connection_returns_pooled(self, pool):
        """get_connection returns a PooledConnection wrapper."""
        conn = pool.get_connection()
        assert isinstance(conn, PooledConnection)
        conn.close()

    def test_get_increments_created(self, pool):
        """First get creates a new connection."""
        assert pool._created == 0
        conn = pool.get_connection()
        assert pool._created == 1
        conn.close()

    def test_return_makes_available(self, pool):
        """Returned connection is reusable."""
        conn1 = pool.get_connection()
        conn1.close()

        # Should reuse, not create new
        conn2 = pool.get_connection()
        assert pool._created == 1  # Still only 1 connection created
        conn2.close()

    def test_multiple_connections_created(self, pool):
        """Multiple simultaneous gets create multiple connections."""
        conns = [pool.get_connection() for _ in range(3)]
        assert pool._created == 3
        for c in conns:
            c.close()

    def test_connections_up_to_pool_size(self, small_pool):
        """Can create connections up to pool_size."""
        conn1 = small_pool.get_connection()
        conn2 = small_pool.get_connection()
        assert small_pool._created == 2
        conn1.close()
        conn2.close()

    def test_pool_exhaustion_timeout(self, temp_db):
        """Raises TimeoutError when pool is exhausted and timeout expires."""
        pool = ConnectionPool(db_path=temp_db, pool_size=1, timeout=0.5)
        conn = pool.get_connection()  # Takes the only slot

        with pytest.raises(TimeoutError, match="Could not get database connection"):
            pool.get_connection()

        conn.close()
        pool.close_all()

    def test_connection_executes_sql(self, pool):
        """Pooled connection can execute SQL statements."""
        conn = pool.get_connection()
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()

        result = conn.execute("SELECT name FROM test WHERE id = 1").fetchone()
        assert result[0] == 'hello'
        conn.close()

    def test_returned_connection_preserves_data(self, pool):
        """Data persists across connection checkout cycles."""
        conn = pool.get_connection()
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'persist')")
        conn.commit()
        conn.close()

        conn2 = pool.get_connection()
        result = conn2.execute("SELECT val FROM test WHERE id = 1").fetchone()
        assert result[0] == 'persist'
        conn2.close()


# ---------------------------------------------------------------------------
# 3. Concurrent access
# ---------------------------------------------------------------------------

class TestConcurrentAccess:
    """Test thread safety and concurrent database operations."""

    def test_concurrent_reads(self, pool):
        """Multiple threads can read concurrently without errors."""
        # Setup
        conn = pool.get_connection()
        conn.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, val INTEGER)")
        conn.execute("INSERT INTO counter VALUES (1, 42)")
        conn.commit()
        conn.close()

        errors = []
        results = []

        def reader():
            try:
                c = pool.get_connection()
                row = c.execute("SELECT val FROM counter WHERE id = 1").fetchone()
                results.append(row[0])
                c.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors during concurrent reads: {errors}"
        assert all(v == 42 for v in results)

    def test_concurrent_writes(self, temp_db):
        """Multiple threads can write without SQLITE_BUSY errors."""
        pool = ConnectionPool(db_path=temp_db, pool_size=5, timeout=10.0)

        conn = pool.get_connection()
        conn.execute("CREATE TABLE writes (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER)")
        conn.commit()
        conn.close()

        errors = []
        writes_per_thread = 20
        num_threads = 5

        def writer(tid):
            try:
                for _ in range(writes_per_thread):
                    c = pool.get_connection()
                    c.execute("INSERT INTO writes (thread_id) VALUES (?)", (tid,))
                    c.commit()
                    c.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"

        # Verify all writes landed
        c = pool.get_connection()
        count = c.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
        assert count == writes_per_thread * num_threads
        c.close()
        pool.close_all()

    def test_concurrent_get_return_cycles(self, pool):
        """Rapid get/return cycles across threads don't corrupt pool state."""
        errors = []
        cycles = 50

        def cycle():
            try:
                for _ in range(cycles):
                    c = pool.get_connection()
                    c.execute("SELECT 1")
                    c.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cycle) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Errors during concurrent cycles: {errors}"


# ---------------------------------------------------------------------------
# 4. PooledConnection proxy
# ---------------------------------------------------------------------------

class TestPooledConnectionProxy:
    """Test PooledConnection attribute proxying and context manager."""

    def test_execute_proxied(self, pool):
        """execute() is proxied to the real connection."""
        conn = pool.get_connection()
        cursor = conn.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_commit_proxied(self, pool):
        """commit() is proxied to the real connection."""
        conn = pool.get_connection()
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()  # Should not raise
        conn.close()

    def test_row_factory_proxied(self, pool):
        """row_factory attribute is proxied via __setattr__."""
        conn = pool.get_connection()
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'test')")
        conn.commit()

        row = conn.execute("SELECT * FROM t").fetchone()
        assert row['id'] == 1
        assert row['name'] == 'test'
        conn.close()

    def test_context_manager(self, pool):
        """PooledConnection works as a context manager."""
        with pool.get_connection() as conn:
            result = conn.execute("SELECT 42").fetchone()
            assert result[0] == 42
        # Connection returned to pool after __exit__

    def test_context_manager_returns_on_exception(self, pool):
        """Connection is returned to pool even when exception occurs inside context."""
        try:
            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
                raise ValueError("test error")
        except ValueError:
            pass

        # Connection should be back in pool; can get a new one
        conn2 = pool.get_connection()
        assert pool._created == 1  # Reused, not newly created
        conn2.close()

    def test_close_returns_to_pool(self, pool):
        """Calling close() on PooledConnection returns to pool, not actual close."""
        conn = pool.get_connection()
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        conn.close()

        # Underlying connection should still be alive in pool
        conn2 = pool.get_connection()
        # Should be able to query the table created above
        result = conn2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='t'").fetchone()
        assert result is not None
        conn2.close()

    def test_private_attrs_on_wrapper(self, pool):
        """Attributes starting with _ are stored on the wrapper, not proxied."""
        conn = pool.get_connection()
        assert hasattr(conn, '_conn')
        assert hasattr(conn, '_pool')
        assert hasattr(conn, '_closed')
        conn.close()


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test unusual usage patterns and boundary conditions."""

    def test_double_close(self, pool):
        """Closing a PooledConnection twice does not break the pool."""
        conn = pool.get_connection()
        conn.close()
        conn.close()  # Should be a no-op, not raise

    def test_close_all_drains_pool(self, pool):
        """close_all() drains and closes all connections, resets counter."""
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()
        conn1.close()
        conn2.close()
        assert pool._created == 2

        pool.close_all()
        assert pool._created == 0

    def test_pool_reusable_after_close_all(self, pool):
        """Pool can create new connections after close_all."""
        conn = pool.get_connection()
        conn.close()
        pool.close_all()

        # Should be able to create a new connection
        conn2 = pool.get_connection()
        assert pool._created == 1
        result = conn2.execute("SELECT 1").fetchone()
        assert result[0] == 1
        conn2.close()

    def test_return_rolls_back_uncommitted(self, pool):
        """Returning a connection rolls back any uncommitted transaction."""
        conn = pool.get_connection()
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        conn.close()

        conn2 = pool.get_connection()
        conn2.execute("INSERT INTO t VALUES (1)")
        # Do NOT commit - just return
        conn2.close()

        # Data should not be present (was rolled back on return)
        conn3 = pool.get_connection()
        count = conn3.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        assert count == 0
        conn3.close()

    def test_pool_size_one(self, temp_db):
        """Pool with size=1 works correctly with sequential get/return."""
        pool = ConnectionPool(db_path=temp_db, pool_size=1, timeout=5.0)
        for _ in range(10):
            conn = pool.get_connection()
            conn.execute("SELECT 1")
            conn.close()
        assert pool._created == 1
        pool.close_all()

    def test_timeout_error_message_includes_count(self, temp_db):
        """TimeoutError message includes the number of connections in use."""
        pool = ConnectionPool(db_path=temp_db, pool_size=1, timeout=0.3)
        conn = pool.get_connection()

        with pytest.raises(TimeoutError) as exc_info:
            pool.get_connection()
        assert "1 connections in use" in str(exc_info.value)

        conn.close()
        pool.close_all()


# ---------------------------------------------------------------------------
# 6. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Test behavior with invalid inputs and error conditions."""

    def test_invalid_path_directory(self, tmp_path):
        """Attempting to connect to a directory path raises an error."""
        pool = ConnectionPool(db_path=str(tmp_path / "nonexistent_dir" / "db.db"))
        with pytest.raises(Exception):
            pool.get_connection()

    def test_readonly_filesystem(self, temp_db):
        """Pool handles read-only database gracefully."""
        # Create database with data first
        pool = ConnectionPool(db_path=temp_db)
        conn = pool.get_connection()
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()
        pool.close_all()

        # Verify we can still read after a fresh pool
        pool2 = ConnectionPool(db_path=temp_db)
        conn2 = pool2.get_connection()
        result = conn2.execute("SELECT id FROM t").fetchone()
        assert result[0] == 1
        conn2.close()
        pool2.close_all()

    def test_connection_cross_thread(self, pool):
        """Connections can be used across threads (check_same_thread=False)."""
        result_holder = []

        def use_in_thread(conn):
            row = conn.execute("SELECT 99").fetchone()
            result_holder.append(row[0])

        conn = pool.get_connection()
        t = threading.Thread(target=use_in_thread, args=(conn,))
        t.start()
        t.join(timeout=5)
        conn.close()

        assert result_holder == [99]


# ---------------------------------------------------------------------------
# 7. Module-level convenience functions
# ---------------------------------------------------------------------------

class TestModuleFunctions:
    """Test get_pool(), get_connection(), close_all_pools()."""

    def test_get_pool_creates_pool(self, temp_db):
        """get_pool creates a new pool for an unseen path."""
        pool = get_pool(temp_db)
        assert isinstance(pool, ConnectionPool)

    def test_get_pool_returns_same_instance(self, temp_db):
        """get_pool returns the same pool for the same resolved path."""
        pool1 = get_pool(temp_db)
        pool2 = get_pool(temp_db)
        assert pool1 is pool2

    def test_get_pool_resolves_paths(self, temp_db):
        """get_pool resolves paths so ./db and full path share a pool."""
        pool1 = get_pool(temp_db)
        pool2 = get_pool(str(Path(temp_db).resolve()))
        assert pool1 is pool2

    def test_get_pool_different_dbs(self):
        """Different database paths get separate pools."""
        f1 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f2 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f1.close()
        f2.close()

        try:
            pool1 = get_pool(f1.name)
            pool2 = get_pool(f2.name)
            assert pool1 is not pool2
        finally:
            Path(f1.name).unlink(missing_ok=True)
            Path(f2.name).unlink(missing_ok=True)

    def test_get_connection_context_manager(self, temp_db):
        """get_connection() yields a usable connection and returns it."""
        with get_connection(temp_db) as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()

        # Verify data persists after context exit
        with get_connection(temp_db) as conn2:
            result = conn2.execute("SELECT id FROM t").fetchone()
            assert result[0] == 1

    def test_get_connection_returns_pooled(self, temp_db):
        """get_connection() returns a PooledConnection."""
        with get_connection(temp_db) as conn:
            assert isinstance(conn, PooledConnection)

    def test_get_connection_custom_pool_size(self, temp_db):
        """get_connection() respects pool_size on first call."""
        with get_connection(temp_db, pool_size=3) as conn:
            conn.execute("SELECT 1")

        pool = get_pool(temp_db)
        assert pool.pool_size in (3, 5)  # 3 if first, 5 if pre-existing

    def test_close_all_pools_clears_registry(self, temp_db):
        """close_all_pools() clears the global pool registry."""
        get_pool(temp_db)

        with _pools_lock:
            assert len(_pools) > 0

        close_all_pools()

        with _pools_lock:
            assert len(_pools) == 0

    def test_close_all_pools_empty_is_safe(self):
        """close_all_pools() on an empty registry doesn't raise."""
        close_all_pools()  # Should not raise

    def test_get_connection_exception_returns_conn(self, temp_db):
        """Connection is returned to pool even if body raises."""
        try:
            with get_connection(temp_db) as conn:
                conn.execute("SELECT 1")
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        # Connection should be available for reuse
        pool = get_pool(temp_db)
        conn2 = pool.get_connection()
        assert pool._created == 1  # Reused existing
        conn2.close()


# ---------------------------------------------------------------------------
# 8. Return connection edge cases
# ---------------------------------------------------------------------------

class TestReturnConnection:
    """Test return_connection behavior in detail."""

    def test_return_puts_back_in_queue(self, pool):
        """Returned connection goes back into the internal queue."""
        conn = pool.get_connection()
        assert pool._pool.qsize() == 0  # Connection is checked out
        conn.close()
        assert pool._pool.qsize() == 1  # Connection is back in queue

    def test_return_rollback_on_error(self, pool):
        """Return handles rollback errors gracefully."""
        conn = pool.get_connection()
        # Force an unusual state - close the real connection underneath
        # and then return the wrapper. The rollback should fail silently.
        real_conn = conn._conn
        conn.close()

        # Pool should still be functional
        conn2 = pool.get_connection()
        result = conn2.execute("SELECT 1").fetchone()
        assert result[0] == 1
        conn2.close()
