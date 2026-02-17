"""
Circuit breaker for LLM calls

Protects against cascading failures when Claude CLI or other LLM backends
are unresponsive. Three states:

  CLOSED  -- calls pass through normally; failures are counted
  OPEN    -- calls are rejected immediately with CircuitBreakerOpenError
  HALF_OPEN -- one probe call is allowed; success closes, failure reopens

Usage:
    from memory_system.circuit_breaker import get_breaker, CircuitBreakerOpenError

    breaker = get_breaker('llm_extraction')
    try:
        result = breaker.call(subprocess.run, ["claude", "-p", prompt], ...)
    except CircuitBreakerOpenError:
        logger.warning("Circuit breaker open, using fallback")
        result = fallback_value
"""

import threading
import time
from typing import Any, Callable


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    """
    Circuit breaker state machine for protecting LLM call sites.

    Args:
        failure_threshold: Consecutive failures before opening (default 3)
        recovery_timeout: Seconds to wait before probing in HALF_OPEN (default 60)
        name: Identifier for this breaker instance (default 'default')
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Current breaker state, accounting for recovery timeout."""
        with self._lock:
            if (
                self._state == self.OPEN
                and self._last_failure_time > 0
                and (time.monotonic() - self._last_failure_time) >= self.recovery_timeout
            ):
                self._state = self.HALF_OPEN
            return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute fn through the circuit breaker.

        In CLOSED / HALF_OPEN: fn is called.  On success the breaker
        closes (if half-open) or stays closed.  On exception the failure
        is recorded and the exception re-raised.

        In OPEN: raises CircuitBreakerOpenError immediately without
        calling fn.
        """
        current = self.state  # triggers timeout check

        if current == self.OPEN:
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
            self._last_failure_time = 0.0

    # -- internal helpers --------------------------------------------------

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED


# ---------------------------------------------------------------------------
# Module-level singleton registry
# ---------------------------------------------------------------------------

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """
    Get or create a named CircuitBreaker singleton.

    First call with a given name creates the instance; subsequent calls
    return the same object regardless of threshold/timeout args.
    """
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                name=name,
            )
        return _registry[name]


def reset_all() -> None:
    """Clear the entire singleton registry (mainly for tests)."""
    with _registry_lock:
        _registry.clear()
