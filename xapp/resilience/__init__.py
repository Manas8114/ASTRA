"""
xapp/resilience/__init__.py
──────────────────────────────────────────────────────────────────────────────
Resilience Patterns for ASTRA xApp.

Exports:
- CircuitBreaker: Shared circuit breaker with Prometheus metrics
- CircuitBreakerConfig: Immutable configuration
- breaker_registry: Global registry for circuit breakers
- create_twin_circuit_breaker: Factory for twin-service breaker
- create_e2_circuit_breaker: Factory for E2 RC client breaker
- create_redis_circuit_breaker: Factory for Redis breaker
"""

from xapp.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitOpenError,
    CircuitBreakerRegistry,
    breaker_registry,
    create_twin_circuit_breaker,
    create_e2_circuit_breaker,
    create_redis_circuit_breaker,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "CircuitOpenError",
    "CircuitBreakerRegistry",
    "breaker_registry",
    "create_twin_circuit_breaker",
    "create_e2_circuit_breaker",
    "create_redis_circuit_breaker",
]