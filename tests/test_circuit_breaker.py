"""
Tests for circuit breaker protecting LLM calls

TDD: These tests were written before the implementation.
Tests cover state machine transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED),
failure threshold behavior, recovery timeout, and the singleton registry.
"""

import time
import pytest

from memory_system.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_breaker,
    reset_all,
)


class TestCircuitBreakerStateMachine:
    """Core state machine tests for the circuit breaker."""

    def setup_method(self):
        """Fresh breaker for each test."""
        reset_all()
        self.breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.5,  # Short for testing
            name="test",
        )

    def test_closed_state_passes_calls_through(self):
        """CLOSED state should pass calls through and return their result."""
        result = self.breaker.call(lambda x: x * 2, 21)
        assert result == 42
        assert self.breaker.state == "CLOSED"
        assert self.breaker.failure_count == 0

    def test_opens_after_3_consecutive_failures(self):
        """Breaker should transition from CLOSED to OPEN after failure_threshold consecutive failures."""
        def failing():
            raise RuntimeError("LLM timeout")

        for i in range(3):
            with pytest.raises(RuntimeError):
                self.breaker.call(failing)

        assert self.breaker.state == "OPEN"
        assert self.breaker.failure_count == 3
        assert self.breaker.is_open is True

    def test_open_state_raises_CircuitBreakerOpenError_immediately(self):
        """OPEN state should raise CircuitBreakerOpenError without calling the function."""
        call_count = 0

        def tracked_fn():
            nonlocal call_count
            call_count += 1
            return "should not run"

        # Force open
        for _ in range(3):
            self.breaker.record_failure()

        assert self.breaker.state == "OPEN"

        with pytest.raises(CircuitBreakerOpenError):
            self.breaker.call(tracked_fn)

        assert call_count == 0  # Function was never called

    def test_transitions_to_half_open_after_recovery_timeout(self):
        """After recovery_timeout elapses, breaker should move from OPEN to HALF_OPEN."""
        # Force open
        for _ in range(3):
            self.breaker.record_failure()

        assert self.breaker.state == "OPEN"

        # Wait for recovery timeout (0.5s)
        time.sleep(0.6)

        # Next call attempt should go through (HALF_OPEN lets one call through)
        result = self.breaker.call(lambda: "recovered")
        assert result == "recovered"
        assert self.breaker.state == "CLOSED"

    def test_closes_again_after_success_in_half_open(self):
        """A success in HALF_OPEN state should transition back to CLOSED with reset counters."""
        # Force open
        for _ in range(3):
            self.breaker.record_failure()

        assert self.breaker.state == "OPEN"

        # Wait for recovery
        time.sleep(0.6)

        # Successful call in half-open
        self.breaker.call(lambda: "ok")

        assert self.breaker.state == "CLOSED"
        assert self.breaker.failure_count == 0
        assert self.breaker.is_open is False

    def test_reset_returns_to_closed(self):
        """Manual reset() should return breaker to CLOSED regardless of current state."""
        # Force open
        for _ in range(3):
            self.breaker.record_failure()

        assert self.breaker.state == "OPEN"
        assert self.breaker.failure_count == 3

        self.breaker.reset()

        assert self.breaker.state == "CLOSED"
        assert self.breaker.failure_count == 0
        assert self.breaker.is_open is False


class TestCircuitBreakerRegistry:
    """Tests for the module-level singleton registry."""

    def setup_method(self):
        reset_all()

    def test_get_breaker_returns_same_instance(self):
        """get_breaker with same name should return the same instance."""
        b1 = get_breaker("llm_extraction")
        b2 = get_breaker("llm_extraction")
        assert b1 is b2

    def test_get_breaker_different_names_different_instances(self):
        """get_breaker with different names should return distinct instances."""
        b1 = get_breaker("extraction")
        b2 = get_breaker("dedup")
        assert b1 is not b2

    def test_reset_all_clears_registry(self):
        """reset_all should clear the singleton registry."""
        b1 = get_breaker("test1")
        b1.record_failure()
        reset_all()
        b2 = get_breaker("test1")
        assert b2.failure_count == 0
        assert b1 is not b2


class TestCircuitBreakerEdgeCases:
    """Edge cases and additional behavior."""

    def setup_method(self):
        reset_all()

    def test_success_resets_failure_count(self):
        """A success in CLOSED state should reset the consecutive failure counter."""
        breaker = CircuitBreaker(failure_threshold=3, name="edge")

        # 2 failures (not enough to open)
        for _ in range(2):
            breaker.record_failure()
        assert breaker.failure_count == 2

        # 1 success resets counter
        breaker.record_success()
        assert breaker.failure_count == 0

        # 2 more failures should NOT open (counter was reset)
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == "CLOSED"

    def test_half_open_failure_reopens(self):
        """A failure in HALF_OPEN state should immediately reopen the breaker."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.3,
            name="half_open_fail",
        )

        # Force open
        for _ in range(3):
            breaker.record_failure()

        # Wait for half-open
        time.sleep(0.4)

        # Failing call in half-open should reopen
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError("still broken")))

        assert breaker.state == "OPEN"

    def test_call_passes_args_and_kwargs(self):
        """call() should correctly forward positional and keyword arguments."""
        breaker = CircuitBreaker(name="args_test")

        def add(a, b, extra=0):
            return a + b + extra

        result = breaker.call(add, 1, 2, extra=10)
        assert result == 13
