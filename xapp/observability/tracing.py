"""
xapp/observability/tracing.py
──────────────────────────────────────────────────────────────────────────────
OpenTelemetry Tracing Integration for ASTRA xApp.

Provides distributed tracing with:
- FastAPI instrumentation
- AsyncPG instrumentation
- Redis instrumentation
- gRPC instrumentation
- OTLP exporter for Tempo/Jaeger
- Custom span attributes for ASTRA context

Usage:
    from xapp.observability.tracing import setup_tracing, get_tracer

    # At startup
    setup_tracing()

    # In code
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("twin_simulation") as span:
        span.set_attribute("cell_id", "cell_001")
        result = await twin.simulate(...)
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Optional

from opentelemetry import trace, baggage
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHTTPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient, GrpcInstrumentorServer
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.b3 import B3MultiFormat
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from xapp.config import get_settings

log = logging.getLogger("astra.tracing")

# Context variable for current span
current_span_var: ContextVar[Optional[trace.Span]] = ContextVar("current_span", default=None)


def setup_tracing(
    service_name: Optional[str] = None,
    service_version: str = "1.0.0",
    endpoint: Optional[str] = None,
    enable_console: bool = False,
) -> None:
    """
    Initialize OpenTelemetry tracing.

    Args:
        service_name: Override service name (default from settings)
        service_version: Service version
        endpoint: OTLP endpoint (default from settings or env)
        enable_console: Export to console for debugging
    """
    settings = get_settings()

    if not settings.observatory.enable_tracing:
        log.info("Tracing disabled via configuration")
        return

    effective_service = service_name or settings.observatory.service_name
    effective_endpoint = endpoint or settings.observatory.otel_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    # Create resource
    resource = Resource.create({
        SERVICE_NAME: effective_service,
        SERVICE_VERSION: service_version,
        DEPLOYMENT_ENVIRONMENT: settings.security.astra_mode,
        "astra.cell_id": settings.cell_id,
    })

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Add OTLP exporter if endpoint configured
    if effective_endpoint:
        try:
            if effective_endpoint.startswith("http"):
                exporter = OTLPHTTPSpanExporter(endpoint=effective_endpoint)
            else:
                exporter = OTLPSpanExporter(endpoint=effective_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info(f"OTLP exporter configured: {effective_endpoint}")
        except Exception as e:
            log.warning(f"Failed to configure OTLP exporter: {e}")

    # Add console exporter for debugging
    if enable_console or os.getenv("OTEL_CONSOLE_EXPORTER", "false").lower() == "true":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        log.info("Console span exporter enabled")

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    # Set up propagators for context propagation
    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(),  # W3C traceparent/tracestate
        B3MultiFormat(),  # B3 headers for Zipkin compatibility
    ]))

    # Auto-instrument libraries
    try:
        FastAPIInstrumentor().instrument()
        AsyncPGInstrumentor().instrument()
        RedisInstrumentor().instrument()
        GrpcInstrumentorClient().instrument()
        GrpcInstrumentorServer().instrument()
        RequestsInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()
        log.info("OpenTelemetry auto-instrumentation enabled")
    except Exception as e:
        log.warning(f"Some auto-instrumentation failed: {e}")

    log.info(
        "OpenTelemetry tracing initialized",
        service=effective_service,
        version=service_version,
        environment=settings.security.astra_mode,
    )


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer instance."""
    return trace.get_tracer(name, version="1.0.0")


def get_current_span() -> Optional[trace.Span]:
    """Get current active span from context."""
    return trace.get_current_span()


# ── Span Helpers ─────────────────────────────────────────────────────────────

