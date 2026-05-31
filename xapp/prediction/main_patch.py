"""
xapp/main_patch.py
───────────────────
HOW TO INTEGRATE PREDICTIVE HEALING INTO YOUR EXISTING xapp/main.py

This file shows the EXACT lines to add. It is not a replacement —
it is a diff/guide. Search for the comments marked ★ ADD and ★ MODIFY
in your existing main.py and insert the indicated lines.

Your existing main.py structure (from README):
  1. Load LSTM model + scaler + threshold
  2. Start WebSocket server
  3. Start REST API
  4. Connect to FlexRIC E2 / subscribe to KPM
  5. Start A1 policy receiver
  6. Start Federated Learning client
  7. Main detection loop

Changes needed:
  A. Import 2 new modules (3 lines)
  B. Instantiate after anomaly_detector is created (5 lines)
  C. Add one async call inside the main loop (7 lines)
  D. Add 2 new REST endpoints (20 lines)
  E. Add forecast trajectory to KPI_UPDATE broadcast (3 lines)

Total new lines in main.py: ~38 lines.
"""

# ════════════════════════════════════════════════════════════════════════════
# A. ADD these imports at the top of main.py (after existing imports)
# ════════════════════════════════════════════════════════════════════════════

from xapp.prediction.forecast_head import ForecastHead
from xapp.prediction.preemptive_healer import PreemptiveHealer

# ════════════════════════════════════════════════════════════════════════════
# B. ADD these lines AFTER anomaly_detector is instantiated in startup
#    (roughly after: detector = AnomalyDetector())
# ════════════════════════════════════════════════════════════════════════════

# ★ ADD — predictive healing modules
forecaster = ForecastHead(anomaly_detector=detector)
preemptive = PreemptiveHealer(
    anomaly_classifier=classifier,
    digital_twin=twin,
    healing_engine=healer,
    websocket_server=ws_server,
    anomaly_detector=detector,
)
log.info("ForecastHead and PreemptiveHealer initialised.")

# ════════════════════════════════════════════════════════════════════════════
# C. MODIFY the main detection loop
#
# Your existing loop (approximate):
#
#   while True:
#       kpi_vec = await e2_client.get_next_kpi()
#       buffer.push(kpi_vec)
#       await ws_server.broadcast({"type": "KPI_UPDATE", ...})
#
#       if buffer.is_ready():
#           window = buffer.get_window()
#           result = detector.detect(window)
#           if result.declared:
#               # ... classify, DT validate, heal ...
#
# ADD this block INSIDE the loop, right after buffer.is_ready() check,
# BEFORE the existing anomaly detection block:
# ════════════════════════════════════════════════════════════════════════════

        # ★ ADD — run forecast every tick when buffer is ready
        if buffer.is_ready():
            window = buffer.get_window()

            # --- PREDICTIVE PATH (new) ---
            forecast = forecaster.predict(window)

            # Broadcast forecast risk curve to dashboard
            await ws_server.broadcast({
                "type": "FORECAST_UPDATE",
                "timestamp": forecast.timestamp,
                "preemptive_alert": forecast.preemptive_alert,
                "seconds_to_anomaly": forecast.seconds_to_anomaly,
                "at_risk_kpis": forecast.at_risk_kpis,
                "confidence": forecast.confidence,
                "risk_curve_60s": forecast.risk_curve[:60].tolist(),  # 60-second view
                "summary": forecast.summary,
            })

            if forecast.preemptive_alert:
                # Evaluate and potentially apply pre-emptive healing
                # This is non-blocking (async) — does not delay reactive path
                asyncio.create_task(
                    preemptive.evaluate(forecast, window)
                )

            # --- REACTIVE PATH (existing — unchanged) ---
            result = detector.detect(window)
            if result.declared:
                # ... your existing classify → DT → heal code ...
                pass

# ════════════════════════════════════════════════════════════════════════════
# D. ADD these REST API endpoints in xapp/api/rest_api.py
# ════════════════════════════════════════════════════════════════════════════

# In rest_api.py, add these two endpoints:

from fastapi import APIRouter
router = APIRouter()

@router.get("/forecast/latest")
async def get_latest_forecast():
    """
    Returns the most recent ForecastResult.
    Dashboard uses this to populate the ForecastPanel component.
    """
    if not hasattr(forecaster, "_last_result") or forecaster._last_result is None:
        return {"status": "no_forecast_yet"}
    r = forecaster._last_result
    return {
        "preemptive_alert": r.preemptive_alert,
        "seconds_to_anomaly": r.seconds_to_anomaly,
        "at_risk_kpis": r.at_risk_kpis,
        "confidence": r.confidence,
        "risk_curve_60s": r.risk_curve[:60].tolist(),
        "summary": r.summary,
        "timestamp": r.timestamp,
    }


@router.get("/prevention/stats")
async def get_prevention_stats():
    """
    Returns prevention statistics for the dashboard counter panel.
    """
    return {
        **preemptive.stats,
        "reactive_healed": healer.total_healed,       # existing counter
        "total_incidents": preemptive.stats["prevented"] + healer.total_healed,
        "prevention_rate_pct": round(
            preemptive.stats["prevention_rate"] * 100, 1
        ),
    }


# ════════════════════════════════════════════════════════════════════════════
# E. MODIFY KPI_UPDATE broadcast to include forecast data
#
# Find the line in your main loop that broadcasts KPI_UPDATE.
# It probably looks like:
#
#   await ws_server.broadcast({
#       "type": "KPI_UPDATE",
#       "timestamp": ...,
#       "kpis": { 6 fields },
#   })
#
# ★ MODIFY it to also include the forecast:
# ════════════════════════════════════════════════════════════════════════════

        await ws_server.broadcast({
            "type": "KPI_UPDATE",
            "timestamp": kpi_vec.timestamp,
            "kpis": {
                "dl_throughput_mbps": kpi_vec.dl_throughput_mbps,
                "latency_ms": kpi_vec.latency_ms,
                "bler_pct": kpi_vec.bler_pct,
                "rsrp_dbm": kpi_vec.rsrp_dbm,
                "handover_success_rate": kpi_vec.handover_success_rate,
                "slice_utilisation_pct": kpi_vec.slice_utilisation_pct,
            },
            # ★ ADD these 3 fields:
            "forecast_alert": forecast.preemptive_alert if buffer.is_ready() else False,
            "forecast_confidence": forecast.confidence if buffer.is_ready() else None,
            "prevention_stats": preemptive.stats,
        })
