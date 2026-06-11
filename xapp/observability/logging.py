"""
xapp/observability/logging.py
──────────────────────────────────────────────────────────────────────────────
Structured Logging with Correlation IDs for ASTRA xApp.

Features:
- JSON structured logging via structlog
- Correlation ID propagation (request-scoped + cross-service)
- Context variables for async-safe correlation tracking
- Automatic field enrichment (service name, version, environment)
- Integration with FastAPI middleware for request correlation
- Log level configuration from centralized settings

Usage:
    from xapp.observability.logging import get_logger, setup_logging, correlation_id_var

    # At startup:
    setup_logging()

    # In code:
    logger = get_logger(__name__)
    logger.info("KPI received", cell_id="cell_001", kpi_count=6)

    # Correlation ID automatically injected from context
    # Access current correlation ID:
    cid = correlation_id_var.get()
"""

from __future__ import annotations

import contextvars
import logging
import os
import sys
import uuid
from typing import Any, Optional

import structlog
from structlog.types import Processor

from xapp.config import get_settings

# ── Context Variables for Correlation ID ──────────────────────────────────────

# Request-scoped correlation ID (async-safe via contextvars)
correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)

# Additional context for cross-service tracing
_trace_context_default: dict[str, str] = {}
trace_context_var: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "trace_context", default=_trace_context_default
)


def generate_correlation_id() -> str:
    """Generate a new correlation ID (UUID4)."""
    return str(uuid.uuid4())


