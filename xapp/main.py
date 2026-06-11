"""
xapp/main.py
──────────────────────────────────────────────────────────────────────────────
ASTRA xApp — Main Entry Point

Production-ready entry point with:
- Centralized Pydantic configuration (fail-fast validation)
- Structured logging with correlation IDs
- Circuit breakers for external dependencies
- WebSocket backpressure management
- Graceful shutdown with resource cleanup
- Health checks and metrics
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Local imports ────────────────────────────────────────────────────────────

from xapp.api import rest_router, a1_router, websocket_router
from xapp.classifier.anomaly_classifier import AnomalyClassifier
from xapp.digital_twin.twin_simulator import DigitalTwinSimulator
from xapp.healing.action_engine import HealingActionEngine
from xapp.healing.e2_rc_client import get_e2_client
from xapp.ingestion.kpi_adapters import select_kpi_stream
from xapp.ingestion.kpi_buffer import KPIBuffer
from xapp.ingestion.kpi_schema import AnomalyType
from xapp.model.anomaly_detector import AnomalyDetector
from xapp.model.attention_extractor import AttentionExtractor
from xapp.innovations.multicell.coordinator import MultiCellCoordinator
from xapp.persistence.redis_client import redis_client
from xapp.persistence.pg_audit import pg_audit_trail
from xapp.prediction.forecast_head import ForecastHead
from xapp.prediction.preemptive_healer import PreemptiveHealer
from xapp.security.rbac import get_current_role

# ── New Phase 1 imports ──────────────────────────────────────────────────────

from xapp.config import get_settings
from xapp.lifecycle import LifecycleManager, register_shutdown_handlers
from xapp.observability import setup_logging, get_logger, CorrelationIDMiddleware, setup_tracing
from xapp.resilience import create_twin_circuit_breaker, create_e2_circuit_breaker


# ── Settings & Logging Initialization ────────────────────────────────────────

_settings = get_settings()
_logger = get_logger("astra.main")


def _load_dotenv(path: str = ".env") -> None:
    """Load environment variables from .env file."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


