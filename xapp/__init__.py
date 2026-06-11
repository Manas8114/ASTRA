"""
xapp/__init__.py
──────────────────────────────────────────────────────────────────────────────
ASTRA xApp Package.

Main submodules:
- api: REST, WebSocket, A1 policy endpoints
- classifier: Anomaly classification
- digital_twin: M/M/1 digital twin simulator
- healing: Healing action engine + E2 RC client
- ingestion: KPI adapters, schemas, buffering
- innovations: Multi-cell, A1 mediator, federated, continual learning
- model: LSTM autoencoder, anomaly detection, attention extraction
- observability: Structured logging, correlation IDs
- persistence: Redis, PostgreSQL audit trail
- prediction: ForecastHead, preemptive healer
- resilience: Circuit breaker, retry patterns
- security: RBAC, authentication
- lifecycle: Graceful shutdown management
- config: Centralized Pydantic settings
"""

# Re-export key symbols for convenient imports
from xapp.config import settings, get_settings, reload_settings
from xapp.lifecycle import LifecycleManager, get_lifecycle_manager, register_shutdown_handlers, GracefulShutdown
from xapp.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    create_twin_circuit_breaker,
    create_e2_circuit_breaker,
    breaker_registry,
)
from xapp.observability import (
    setup_logging,
    get_logger,
    correlation_id_var,
    CorrelationIDMiddleware,
)
from xapp.api import WebSocketHub, websocket_hub

__all__ = [
    "settings",
    "get_settings",
    "reload_settings",
    "LifecycleManager",
    "get_lifecycle_manager",
    "register_shutdown_handlers",
    "GracefulShutdown",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "create_twin_circuit_breaker",
    "create_e2_circuit_breaker",
    "breaker_registry",
    "setup_logging",
    "get_logger",
    "correlation_id_var",
    "CorrelationIDMiddleware",
    "WebSocketHub",
    "websocket_hub",
]
