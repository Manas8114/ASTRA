"""
xapp/observability/__init__.py
──────────────────────────────────────────────────────────────────────────────
Observability Module for ASTRA xApp.

Exports:
- setup_loging: Initialize structured JSON logging
- get_logger: Get structured logger instance
- correlation_id_var: Context variable for correlation ID
- get_correlation_id: Get/set current correlation ID
- CorrelationIDMiddleware: FastAPI middleware for request correlation
- websocket_correlation: WebSocket correlation helper
- log_context: Context manager for binding log context
- log_duration: Context manager for timing operations
- setup_tracing: Initialize OpenTelemetry tracing
- get_tracer: Get OpenTelemetry tracer
- AstraSpan: Context manager for ASTRA-specific spans
- trace_async: Async context manager for tracing
- trace_function/trace_async_function: Decorators for tracing
"""

from xapp.observability.logging import (
    setup_logging,
    get_logger,
    correlation_id_var,
    trace_context_var,
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
    get_trace_context,
    set_trace_context,
    CorrelationIDMiddleware,
    websocket_correlation,
    log_context,
    log_duration,
)
from xapp.observability.tracing import (
    setup_tracing,
    get_tracer,
    AstraSpan,
    trace_async,
    trace_function,
    trace_async_function,
    add_astra_attributes,
    add_kpi_attributes,
    add_model_attributes,
    set_baggage,
    get_baggage,
    clear_baggage,
    otel_fastapi_middleware,
)

__all__ = [
    "setup_logging",
    "get_logger",
    "correlation_id_var",
    "trace_context_var",
    "generate_correlation_id",
    "get_correlation_id",
    "set_correlation_id",
    "get_trace_context",
    "set_trace_context",
    "CorrelationIDMiddleware",
    "websocket_correlation",
    "log_context",
    "log_duration",
    "setup_tracing",
    "get_tracer",
    "AstraSpan",
    "trace_async",
    "trace_function",
    "trace_async_function",
    "add_astra_attributes",
    "add_kpi_attributes",
    "add_model_attributes",
    "set_baggage",
    "get_baggage",
    "clear_baggage",
    "otel_fastapi_middleware",
]