# ── FastAPI Lifespan ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
    - Initialize structured logging
    - Register shutdown handlers
    - Validate configuration
    - Start background tasks

    Shutdown:
    - Graceful shutdown via LifecycleManager
    """
    global _lifecycle_manager, _detection_task, _server_task

    _load_dotenv()

    # Initialize structured logging FIRST
    setup_logging(
        log_level=_settings.observatory.log_level,
        log_format=_settings.observatory.log_format,
        service_name=_settings.observatory.service_name,
    )
    
    # Initialize OpenTelemetry tracing
    if _settings.observatory.enable_tracing:
        setup_tracing(
            service_name=_settings.observatory.service_name,
            enable_console=_settings.observatory.log_format != "json",
        )

    _logger.info(
        "ASTRA xApp starting",
        cell_id=_settings.cell_id,
        mode=_settings.security.astra_mode,
        version="1.0.0",
    )

    # Validate production requirements (fail-fast in config)
    if _settings.is_prod:
        _logger.info("Production mode validated successfully")

    # Initialize lifecycle manager and register shutdown handlers
    _lifecycle_manager = LifecycleManager(default_timeout=30.0)
    register_shutdown_handlers(_lifecycle_manager)

    # Initialize components that need graceful shutdown
    _state_manager = StateManager()
    _state = _state_manager.get_state(_settings.cell_id)
    _hub = WebSocketHub()

    # Create FastAPI app
    _app = FastAPI(
        title="ASTRA xApp",
        description="O-RAN Near-RT RIC xApp for Autonomous 5G RAN Self-Healing",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── CORS ────────────────────────────────────────────────────────────────
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Correlation-ID"],
    )

    # ── Correlation ID Middleware ──────────────────────────────────────────
    _app.add_middleware(CorrelationIDMiddleware)

    # ── OpenTelemetry FastAPI Instrumentation ──────────────────────────────
    from xapp.observability import otel_fastapi_middleware
    otel_fastapi_middleware(_app)

    # ── Auth Middleware for Prod ───────────────────────────────────────────
    if _settings.is_prod:
        from starlette.middleware.base import BaseHTTPMiddleware
        from fastapi import Request
        from starlette.responses import JSONResponse

        class AuthMiddleware(BaseHTTPMiddleware):
            OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}

            async def dispatch(self, request: Request, call_next):
                path = request.url.path
                if path in self.OPEN_PATHS or path.startswith("/ws"):
                    return await call_next(request)
                try:
                    get_current_role(request)
                except Exception:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Unauthorized — provide Bearer token in Authorization header"},
                    )
                return await call_next(request)

        _app.add_middleware(AuthMiddleware)

    # ── Routes ──────────────────────────────────────────────────────────────
    _app.include_router(rest_router(_state_manager))
    _app.include_router(websocket_router(_hub))
    _app.include_router(a1_router(_state_manager))

    # ── Metrics ─────────────────────────────────────────────────────────────
    if _settings.is_prod:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator
            Instrumentator().instrument(_app).expose(_app, endpoint="/metrics")
            _logger.info("Prometheus metrics exposed at /metrics")
        except Exception as e:
            _logger.warning("Failed to initialize Prometheus instrumentator: %s", e)

    # ── Rate Limiting (Prod) ────────────────────────────────────────────────
    if _settings.is_prod:
        try:
            from fastapi_limiter import FastAPILimiter
            import redis.asyncio as aioredis
            r = aioredis.Redis(
                host=_settings.redis.host,
                port=_settings.redis.port,
                password=_settings.redis.password,
                db=_settings.redis.db,
                decode_responses=True,
            )
            await FastAPILimiter.init(r)
            _logger.info("FastAPI rate limiter initialized")
        except Exception as e:
            _logger.warning("FastAPILimiter init failed: %s", e)

    # ── Register components for graceful shutdown ──────────────────────────
    _lifecycle_manager.register_websocket_hub(_hub)
    _lifecycle_manager.register_redis_client(redis_client)

    # Get E2 client for shutdown registration
    _e2_client = get_e2_client()
    _lifecycle_manager.register_e2_client(_e2_client)

    # Register thread pool from state.py
    from xapp.state import _EXECUTOR
    _lifecycle_manager.register_thread_pool(_EXECUTOR)

    # If twin-service gRPC channel exists, register it
    if hasattr(_state, 'digital_twin') and hasattr(_state.digital_twin, 'channel'):
        _lifecycle_manager.register_twin_channel(_state.digital_twin.channel)

    # ── Start Detection Loop ──────────────────────────────────────────────
    _detection_task = asyncio.create_task(detection_loop(_state, _hub))
    _lifecycle_manager.register_detection_loop(_detection_task)

    # ── Start HTTP Server ──────────────────────────────────────────────────
    config = uvicorn.Config(
        _app,
        host=_settings.api.host,
        port=_settings.api.port,
        log_level=_settings.observatory.log_level.lower(),
        access_log=False,  # We log via CorrelationIDMiddleware
    )
    server = uvicorn.Server(config)
    _server_task = asyncio.create_task(server.serve())

    _logger.info(
        "ASTRA xApp running",
        cell_id=_state.cell_id,
        threshold=_state.threshold,
        api_port=_settings.api.port,
    )

    yield  # Application runs here

    # ── Graceful Shutdown ──────────────────────────────────────────────────
    _logger.info("Shutdown signal received — initiating graceful shutdown")
    await _lifecycle_manager.shutdown()
    _logger.info("ASTRA xApp shutdown complete")


# ── Global State (populated in lifespan) ────────────────────────────────────

_lifecycle_manager: LifecycleManager | None = None
_detection_task: asyncio.Task | None = None
_server_task: asyncio.Task | None = None


# ── Detection Loop (Core ML Pipeline) ────────────────────────────────────────

async def detection_loop(state: LiveState, hub: WebSocketHub) -> None:
    """
    Main detection loop — runs continuously processing KPI stream.

    Pipeline: KPI Stream → Buffer → LSTM AE → Attention → Classification → Twin → Healing
    """
    _logger.info("Detection loop started")

    # Initialize ML components
    buffer = KPIBuffer()
    detector = AnomalyDetector(
        consecutive_trigger=_settings.kpi.consecutive_anomaly_trigger,
    )
    state.threshold = detector.threshold
    last_calculated_threshold = detector.threshold

    classifier = AnomalyClassifier()
    attention = AttentionExtractor()
    twin = DigitalTwinSimulator(detector, _settings.twin.approval_threshold)
    healing = HealingActionEngine()
    multicell = MultiCellCoordinator()

    # Forecasting (optional — requires PyTorch model)
    forecaster = ForecastHead(anomaly_detector=detector) if hasattr(detector, "model") else None
    preemptive = (
        PreemptiveHealer(
            anomaly_classifier=classifier,
            digital_twin=twin,
            healing_engine=healing,
            websocket_server=hub,
            anomaly_detector=detector,
        )
        if forecaster is not None
        else None
    )
    state.forecaster = forecaster
    state.preemptive = preemptive

    # ── Wire EWC Continual Learning ──────────────────────────────────────
    ewc_penalty_fn = None
    if (
        hasattr(detector, "model")
        and _settings.model.ewc_enabled
        and os.getenv("ASTRA_EWC_ENABLED", "true").lower() == "true"
    ):
        try:
            from xapp.innovations.continual.ewc import EWCPenalty
            from xapp.innovations.continual.anomaly_memory import AnomalyMemoryBuffer
            ewc = EWCPenalty(detector.model)
            anomaly_memory = AnomalyMemoryBuffer(
                capacity=_settings.model.ewc_buffer_capacity,
            )
            ewc_penalty_fn = ewc.penalty
            state.ewc = ewc
            state.anomaly_memory = anomaly_memory
            _logger.info(
                "EWC continual learning wired",
                lambda_=ewc.lambda_,
                buffer_capacity=anomaly_memory.capacity,
            )
        except Exception as e:
            _logger.warning("EWC init failed (non-critical): %s", e)

    # Select KPI stream
    stream = select_kpi_stream(state)

    # ── Main Processing Loop ──────────────────────────────────────────────
    async for kpi in stream:
        # Check for shutdown
        if _lifecycle_manager and _lifecycle_manager.is_shutting_down:
            _logger.info("Detection loop stopping — shutdown in progress")
            break

        buffer.push(kpi)

        window = buffer.get_window()
        forecast_alert = False
        forecast_confidence = None

        # ── Preemptive Forecasting ────────────────────────────────────────
        if window is not None and forecaster is not None and preemptive is not None:
            forecast = forecaster.predict(window)
            forecast_alert = forecast.preemptive_alert
            forecast_confidence = forecast.confidence

            # Broadcast forecast risk curve
            await hub.broadcast({
                "type": "FORECAST_UPDATE",
                "timestamp": forecast.timestamp,
                "preemptive_alert": forecast.preemptive_alert,
                "seconds_to_anomaly": forecast.seconds_to_anomaly,
                "at_risk_kpis": forecast.at_risk_kpis,
                "confidence": forecast.confidence,
                "risk_curve_60s": forecast.risk_curve[:60].tolist(),
                "summary": forecast.summary,
            })

            if forecast.preemptive_alert:
                asyncio.create_task(preemptive.evaluate(forecast, window))

        # ── Record KPI Event ──────────────────────────────────────────────
        kpi_event = state.record_event({
            "type": "KPI_UPDATE",
            "kpis": kpi.to_dict(),
            "forecast_alert": forecast_alert,
            "forecast_confidence": forecast_confidence,
            "prevention_stats": preemptive.stats if preemptive is not None else {},
        })
        await hub.broadcast(kpi_event)

        # ── Anomaly Detection ─────────────────────────────────────────────
        if window is not None:
            # Update dynamic threshold if changed
            if abs(state.threshold - last_calculated_threshold) > 1e-6:
                detector.threshold = state.threshold
                detector.min_samples = 99999999
            result = detector.detect(window)
            state.threshold = detector.threshold
            last_calculated_threshold = detector.threshold

            if result.declared:
                classification = classifier.classify(result.per_feature_mse)
                attr = attention.extract(result.attention_weights)

                anomaly_event = state.record_event({
                    "type": "ANOMALY_DETECTED",
                    "anomaly_type": classification.anomaly_type.value,
                    "confidence": classification.confidence,
                    "top_kpis": classification.top_kpis,
                    "reasoning": classification.reasoning,
                    "attention_weights": attr.weights,
                    "top_cause": attr.top_cause,
                    "explanation": attr.explanation,
                    "total_mse": result.total_mse,
                })
                await hub.broadcast(anomaly_event)

                # Feed anomaly memory for EWC
                if ewc_penalty_fn is not None and hasattr(state, "anomaly_memory"):
                    buffer_full = state.anomaly_memory.add(result.per_feature_mse)
                    if buffer_full:
                        try:
                            import numpy as np
                            errors = state.anomaly_memory.drain()
                            ref_data = np.array(
                                [[list(e.values())] * 30 for e in errors],
                                dtype=np.float32,
                            )
                            state.ewc.consolidate(detector.model, ref_data)
                            _logger.info("EWC consolidated with %d anomaly samples", len(errors))
                        except Exception as e:
                            _logger.warning("EWC consolidation failed: %s", e)

                # Healing Decision
                candidate = healing.candidate_for(classification.anomaly_type)
                current = buffer.recent_average() or kpi.to_dict()

                if classification.anomaly_type == AnomalyType.NOVEL or candidate is None:
                    event = state.record_event({
                        "type": "ESCALATION",
                        "reason": "Novel anomaly is never auto-healed.",
                        "anomaly_type": classification.anomaly_type.value,
                    })
                    await hub.broadcast(event)
                else:
                    sim = twin.simulate_action(candidate, current, result.total_mse)
                    sim_event = state.record_event({
                        "type": "DT_SIMULATION",
                        "anomaly_type": classification.anomaly_type.value,
                        "action": candidate.action_type,
                        "parameters": candidate.parameters,
                        "current_mse": result.total_mse,
                        "projected_mse": sim.projected_mse,
                        "improvement_pct": sim.improvement_pct,
                        "approved": sim.approved,
                        "current_state": current,
                        "projected_state": sim.projected_state,
                        "queue_metrics": getattr(sim, "queue_metrics", None),
                        "recommendation": sim.recommendation,
                    })
                    await hub.broadcast(sim_event)

                    if sim.approved:
                        healed = await healing.execute(classification.anomaly_type, candidate, sim, current)
                        event = state.record_event(healed)
                        with state.lock:
                            state.injected_anomaly = None

                        # Multi-cell coordination
                        try:
                            coord_msgs = await multicell.broadcast(
                                state.cell_id, candidate.action_type, candidate.parameters
                            )
                            if coord_msgs:
                                coord_event = state.record_event({
                                    "type": "MULTICELL_BROADCAST",
                                    "source_cell": state.cell_id,
                                    "neighbors_notified": len(coord_msgs),
                                    "action": candidate.action_type,
                                })
                                await hub.broadcast(coord_event)
                        except Exception:
                            pass  # Non-critical

                    else:
                        event = state.record_event({
                            "type": "ESCALATION",
                            "reason": sim.recommendation,
                            "anomaly_type": classification.anomaly_type.value,
                        })
                        await hub.broadcast(event)

        await asyncio.sleep(1)


# ── Legacy Imports for Main Execution ────────────────────────────────────────

from xapp.state import LiveState, StateManager
from xapp.api.websocket_backpressure import WebSocketHub


# ── Main Entry Point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # This path is used for direct `python -m xapp.main` execution
    # The lifespan handles everything, but we need to run the event loop
    import sys

    # Ensure we can import from parent directory
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Create app with lifespan
    _load_dotenv()
    setup_logging()
    _logger = get_logger("astra.main")

    # Use asyncio.run with the lifespan-managed app
    async def run_server() -> None:
        _load_dotenv()

        # Settings already loaded globally
        _logger.info("ASTRA xApp starting (direct execution)")

        _lifecycle_manager = LifecycleManager(default_timeout=30.0)
        register_shutdown_handlers(_lifecycle_manager)

        _state_manager = StateManager()
        _state = _state_manager.get_state(get_settings().cell_id)
        _hub = WebSocketHub()

        app = FastAPI(title="ASTRA xApp", lifespan=lifespan)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=get_settings().api.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Correlation-ID"],
        )
        app.add_middleware(CorrelationIDMiddleware)

        if get_settings().is_prod:
            from starlette.middleware.base import BaseHTTPMiddleware
            from fastapi import Request
            from starlette.responses import JSONResponse

            class AuthMiddleware(BaseHTTPMiddleware):
                OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}

                async def dispatch(self, request: Request, call_next):
                    path = request.url.path
                    if path in self.OPEN_PATHS or path.startswith("/ws"):
                        return await call_next(request)
                    try:
                        get_current_role(request)
                    except Exception:
                        return JSONResponse(
                            status_code=401,
                            content={"detail": "Unauthorized — provide Bearer token in Authorization header"},
                        )
                    return await call_next(request)

            app.add_middleware(AuthMiddleware)

        app.include_router(rest_router(_state_manager))
        app.include_router(websocket_router(_hub))
        app.include_router(a1_router(_state_manager))

        if get_settings().is_prod:
            try:
                from prometheus_fastapi_instrumentator import Instrumentator
                Instrumentator().instrument(app).expose(app, endpoint="/metrics")
            except Exception as e:
                _logger.warning("Prometheus instrumentator failed: %s", e)

        _lifecycle_manager.register_websocket_hub(_hub)
        _lifecycle_manager.register_redis_client(redis_client)
        _e2_client = get_e2_client()
        _lifecycle_manager.register_e2_client(_e2_client)
        from xapp.state import _EXECUTOR
        _lifecycle_manager.register_thread_pool(_EXECUTOR)

        _detection_task = asyncio.create_task(detection_loop(_state, _hub))
        _lifecycle_manager.register_detection_loop(_detection_task)

        config = uvicorn.Config(
            app,
            host=get_settings().api.host,
            port=get_settings().api.port,
            log_level=get_settings().observatory.log_level.lower(),
            access_log=False,
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(run_server())