def get_correlation_id() -> str:
    """Get current correlation ID or generate a new one."""
    cid = correlation_id_var.get()
    if cid is None:
        cid = generate_correlation_id()
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set correlation ID for current context."""
    correlation_id_var.set(cid)


def get_trace_context() -> dict[str, str]:
    """Get current trace context."""
    return trace_context_var.get().copy()


def set_trace_context(ctx: dict[str, str]) -> None:
    """Set trace context for current context."""
    trace_context_var.set(ctx)


# ── Structlog Processors ──────────────────────────────────────────────────────

def add_correlation_id(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add correlation ID to log event."""
    cid = correlation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def add_trace_context(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add trace context fields (trace_id, span_id, parent_span_id)."""
    ctx = trace_context_var.get()
    if ctx:
        event_dict.update(ctx)
    return event_dict


def add_service_info(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add static service information."""
    settings = get_settings()
    event_dict["service"] = settings.observatory.service_name
    event_dict["environment"] = settings.security.mode
    event_dict["cell_id"] = settings.cell_id
    return event_dict


def add_severity_level(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Map structlog level to standard severity field."""
    level_map = {
        "debug": "DEBUG",
        "info": "INFO",
        "warning": "WARN",
        "error": "ERROR",
        "critical": "CRITICAL",
    }
    event_dict["severity"] = level_map.get(method_name, method_name.upper())
    return event_dict


def drop_empty_fields(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Remove None/empty values to keep logs clean."""
    return {k: v for k, v in event_dict.items() if v not in (None, "", [], {})}


def setup_json_renderer() -> structlog.processors.JSONRenderer:
    """Configure JSON renderer with sorted keys for consistent output."""
    return structlog.processors.JSONRenderer(sort_keys=True)


def setup_console_renderer() -> structlog.dev.ConsoleRenderer:
    """Configure pretty console renderer for development."""
    return structlog.dev.ConsoleRenderer(colors=True)


# ── Logging Setup ─────────────────────────────────────────────────────────────

_shared_processors: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    add_service_info,
    add_correlation_id,
    add_trace_context,
    add_severity_level,
    drop_empty_fields,
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]


def setup_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
    service_name: Optional[str] = None,
) -> None:
    """
    Initialize structured logging for the application.

    Must be called once at application startup (typically in main.py).

    Args:
        log_level: Override log level (DEBUG, INFO, WARNING, ERROR)
        log_format: Override format ("json" or "console")
        service_name: Override service name for log enrichment
    """
    settings = get_settings()

    # Determine effective configuration
    effective_level = log_level or os.getenv("LOG_LEVEL", settings.observatory.log_level)
    effective_format = log_format or os.getenv("LOG_FORMAT", settings.observatory.log_format)
    effective_service = service_name or settings.observatory.service_name

    # Configure stdlib logging to route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, effective_level.upper(), logging.INFO),
    )

    # Configure structlog
    if effective_format.lower() == "json":
        renderer: Processor = setup_json_renderer()
    else:
        renderer = setup_console_renderer()

    structlog.configure(
        processors=_shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, effective_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set service name in context for all subsequent logs
    structlog.contextvars.bind_contextvars(service=effective_service)

    # Log startup configuration
    logger = get_logger("astra.logging")
    logger.info(
        "Structured logging initialized",
        level=effective_level,
        format=effective_format,
        service=effective_service,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        structlog BoundLogger with context support
    """
    return structlog.get_logger(name)


# ── FastAPI Middleware for Request Correlation ────────────────────────────────

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware to extract/inject correlation IDs from requests.

    - Reads 'X-Correlation-ID' header or generates new one
    - Sets contextvars for request duration
    - Adds correlation ID to response headers
    """

    HEADER_NAME = "X-Correlation-ID"
    TRACEPARENT_HEADER = "traceparent"  # W3C Trace Context

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract correlation ID from headers
        correlation_id = request.headers.get(self.HEADER_NAME)
        if not correlation_id:
            # Check W3C traceparent format: version-trace-id-parent-id-flags
            traceparent = request.headers.get(self.TRACEPARENT_HEADER)
            if traceparent:
                try:
                    # traceparent: 00-<trace-id>-<parent-id>-<flags>
                    parts = traceparent.split("-")
                    if len(parts) >= 2:
                        correlation_id = parts[1]  # Use trace-id as correlation ID
                except Exception:
                    pass

        if not correlation_id:
            correlation_id = generate_correlation_id()

        # Set context for this request
        correlation_id_var.set(correlation_id)

        # Extract trace context if present
        trace_ctx = {}
        if traceparent:
            trace_ctx["traceparent"] = traceparent
            # Parse trace-id and parent-id for structured fields
            try:
                parts = traceparent.split("-")
                if len(parts) >= 3:
                    trace_ctx["trace_id"] = parts[1]
                    trace_ctx["span_id"] = parts[2]
            except Exception:
                pass
        trace_context_var.set(trace_ctx)

        # Process request
        start_time = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start_time) * 1000

        # Add correlation ID to response headers
        response.headers[self.HEADER_NAME] = correlation_id

        # Log request completion
        logger = get_logger("astra.http")
        logger.info(
            "HTTP request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            client_host=request.client.host if request.client else None,
        )

        return response


# ── WebSocket Correlation Helper ──────────────────────────────────────────────

from fastapi import WebSocket


async def websocket_correlation(websocket: WebSocket) -> str:
    """
    Extract or generate correlation ID for WebSocket connection.

    Call this in websocket endpoint before accepting connection.
    Returns the correlation ID for use in subsequent logging.
    """
    # Try to get from query params or headers
    correlation_id = websocket.query_params.get("correlation_id")
    if not correlation_id:
        correlation_id = websocket.headers.get("x-correlation-id")

    if not correlation_id:
        correlation_id = generate_correlation_id()

    # Set for this connection's context
    correlation_id_var.set(correlation_id)

    return correlation_id


# ── Logging Context Managers ──────────────────────────────────────────────────

import time
from contextlib import contextmanager
from typing import Generator


@contextmanager
def log_context(**kwargs: Any) -> Generator[None, None, None]:
    """
    Context manager to bind additional context to logs.

    Usage:
        with log_context(cell_id="cell_001", operation="healing"):
            logger.info("Starting healing process")
            # All logs in this block include cell_id and operation
    """
    # Use structlog's built-in context binding
    tokens = []
    for key, value in kwargs.items():
        if value is not None:
            # bind_contextvars returns the bound context which can be cleared
            bound = structlog.contextvars.bind_contextvars(**{key: value})
            tokens.append((key, bound))
    try:
        yield
    finally:
        for key, _ in tokens:
            structlog.contextvars.unbind_contextvars(key)


@contextmanager
def log_duration(logger: structlog.BoundLogger, operation: str, **kwargs: Any) -> Generator[None, None, None]:
    """
    Context manager to log operation duration.

    Usage:
        with log_duration(logger, "twin_simulation"):
            result = await twin.simulate(...)
    """
    start = time.monotonic()
    logger.debug(f"{operation} started", **kwargs)
    try:
        yield
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(f"{operation} failed", duration_ms=round(duration_ms, 2), error=str(e), **kwargs)
        raise
    else:
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(f"{operation} completed", duration_ms=round(duration_ms, 2), **kwargs)


# ── Import time for middleware (avoid circular import) ────────────────────────

import time  # noqa: E402