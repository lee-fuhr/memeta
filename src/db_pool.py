"""
SQLite Connection Pooling

Fixes P2 performance issue: Prevents SQLITE_BUSY errors under concurrent operations.

Problem:
- Every module creates raw sqlite3.connect() calls
- Concurrent access causes lock contention
- SQLITE_BUSY errors and retry loops

Solution:
- Connection pool with configurable size
- Automatic timeout + retry with exponential backoff
- Context manager for safe resource management

Usage:
    from db_pool import get_connection

    with get_connection(db_path) as conn:
        cursor = conn.execute("SELECT ...")
        # Connection automatically returned to pool
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional
from pathlib import Path
from queue import Queue, Empty


class PooledConnection:
    """
    Wrapper around SQLite connection that returns to pool on close().

    Makes connection pooling transparent to existing code that calls conn.close().
    """

    def __init__(self, conn: sqlite3.Connection, pool: 'ConnectionPool'):
        self._conn = conn
        self._pool = pool
        self._closed = False

    def __getattr__(self, name):
        """Proxy all other methods to the real connection."""
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        """Proxy attribute writes to the real connection."""
        if name.startswith('_'):
            # Private attributes go to wrapper
            super().__setattr__(name, value)
        else:
            # Public attributes go to underlying connection
            setattr(self._conn, name, value)

    def close(self):
        """Return connection to pool instead of closing."""
        if not self._closed:
            self._pool.return_connection(self._conn)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class ConnectionPool:
    """
    Thread-safe SQLite connection pool.

    Features:
    - Fixed pool size (default 5 connections)
    - Automatic connection creation on demand
    - Thread-safe borrowing/returning
    - Timeout + exponential backoff retry
    - WAL mode enabled for better concurrency
    """

    def __init__(self, db_path: str, pool_size: int = 5, timeout: float = 30.0):
        """
        Initialize connection pool.

        Args:
            db_path: Path to SQLite database
            pool_size: Maximum concurrent connections
            timeout: Max seconds to wait for connection
        """
        self.db_path = str(db_path)
        self.pool_size = pool_size
        self.timeout = timeout
        self._pool = Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._created = 0

        # Pre-create connections (lazy: create on first get)

    def _create_connection(self) -> sqlite3.Connection:
        """Create new SQLite connection with optimal settings."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False  # Allow cross-thread usage (pool manages safety)
        )

        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")

        # Faster synchronous mode (still safe with WAL)
        conn.execute("PRAGMA synchronous=NORMAL")

        # Increase cache size (10MB)
        conn.execute("PRAGMA cache_size=-10000")

        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")

        return conn

    def get_connection(self) -> sqlite3.Connection:
        """
        Get connection from pool (or create new if under pool_size).

        Returns:
            SQLite connection

        Raises:
            TimeoutError: If no connection available within timeout
        """
        start_time = time.time()
        retry_delays = [0.1, 0.2, 0.5, 1.0, 2.0]  # Exponential backoff
        retry_count = 0

        while time.time() - start_time < self.timeout:
            try:
                # Try to get existing connection from pool
                conn = self._pool.get(block=False)
                return PooledConnection(conn, self)

            except Empty:
                # Pool empty - try to create new connection if under limit
                with self._lock:
                    if self._created < self.pool_size:
                        conn = self._create_connection()
                        self._created += 1
                        return PooledConnection(conn, self)

                # Pool full - wait and retry with exponential backoff
                delay = retry_delays[min(retry_count, len(retry_delays) - 1)]
                time.sleep(delay)
                retry_count += 1

        raise TimeoutError(
            f"Could not get database connection after {self.timeout}s "
            f"({self._created} connections in use)"
        )

    def return_connection(self, conn: sqlite3.Connection):
        """
        Return connection to pool.

        Args:
            conn: SQLite connection to return
        """
        # Rollback any uncommitted transaction
        try:
            conn.rollback()
        except Exception:
            pass  # Ignore errors (connection might be closed)

        # Return to pool
        try:
            self._pool.put(conn, block=False)
        except Exception:
            # Pool full (shouldn't happen) - close connection
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created -= 1

    def close_all(self):
        """Close all connections in pool (for shutdown)."""
        connections = []

        # Drain pool
        while True:
            try:
                conn = self._pool.get(block=False)
                connections.append(conn)
            except Empty:
                break

        # Close all
        for conn in connections:
            try:
                conn.close()
            except Exception:
                pass

        with self._lock:
            self._created = 0


# Global pools (one per database path)
_pools = {}
_pools_lock = threading.Lock()


def get_pool(db_path: str, pool_size: int = 5) -> ConnectionPool:
    """
    Get or create connection pool for database.

    Args:
        db_path: Path to SQLite database
        pool_size: Maximum concurrent connections

    Returns:
        ConnectionPool instance
    """
    db_path = str(Path(db_path).resolve())

    with _pools_lock:
        if db_path not in _pools:
            _pools[db_path] = ConnectionPool(db_path, pool_size)

        return _pools[db_path]


@contextmanager
def get_connection(db_path: str, pool_size: int = 5):
    """
    Context manager for getting pooled connection.

    Usage:
        with get_connection("path/to/db.db") as conn:
            cursor = conn.execute("SELECT ...")

    Args:
        db_path: Path to SQLite database
        pool_size: Maximum concurrent connections

    Yields:
        SQLite connection (auto-returned to pool on exit)
    """
    pool = get_pool(db_path, pool_size)
    conn = pool.get_connection()

    try:
        yield conn
    finally:
        pool.return_connection(conn)


def close_all_pools():
    """Close all connection pools (for shutdown)."""
    with _pools_lock:
        for pool in _pools.values():
            pool.close_all()
        _pools.clear()
