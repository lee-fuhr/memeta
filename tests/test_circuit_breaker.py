"""
Tests for the circuit breaker module.

Covers:
- State transitions (closed -> open -> half_open -> closed)
- Failure counting and threshold
- Recovery timeout
- Fallback behavior
- SQLite persistence across restarts
- get_state() and get_stats() API
- reset() forced close
- Singleton registry
- Full lifecycle
"""

import sqlite3
import time

import pytest

from memory_system.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_breaker,
    reset_all,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear the singleton registry before and after each test."""
    reset_all()
    yield
    reset_all()


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database file."""
    return str(tmp_path / "test_cb.db")


# ---------------------------------------------------------------------------
# 1. Initial state is closed
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.get_state() == "closed"

    def test_initial_failure_count_is_zero(self):
        cb = CircuitBreaker(name="test")
        assert cb.failure_count == 0

    def test_initial_is_open_is_false(self):
        cb = CircuitBreaker(name="test")
        assert cb.is_open is False


# ---------------------------------------------------------------------------
# 2. Successful calls don't increment failure count
# ---------------------------------------------------------------------------

class TestSuccessfulCalls:
    def test_success_keeps_state_closed(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.get_state() == "closed"
        assert cb.failure_count == 0

    def test_success_after_failures_resets_count(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.failure_count == 4
        cb.call(lambda: "ok")
        assert cb.failure_count == 0
        assert cb.get_state() == "closed"


# ---------------------------------------------------------------------------
# 3. Failure increments count
# ---------------------------------------------------------------------------

class TestFailureCounting:
    def test_failure_increments_count(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        with pytest.raises(ValueError):
            cb.call(self._raise_value_error)
        assert cb.failure_count == 1

    def test_multiple_failures_accumulate(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(self._raise_value_error)
        assert cb.failure_count == 3

    def test_manual_record_failure(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

    @staticmethod
    def _raise_value_error():
        raise ValueError("boom")


# ---------------------------------------------------------------------------
# 4. After threshold failures, state becomes open
# ---------------------------------------------------------------------------

class TestThresholdOpening:
    def test_opens_at_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(5):
            cb.record_failure()
        assert cb.get_state() == "open"
        assert cb.is_open is True

    def test_does_not_open_below_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.get_state() == "closed"
        assert cb.is_open is False

    def test_custom_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.get_state() == "open"


# ---------------------------------------------------------------------------
# 5. Open state returns fallback without calling fn
# ---------------------------------------------------------------------------

class TestOpenStateFallback:
    def test_open_raises_without_fallback(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        assert cb.get_state() == "open"
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(lambda: "should not run")

    def test_open_returns_fallback(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        result = cb.call(lambda: "should not run", fallback="default")
        assert result == "default"

    def test_open_does_not_call_fn(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        call_log = []
        result = cb.call(lambda: call_log.append(1) or "called", fallback="safe")
        assert result == "safe"
        assert call_log == []

    def test_fallback_none_is_valid(self):
        """fallback=None should return None, not raise."""
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        result = cb.call(lambda: "nope", fallback=None)
        assert result is None


# ---------------------------------------------------------------------------
# 6. After recovery_timeout, transitions to half-open
# ---------------------------------------------------------------------------

class TestRecoveryTimeout:
    def test_transitions_to_half_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.get_state() == "open"
        time.sleep(0.15)
        assert cb.get_state() == "half_open"


# ---------------------------------------------------------------------------
# 7. Half-open: success closes circuit
# ---------------------------------------------------------------------------

class TestHalfOpenSuccess:
    def test_half_open_success_closes(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        assert cb.get_state() == "open"
        time.sleep(0.1)
        assert cb.get_state() == "half_open"
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.get_state() == "closed"
        assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# 8. Half-open: failure reopens circuit
# ---------------------------------------------------------------------------

class TestHalfOpenFailure:
    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        time.sleep(0.1)
        assert cb.get_state() == "half_open"
        with pytest.raises(RuntimeError):
            cb.call(self._fail)
        assert cb.get_state() == "open"

    @staticmethod
    def _fail():
        raise RuntimeError("still broken")


# ---------------------------------------------------------------------------
# 9. State persists across restarts (same db_path)
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_state_persists_to_db(self, tmp_db):
        cb1 = CircuitBreaker(name="persist_test", db_path=tmp_db, failure_threshold=3)
        cb1.record_failure()
        cb1.record_failure()
        assert cb1.failure_count == 2

        cb2 = CircuitBreaker(name="persist_test", db_path=tmp_db, failure_threshold=3)
        assert cb2.failure_count == 2
        assert cb2.get_state() == "closed"

    def test_open_state_persists(self, tmp_db):
        cb1 = CircuitBreaker(name="persist_open", db_path=tmp_db, failure_threshold=2)
        cb1.record_failure()
        cb1.record_failure()
        assert cb1.get_state() == "open"

        cb2 = CircuitBreaker(name="persist_open", db_path=tmp_db, failure_threshold=2)
        assert cb2.get_state() == "open"
        assert cb2.failure_count == 2

    def test_reset_persists(self, tmp_db):
        cb1 = CircuitBreaker(name="persist_reset", db_path=tmp_db, failure_threshold=1)
        cb1.record_failure()
        assert cb1.get_state() == "open"
        cb1.reset()

        cb2 = CircuitBreaker(name="persist_reset", db_path=tmp_db, failure_threshold=1)
        assert cb2.get_state() == "closed"
        assert cb2.failure_count == 0

    def test_no_db_works_fine(self):
        """Without db_path, breaker works purely in-memory."""
        cb = CircuitBreaker(name="no_db")
        cb.record_failure()
        assert cb.failure_count == 1

    def test_db_table_schema(self, tmp_db):
        """Verify the schema is created correctly."""
        CircuitBreaker(name="schema_test", db_path=tmp_db)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='circuit_breaker_state'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        schema = row[0]
        assert "name TEXT PRIMARY KEY" in schema
        assert "failure_count INTEGER" in schema


# ---------------------------------------------------------------------------
# 10. reset() forces closed
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_from_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        assert cb.get_state() == "open"
        cb.reset()
        assert cb.get_state() == "closed"
        assert cb.failure_count == 0

    def test_reset_from_closed_clears_failures(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.reset()
        assert cb.failure_count == 0
        assert cb.get_state() == "closed"


# ---------------------------------------------------------------------------
# 11. get_stats() returns correct data
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_stats_initial(self):
        cb = CircuitBreaker(name="stats_test", failure_threshold=5, recovery_timeout=600)
        stats = cb.get_stats()
        assert stats["name"] == "stats_test"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 5
        assert stats["recovery_timeout"] == 600
        assert stats["last_failure_at"] is None
        assert stats["opened_at"] is None
        assert isinstance(stats["updated_at"], int)

    def test_stats_after_failures(self):
        cb = CircuitBreaker(name="stats_test2", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["failure_count"] == 2
        assert stats["state"] == "closed"
        assert stats["last_failure_at"] is not None

    def test_stats_when_open(self):
        cb = CircuitBreaker(name="stats_test3", failure_threshold=1)
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["state"] == "open"
        assert stats["failure_count"] == 1
        assert stats["opened_at"] is not None


# ---------------------------------------------------------------------------
# 12. Singleton registry (get_breaker)
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_breaker_returns_same_instance(self):
        b1 = get_breaker("my_breaker")
        b2 = get_breaker("my_breaker")
        assert b1 is b2

    def test_different_names_different_instances(self):
        b1 = get_breaker("breaker_a")
        b2 = get_breaker("breaker_b")
        assert b1 is not b2

    def test_reset_all_clears_registry(self):
        b1 = get_breaker("will_be_cleared")
        reset_all()
        b2 = get_breaker("will_be_cleared")
        assert b1 is not b2

    def test_get_breaker_respects_params_on_first_call(self):
        b = get_breaker("custom", failure_threshold=10, recovery_timeout=300)
        assert b.failure_threshold == 10
        assert b.recovery_timeout == 300

    def test_get_breaker_ignores_params_on_subsequent_call(self):
        b1 = get_breaker("sticky", failure_threshold=7)
        b2 = get_breaker("sticky", failure_threshold=99)
        assert b2.failure_threshold == 7


# ---------------------------------------------------------------------------
# 13. Default parameter values match spec
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_failure_threshold_is_5(self):
        cb = CircuitBreaker(name="defaults")
        assert cb.failure_threshold == 5

    def test_default_recovery_timeout_is_600(self):
        cb = CircuitBreaker(name="defaults2")
        assert cb.recovery_timeout == 600.0


# ---------------------------------------------------------------------------
# 14. Exception propagation
# ---------------------------------------------------------------------------

class TestExceptionPropagation:
    def test_original_exception_propagated(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        with pytest.raises(TypeError, match="bad type"):
            cb.call(self._raise_type_error)
        assert cb.failure_count == 1

    def test_closed_with_fallback_still_raises_on_fn_error(self):
        """When CLOSED, fn exceptions propagate even with fallback.
        Fallback only applies when the breaker is OPEN."""
        cb = CircuitBreaker(name="test", failure_threshold=5)
        with pytest.raises(ValueError):
            cb.call(self._raise_value_error, fallback="unused")

    @staticmethod
    def _raise_type_error():
        raise TypeError("bad type")

    @staticmethod
    def _raise_value_error():
        raise ValueError("nope")


# ---------------------------------------------------------------------------
# 15. Args/kwargs forwarding
# ---------------------------------------------------------------------------

class TestArgsKwargs:
    def test_call_passes_args_and_kwargs(self):
        cb = CircuitBreaker(name="args_test")

        def add(a, b, extra=0):
            return a + b + extra

        result = cb.call(add, 1, 2, extra=10)
        assert result == 13


# ---------------------------------------------------------------------------
# 16. Full lifecycle test
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    def test_closed_to_open_to_half_open_to_closed(self):
        """Complete circuit breaker lifecycle."""
        cb = CircuitBreaker(name="lifecycle", failure_threshold=2, recovery_timeout=0.05)

        # Start closed
        assert cb.get_state() == "closed"
        result = cb.call(lambda: "ok")
        assert result == "ok"

        # Two failures -> open
        cb.record_failure()
        cb.record_failure()
        assert cb.get_state() == "open"

        # Can't call when open
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(lambda: "blocked")

        # Wait for recovery
        time.sleep(0.1)
        assert cb.get_state() == "half_open"

        # Successful probe -> closed
        result = cb.call(lambda: "back!")
        assert result == "back!"
        assert cb.get_state() == "closed"
        assert cb.failure_count == 0
