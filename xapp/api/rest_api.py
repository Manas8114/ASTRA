from __future__ import annotations

from fastapi import APIRouter, HTTPException

from xapp.ingestion.kpi_schema import AnomalyType
from xapp.state import LiveState


def rest_router(state: LiveState) -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    async def status():
        snap = state.snapshot()
        return {k: snap[k] for k in ["running", "model_version", "threshold", "cell_id", "uptime"]}

    @router.get("/kpis/current")
    async def current_kpis():
        latest = state.snapshot()["latest_kpi"]
        if latest is None:
            raise HTTPException(status_code=404, detail="No KPI sample received yet")
        return latest

    @router.get("/kpis/history")
    async def kpi_history(minutes: int = 60):
        limit = max(1, min(minutes * 60, 3600))
        return state.snapshot()["history"][-limit:]

    @router.get("/anomalies")
    async def anomalies():
        return state.snapshot()["anomalies"]

    @router.get("/healing")
    async def healing():
        return state.snapshot()["healing"]

    @router.get("/attribution/latest")
    async def latest_attribution():
        return state.snapshot()["latest_attribution"] or {}

    @router.post("/policy")
    async def policy(payload: dict):
        threshold = payload.get("threshold") or payload.get("threshold_3sigma")
        if threshold is not None:
            with state.lock:
                state.threshold = float(threshold)
        return {"accepted": True, "threshold": state.snapshot()["threshold"]}

    @router.post("/inject/{anomaly_type}")
    async def inject(anomaly_type: AnomalyType):
        with state.lock:
            state.injected_anomaly = anomaly_type.value
        event = state.record_event({"type": "MANUAL_INJECTION", "anomaly_type": anomaly_type.value})
        return event

    @router.get("/health")
    async def health():
        return {"ok": True}

    return router