class AstraSpan:
    """
    Context manager for creating ASTRA-specific spans with standard attributes.

    Usage:
        with AstraSpan("twin_simulation", cell_id="cell_001", action_type="ADMISSION_CONTROL"):
            result = await twin.simulate(...)
    """

    def __init__(
        self,
        operation: str,
        tracer_name: str = "astra",
        **attributes: Any,
    ) -> None:
        self._operation = operation
        self._tracer = get_tracer(tracer_name)
        self._attributes = {
            "astra.operation": operation,
            **attributes,
        }
        self._span: Optional[trace.Span] = None
        self._token = None

    def __enter__(self) -> trace.Span:
        self._span = self._tracer.start_span(self._operation)
        self._token = current_span_var.set(self._span)

        # Set standard attributes
        for key, value in self._attributes.items():
            if value is not None:
                self._span.set_attribute(key, value)

        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._span:
            if exc_type is not None:
                self._span.record_exception(exc_val)
                self._span.set_status(trace.StatusCode.ERROR, str(exc_val))
            else:
                self._span.set_status(trace.StatusCode.OK)
            self._span.end()
        if self._token:
            current_span_var.reset(self._token)


def add_astra_attributes(span: trace.Span, **kwargs: Any) -> None:
    """Add ASTRA-specific attributes to a span."""
    standard_attrs = {
        "astra.cell_id": kwargs.get("cell_id"),
        "astra.anomaly_type": kwargs.get("anomaly_type"),
        "astra.action_type": kwargs.get("action_type"),
        "astra.improvement_pct": kwargs.get("improvement_pct"),
        "astra.detector_threshold": kwargs.get("threshold"),
        "astra.forecast_horizon": kwargs.get("forecast_horizon"),
    }

    for key, value in standard_attrs.items():
        if value is not None:
            span.set_attribute(key, value)


def add_kpi_attributes(span: trace.Span, kpi_data: dict[str, float], prefix: str = "kpi") -> None:
    """Add KPI values as span attributes."""
    for key, value in kpi_data.items():
        span.set_attribute(f"{prefix}.{key}", value)


def add_model_attributes(span: trace.Span, model_info: dict) -> None:
    """Add model information as span attributes."""
    for key, value in model_info.items():
        if isinstance(value, (str, int, float, bool)):
            span.set_attribute(f"model.{key}", value)


# ── Baggage Helpers ──────────────────────────────────────────────────────────

_baggage_keys = {
    "cell_id": "astra.cell_id",
    "anomaly_type": "astra.anomaly_type",
    "correlation_id": "astra.correlation_id",
}


def set_baggage(**kwargs: Any) -> None:
    """Set baggage entries for cross-service propagation."""
    for key, value in kwargs.items():
        if value is not None and key in _baggage_keys:
            baggage.set_baggage(_baggage_keys[key], str(value))


def get_baggage(key: str) -> Optional[str]:
    """Get baggage value by key."""
    if key in _baggage_keys:
        return baggage.get_baggage(_baggage_keys[key])
    return None


def clear_baggage() -> None:
    """Clear all ASTRA baggage entries."""
    for attr_key in _baggage_keys.values():
        baggage.clear_baggage(attr_key)


# ── FastAPI Integration ──────────────────────────────────────────────────────

def otel_fastapi_middleware(app) -> None:
    """
    Add OpenTelemetry instrumentation to FastAPI app.

    Should be called after setup_tracing().
    """
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=trace.get_tracer_provider(),
        excluded_urls="/health,/metrics,/docs,/openapi.json,/redoc",
    )


# ── Context Managers for Common Operations ───────────────────────────────────

from contextlib import asynccontextmanager
from functools import wraps


@asynccontextmanager
async def trace_async(operation: str, **attributes: Any):
    """Async context manager for tracing."""
    tracer = get_tracer("astra")
    with tracer.start_as_current_span(operation) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise


def trace_function(operation: str, **attributes: Any):
    """Decorator for tracing sync functions."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with AstraSpan(operation, **attributes) as span:
                return func(*args, **kwargs)
        return wrapper
    return decorator


def trace_async_function(operation: str, **attributes: Any):
    """Decorator for tracing async functions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with trace_async(operation, **attributes) as span:
                return await func(*args, **kwargs)
        return wrapper
    return decorator