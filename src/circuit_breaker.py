"""
Circuit breaker for LLM calls

Protects against cascading failures when Claude CLI or other LLM backends
are unresponsive. Three states:

  CLOSED    -- calls pass through normally; failures are counted
  OPEN      -- calls are rejected immediately (fallback or CircuitBreakerOpenError)
  HALF_OPEN -- one probe call is allowed; success closes, failure reopens

State is persisted in SQLite (intelligence.db by default) so that breaker
state survives process restarts.

Usage:
    from memory_system.circuit_breaker import get_breaker, CircuitBreakerOpenError

    breaker = get_breaker('llm_extraction')
    try:
        result = breaker.call(subprocess.run, ["claude", "-p", prompt], ...)
    except CircuitBreakerOpenError:
        logger.warning("Circuit breaker open, using fallback")
        result = fallback_value

    # Or with built-in fallback:
    result = breaker.call(risky_fn, fallback=default_value)
"""

import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Optional


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN."""
    pass


_SENTINEL = object()  # distinguishes "no fallback given" from fallback=None

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    name TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'closed',
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_at INTEGER,
    opened_at INTEGER,
    updated_at INTEGER NOT NULL
);
"""


def _now_ts() -> int:
    """Current time as integer epoch seconds."""
    return int(time.time())


class CircuitBreaker:
    """
    Circuit breaker state machine for protecting LLM call sites.

    Args:
        name: Identifier for this breaker instance
        db_path: SQLite database path for persistence (None = in-memory only)
        failure_threshold: Consecutive failures before opening (default 5)
        recovery_timeout: Seconds to wait before probing in HALF_OPEN (default 600)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        db_path: Optional[str] = None,
        failure_threshold: int = 5,
        recovery_timeout: float = 600.0,
    ):
        self.name = name
        self.db_path = db_path
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_at: Optional[int] = None
        self._opened_at: Optional[float] = None  # float for sub-second precision
        self._updated_at: int = _now_ts()
        self._lock = threading.Lock()

        # Initialise DB table and load persisted state
        if self.db_path:
            self._init_db()
            self._load_state()

    # -- DB helpers -----------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Get a short-lived connection for a single operation."""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """Ensure the circuit_breaker_state table exists."""
        conn = self._get_conn()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _load_state(self) -> None:
        """Load persisted state from DB (if any row exists for this name)."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT state, failure_count, last_failure_at, opened_at, updated_at "
                "FROM circuit_breaker_state WHERE name = ?",
                (self.name,),
            ).fetchone()
            if row:
                self._state = row[0]
                self._failure_count = row[1]
                self._last_failure_at = row[2]
                # Convert opened_at from int (DB) to float (memory) for timing
                self._opened_at = float(row[3]) if row[3] is not None else None
                self._updated_at = row[4]
        finally:
            conn.close()

    def _persist_state(self) -> None:
        """Write current in-memory state to DB."""
        if not self.db_path:
            return
        conn = self._get_conn()
        try:
            # Convert opened_at float to int for DB storage
            opened_at_db = int(self._opened_at) if self._opened_at is not None else None
            conn.execute(
                "INSERT INTO circuit_breaker_state "
                "(name, state, failure_count, last_failure_at, opened_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "state=excluded.state, failure_count=excluded.failure_count, "
                "last_failure_at=excluded.last_failure_at, opened_at=excluded.opened_at, "
                "updated_at=excluded.updated_at",
                (
                    self.name,
                    self._state,
                    self._failure_count,
                    self._last_failure_at,
                    opened_at_db,
                    self._updated_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # -- Public API -----------------------------------------------------------

    @property
    def state(self) -> str:
        """Current breaker state, accounting for recovery timeout."""
        with self._lock:
            self._check_recovery()
            return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN

    def get_state(self) -> str:
        """Return current state as a string: 'closed', 'open', or 'half_open'."""
        return self.state

    def get_stats(self) -> Dict[str, Any]:
        """Return a dict with state, failures, and timestamps."""
        with self._lock:
            self._check_recovery()
            return {
                "name": self.name,
                "state": self._state,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "last_failure_at": self._last_failure_at,
                "opened_at": self._opened_at,
                "updated_at": self._updated_at,
            }

    def call(self, fn: Callable, *args: Any, fallback: Any = _SENTINEL, **kwargs: Any) -> Any:
        """
        Execute *fn* through the circuit breaker.

        In CLOSED / HALF_OPEN: fn is called.  On success the breaker
        closes (if half-open) or stays closed.  On exception the failure
        is recorded and the exception re-raised.

        In OPEN: if *fallback* was provided it is returned immediately;
        otherwise ``CircuitBreakerOpenError`` is raised.

        Args:
            fn: Callable to execute
            *args: Positional arguments for fn
            fallback: Value to return when the breaker is OPEN.  If not
                      supplied, CircuitBreakerOpenError is raised instead.
                      Pass fallback=None explicitly to get None back.
            **kwargs: Keyword arguments for fn
        """
        current = self.state  # triggers timeout check

        if current == self.OPEN:
            if fallback is not _SENTINEL:
                return fallback
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN "
                f"({self._failure_count} consecutive failures)"
            )

        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise

        self._on_success()
        return result

    def record_failure(self) -> None:
        """Manually record a failure (increments counter, may open breaker)."""
        self._on_failure()

    def record_success(self) -> None:
        """Manually record a success (resets failure counter, may close breaker)."""
        self._on_success()

    def reset(self) -> None:
        """Force the breaker back to CLOSED with zero failures."""
        with self._lock:
            self._state = self.CLOSED
            self._failure_count = 0
            self._last_failure_at = None
            self._opened_at = None
            self._updated_at = _now_ts()
            self._persist_state()

    # -- internal helpers ----------------------------------------------------

    def _check_recovery(self) -> None:
        """Transition OPEN -> HALF_OPEN when recovery_timeout has elapsed.

        Must be called under self._lock.
        """
        if self._state == self.OPEN and self._opened_at is not None:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self._state = self.HALF_OPEN
                self._updated_at = _now_ts()
                self._persist_state()

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            now = time.time()
            self._last_failure_at = int(now)
            self._updated_at = int(now)
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = now  # float for sub-second recovery precision
            self._persist_state()

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED
            self._opened_at = None
            self._updated_at = _now_ts()
            self._persist_state()


# ---------------------------------------------------------------------------
# Module-level singleton registry
# ---------------------------------------------------------------------------

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    db_path: Optional[str] = None,
    failure_threshold: int = 5,
    recovery_timeout: float = 600.0,
) -> CircuitBreaker:
    """
    Get or create a named CircuitBreaker singleton.

    First call with a given name creates the instance; subsequent calls
    return the same object regardless of threshold/timeout args.
    """
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name=name,
                db_path=db_path,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return _registry[name]


def reset_all() -> None:
    """Clear the entire singleton registry (mainly for tests)."""
    with _registry_lock:
        _registry.clear()
