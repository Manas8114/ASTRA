"""
xapp/resilience/circuit_breaker.py
──────────────────────────────────────────────────────────────────────────────
Shared Circuit Breaker Implementation with Prometheus Metrics.

Provides a reusable circuit breaker pattern for protecting external dependencies
(gRPC services, E2 control plane, databases, etc.) with:
- Three states: CLOSED, OPEN, HALF_OPEN
- Configurable failure threshold and recovery timeout
- Prometheus metrics for observability
- Async-friendly with thread-safe state transitions
- Optional fallback callable execution

Usage:
    breaker = CircuitBreaker(
        name="twin-service",
        failure_threshold=3,
        recovery_timeout=30.0,
    )

    async def call_twin(action):
        async with breaker:
            return await grpc_call(action)

    # Or with fallback:
    result = await breaker.call(grpc_call, action, fallback=local_simulation)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Awaitable, Callable, Optional, TypeVar

from prometheus_client import Counter, Gauge, Histogram

from xapp.config import get_settings

log = logging.getLogger("astra.circuit_breaker")

T = TypeVar("T")

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_CB_STATE = Gauge(
    "astra_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    ["name"],
)

_CB_FAILURES = Counter(
    "astra_circuit_breaker_failures_total",
    "Total circuit breaker failure recordings",
    ["name"],
)

_CB_SUCCESSES = Counter(
    "astra_circuit_breaker_successes_total",
    "Total circuit breaker success recordings",
    ["name"],
)

_CB_TRANSITIONS = Counter(
    "astra_circuit_breaker_transitions_total",
    "Total circuit breaker state transitions",
    ["name", "from_state", "to_state"],
)

_CB_CALL_DURATION = Histogram(
    "astra_circuit_breaker_call_duration_seconds",
    "Duration of calls executed through circuit breaker",
    ["name", "outcome"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

_CB_FALLBACKS = Counter(
    "astra_circuit_breaker_fallbacks_total",
    "Total fallback executions",
    ["name", "fallback_type"],
)


# ── Circuit State Enum ───────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation — calls pass through
    OPEN = "open"          # Failing — calls blocked, fallback used
    HALF_OPEN = "half_open"  # Testing recovery — one probe call allowed


# ── Circuit Breaker Configuration ────────────────────────────────────────────

@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Immutable configuration for a circuit breaker."""
    name: str
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    expected_exception: type[Exception] = Exception
    success_threshold: int = 1  # successes needed in HALF_OPEN to close


