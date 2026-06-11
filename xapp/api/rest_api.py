from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Depends

from xapp.ingestion.kpi_schema import AnomalyType
from xapp.state import StateManager

def rest_router(state_manager: StateManager) -> APIRouter:
    router = APIRouter()

    def get_state(cell_id: str = None):
        return state_manager.get_state(cell_id or os.getenv("CELL_ID", "cell_001"))

    def require_control_auth(x_api_key: str | None) -> None:
        expected = os.getenv("ASTRA_CONTROL_API_KEY")
        if expected and x_api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid control API key")

    @router.get("/status")
    async def status(cell_id: str = None):
        snap = get_state(cell_id).snapshot()
        return {k: snap[k] for k in ["running", "model_version", "threshold", "cell_id", "uptime"]}

    @router.get("/kpis/current")
    async def current_kpis(cell_id: str = None):
        latest = get_state(cell_id).snapshot()["latest_kpi"]
        if latest is None:
            raise HTTPException(status_code=404, detail="No KPI sample received yet")
        return latest

    @router.get("/kpis/history")
    async def kpi_history(minutes: int = 60, cell_id: str = None):
        limit = max(1, min(minutes * 60, 3600))
        return get_state(cell_id).snapshot()["history"][-limit:]

    @router.get("/anomalies")
    async def anomalies(cell_id: str = None):
        return get_state(cell_id).snapshot()["anomalies"]

    @router.get("/healing")
    async def healing(cell_id: str = None):
        return get_state(cell_id).snapshot()["healing"]

    @router.get("/attribution/latest")
    async def latest_attribution(cell_id: str = None):
        return get_state(cell_id).snapshot()["latest_attribution"] or {}

    deps = []
    if os.getenv("ASTRA_MODE") == "prod":
        try:
            from fastapi_limiter.depends import RateLimiter
            deps = [Depends(RateLimiter(times=50, seconds=60))]
        except ImportError:
            pass

    @router.post("/policy", dependencies=deps)
    async def policy(payload: dict, x_api_key: str | None = Header(default=None), cell_id: str = None):
        require_control_auth(x_api_key)
        state = get_state(cell_id)
        threshold = payload.get("threshold") or payload.get("threshold_3sigma")
        if threshold is not None:
            with state.lock:
                state.threshold = float(threshold)
        return {"accepted": True, "threshold": state.snapshot()["threshold"]}

    @router.post("/inject/{anomaly_type}", dependencies=deps)
    async def inject(anomaly_type: AnomalyType, x_api_key: str | None = Header(default=None), cell_id: str = None):
        require_control_auth(x_api_key)
        state = get_state(cell_id)
        with state.lock:
            state.injected_anomaly = anomaly_type.value
        event = state.record_event({"type": "MANUAL_INJECTION", "anomaly_type": anomaly_type.value})
        return event

    @router.get("/health")
    async def health():
        return {"ok": True}

    @router.get("/forecast/latest")
    async def get_latest_forecast(cell_id: str = None):
        state = get_state(cell_id)
        if not hasattr(state, "forecaster") or state.forecaster is None:
            return {"status": "no_forecast_yet"}
        r = state.forecaster._last_result
        if r is None:
            return {"status": "no_forecast_yet"}
        return {
            "preemptive_alert": r["preemptive_alert"],
            "seconds_to_anomaly": r["seconds_to_anomaly"],
            "at_risk_kpis": r["at_risk_kpis"],
            "confidence": r["confidence"],
            "summary": r["summary"],
            "timestamp": r["timestamp"],
        }

    @router.get("/prevention/stats")
    async def get_prevention_stats(cell_id: str = None):
        state = get_state(cell_id)
        if not hasattr(state, "preemptive") or state.preemptive is None:
            return {
                "prevented": 0,
                "false_alarms": 0,
                "applied": 0,
                "prevention_rate": 0.0,
                "reactive_healed": 0,
                "total_incidents": 0,
                "prevention_rate_pct": 0.0,
            }
        p = state.preemptive
        h = state.preemptive.healer
        return {
            **p.stats,
            "reactive_healed": h.total_healed,
            "total_incidents": p.stats["prevented"] + h.total_healed,
            "prevention_rate_pct": round(p.stats["prevention_rate"] * 100, 1),
        }

    return router