# ── Circuit Breaker Core ─────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Thread-safe, async-compatible circuit breaker with Prometheus metrics.

    State Machine:
        CLOSED ──(failure_threshold reached)──► OPEN
        OPEN ──(recovery_timeout elapsed)──► HALF_OPEN
        HALF_OPEN ──(success_threshold reached)──► CLOSED
        HALF_OPEN ──(failure)──► OPEN
    """

    def __init__(
        self,
        config: CircuitBreakerConfig,
    ) -> None:
        self._config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = Lock()

        # Metrics labels
        self._metrics_name = config.name.replace(".", "_").replace("-", "_")

        # Initialize Prometheus state gauge
        _CB_STATE.labels(name=self._metrics_name).set(0)  # CLOSED = 0

        log.info(
            "Circuit breaker '%s' initialized: failure_threshold=%d, recovery_timeout=%.1fs",
            config.name, config.failure_threshold, config.recovery_timeout,
        )

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN

    def _maybe_transition_to_half_open(self) -> None:
        """Check if we should transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                log.info("Circuit breaker '%s' transitioned to HALF_OPEN (probe allowed)", self._config.name)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Internal state transition with metrics."""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state
        self._failure_count = 0
        self._success_count = 0

        # Update Prometheus state gauge
        state_value = {"closed": 0, "half_open": 1, "open": 2}[new_state.value]
        _CB_STATE.labels(name=self._metrics_name).set(state_value)

        # Record transition
        _CB_TRANSITIONS.labels(
            name=self._metrics_name,
            from_state=old_state.value,
            to_state=new_state.value,
        ).inc()

        log.warning(
            "Circuit breaker '%s' state transition: %s → %s",
            self._config.name, old_state.value, new_state.value,
        )

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            _CB_SUCCESSES.labels(name=self._metrics_name).inc()

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success in closed state
                self._failure_count = 0

    def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record a failed call."""
        with self._lock:
            _CB_FAILURES.labels(name=self._metrics_name).inc()
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN immediately opens the circuit
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self._config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def can_execute(self) -> bool:
        """Check if a call can be executed (used for non-async fallback decisions)."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state != CircuitState.OPEN

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Optional[Callable[..., Awaitable[T]]] = None,
        fallback_type: str = "default",
        **kwargs: Any,
    ) -> T:
        """
        Execute a callable through the circuit breaker.

        Args:
            func: Async callable to execute
            *args, **kwargs: Arguments passed to func
            fallback: Optional async fallback callable (used when circuit is OPEN)
            fallback_type: Label for fallback metrics

        Returns:
            Result of func or fallback

        Raises:
            CircuitOpenError: If circuit is OPEN and no fallback provided
            Original exception: If func fails and circuit doesn't open
        """
        # Check state before executing
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.OPEN:
                if fallback is not None:
                    _CB_FALLBACKS.labels(name=self._metrics_name, fallback_type=fallback_type).inc()
                    log.debug("Circuit breaker '%s' OPEN — executing fallback", self._config.name)
                    return await fallback(*args, **kwargs)
                raise CircuitOpenError(f"Circuit breaker '{self._config.name}' is OPEN")

        # Execute with timing
        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            duration = time.monotonic() - start
            _CB_CALL_DURATION.labels(name=self._metrics_name, outcome="success").observe(duration)
            self.record_success()
            return result
        except self._config.expected_exception as exc:
            duration = time.monotonic() - start
            _CB_CALL_DURATION.labels(name=self._metrics_name, outcome="failure").observe(duration)
            self.record_failure(exc)
            # If we just opened the circuit and have fallback, try it
            if self.is_open and fallback is not None:
                _CB_FALLBACKS.labels(name=self._metrics_name, fallback_type=fallback_type).inc()
                log.debug("Circuit breaker '%s' opened during call — executing fallback", self._config.name)
                return await fallback(*args, **kwargs)
            raise

    def __enter__(self) -> "CircuitBreaker":
        """Sync context manager entry — checks state."""
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(f"Circuit breaker '{self._config.name}' is OPEN")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Sync context manager exit — records outcome."""
        if exc_type is None:
            self.record_success()
        elif issubclass(exc_type, self._config.expected_exception):
            self.record_failure(exc_val)
        # Don't suppress exceptions
        return False

    async def __aenter__(self) -> "CircuitBreaker":
        """Async context manager entry."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit."""
        return self.__exit__(exc_type, exc_val, exc_tb)

    def stats(self) -> dict[str, Any]:
        """Return current circuit breaker statistics."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return {
                "name": self._config.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self._config.failure_threshold,
                "recovery_timeout": self._config.recovery_timeout,
                "last_failure_time": self._last_failure_time if self._last_failure_time else None,
                "time_since_last_failure": (
                    time.monotonic() - self._last_failure_time
                    if self._last_failure_time
                    else None
                ),
            }

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        with self._lock:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            _CB_STATE.labels(name=self._metrics_name).set(0)
            if old_state != CircuitState.CLOSED:
                _CB_TRANSITIONS.labels(
                    name=self._metrics_name,
                    from_state=old_state.value,
                    to_state="closed",
                ).inc()
            log.info("Circuit breaker '%s' manually reset to CLOSED", self._config.name)


class CircuitOpenError(Exception):
    """Raised when circuit breaker is OPEN and no fallback is available."""
    pass


# ── Circuit Breaker Registry ─────────────────────────────────────────────────

class CircuitBreakerRegistry:
    """
    Global registry for circuit breakers.
    Ensures single instance per name and provides bulk operations.
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock = Lock()

    def __new__(cls) -> "CircuitBreakerRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._breakers: dict[str, CircuitBreaker] = {}
        return cls._instance

    def get_or_create(self, config: CircuitBreakerConfig) -> CircuitBreaker:
        """Get existing breaker or create new one."""
        with self._lock:
            if config.name not in self._breakers:
                self._breakers[config.name] = CircuitBreaker(config)
            return self._breakers[config.name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get breaker by name."""
        return self._breakers.get(name)

    def all_stats(self) -> dict[str, dict]:
        """Get stats for all registered breakers."""
        return {name: cb.stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all breakers to CLOSED."""
        for cb in self._breakers.values():
            cb.reset()


# ── Convenience Factory Functions ────────────────────────────────────────────

def create_twin_circuit_breaker() -> CircuitBreaker:
    """Create circuit breaker for gRPC twin-service."""
    settings = get_settings()
    config = CircuitBreakerConfig(
        name="twin-service",
        failure_threshold=settings.twin.circuit_failure_threshold,
        recovery_timeout=settings.twin.circuit_recovery_timeout,
    )
    return CircuitBreakerRegistry().get_or_create(config)


def create_e2_circuit_breaker() -> CircuitBreaker:
    """Create circuit breaker for E2 RC client."""
    settings = get_settings()
    config = CircuitBreakerConfig(
        name="e2-rc-client",
        failure_threshold=settings.e2.circuit_failure_threshold,
        recovery_timeout=settings.e2.circuit_recovery_timeout,
    )
    return CircuitBreakerRegistry().get_or_create(config)


def create_redis_circuit_breaker() -> CircuitBreaker:
    """Create circuit breaker for Redis operations."""
    settings = get_settings()
    config = CircuitBreakerConfig(
        name="redis",
        failure_threshold=5,
        recovery_timeout=10.0,
    )
    return CircuitBreakerRegistry().get_or_create(config)


# Export registry singleton
breaker_registry = CircuitBreakerRegistry()