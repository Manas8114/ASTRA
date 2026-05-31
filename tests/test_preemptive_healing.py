import pytest
import numpy as np
import torch
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from xapp.prediction.forecast_head import ForecastHead, ForecastHeadNet, ForecastResult
from xapp.prediction.preemptive_healer import PreemptiveHealer, PreemptiveStatus
from xapp.ingestion.kpi_schema import AnomalyType
from xapp.model.anomaly_detector import AnomalyDetector
from xapp.healing.action_engine import HealingActionEngine, HealingAction
from xapp.state import LiveState
from fastapi.testclient import TestClient
from fastapi import FastAPI
from xapp.api.rest_api import rest_router


def test_forecast_head_net():
    net = ForecastHeadNet(latent_dim=8, hidden=16, n_kpis=6, horizon=10)
    latent = torch.zeros(2, 8)
    last_known = torch.zeros(2, 6)
    out = net(latent, last_known)
    assert out.shape == (2, 10, 6)


def test_forecast_head():
    # Mock anomaly detector
    detector = MagicMock()
    detector.model = MagicMock()
    # Mock encoder to return a 8-dim vector
    detector.model.encode.return_value = torch.zeros(1, 8)
    
    # Instantiate forecaster
    forecaster = ForecastHead(detector)
    
    # Mock predict's underlying net forward call
    forecaster.net = MagicMock()
    # net returns shape (batch, horizon, n_kpis) -> (1, 300, 6)
    # 0.5 represents normal/nominal state, producing no warnings or alert
    forecaster.net.return_value = torch.full((1, 300, 6), 0.5)
    
    window = np.zeros((30, 6))
    res = forecaster.predict(window)
    
    assert isinstance(res, ForecastResult)
    assert res.trajectory.shape == (300, 6)
    assert res.preemptive_alert is False
    assert res.seconds_to_anomaly is None
    assert forecaster._last_result == res


@pytest.mark.asyncio
async def test_preemptive_healer_confidence_gate():
    classifier = MagicMock()
    twin = MagicMock()
    healer = AsyncMock()
    ws = AsyncMock()
    detector = MagicMock()
    
    preemptive = PreemptiveHealer(classifier, twin, healer, ws, detector)
    
    forecast_result = ForecastResult(
        trajectory=np.zeros((300, 6)),
        risk_curve=np.zeros(300),
        preemptive_alert=True,
        seconds_to_anomaly=10,
        confidence=0.5,  # below MIN_CONFIDENCE (0.65)
        at_risk_kpis=["latency_ms"],
        summary="low confidence forecast",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    window = np.zeros((30, 6))
    event = await preemptive.evaluate(forecast_result, window)
    
    assert event.status == PreemptiveStatus.SKIPPED_CONF
    ws.broadcast.assert_any_call({
        "type": "PREVENTION_SKIPPED",
        "reason": "Confidence 50% below threshold 65%",
        "timestamp": event.timestamp
    })
    healer.execute_raw.assert_not_called()


@pytest.mark.asyncio
async def test_preemptive_healer_apply():
    classifier = MagicMock()
    twin = MagicMock()
    
    # Mock DigitalTwinSimulator simulation result
    class MockSimResult:
        improvement_pct = 0.50
        approved = True
        projected_state = {}
        
    twin.simulate_action.return_value = MockSimResult()
    
    healer = AsyncMock()
    ws = AsyncMock()
    detector = MagicMock()
    detector.recent_declared_anomalies.return_value = []
    
    preemptive = PreemptiveHealer(classifier, twin, healer, ws, detector)
    
    forecast_result = ForecastResult(
        trajectory=np.zeros((300, 6)),
        risk_curve=np.zeros(300),
        preemptive_alert=True,
        seconds_to_anomaly=15,
        confidence=0.8,  # above MIN_CONFIDENCE
        at_risk_kpis=["dl_throughput_mbps", "latency_ms"],
        summary="anomaly threat",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    window = np.zeros((30, 6))
    event = await preemptive.evaluate(forecast_result, window)
    
    assert event.status == PreemptiveStatus.APPLIED
    assert event.action_type == "ADMISSION_CONTROL"
    healer.execute_raw.assert_called_once_with(
        action_type="ADMISSION_CONTROL",
        parameters={"pct": 0.10},
        mode="PREEMPTIVE"
    )
    
    # Verify stats
    assert preemptive.stats["applied"] == 1
    assert preemptive.stats["prevented"] == 1


def test_rest_api_forecast_routes():
    state = LiveState(cell_id="cell_test")
    
    # Mock forecaster and preemptive
    forecaster = MagicMock()
    forecaster._last_result = ForecastResult(
        trajectory=np.zeros((300, 6)),
        risk_curve=np.zeros(300),
        preemptive_alert=True,
        seconds_to_anomaly=12,
        confidence=0.9,
        at_risk_kpis=["bler_pct"],
        summary="mock forecast",
        timestamp="2026-06-01T00:00:00Z"
    )
    
    preemptive = MagicMock()
    preemptive.stats = {
        "prevented": 3,
        "false_alarms": 1,
        "applied": 4,
        "prevention_rate": 0.75
    }
    healer = MagicMock()
    healer.total_healed = 5
    preemptive.healer = healer
    
    state.forecaster = forecaster
    state.preemptive = preemptive
    
    app = FastAPI()
    app.include_router(rest_router(state))
    client = TestClient(app)
    
    # Test forecast latest
    response = client.get("/forecast/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["preemptive_alert"] is True
    assert data["seconds_to_anomaly"] == 12
    assert data["at_risk_kpis"] == ["bler_pct"]
    
    # Test prevention stats
    response = client.get("/prevention/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["prevented"] == 3
    assert stats["reactive_healed"] == 5
    assert stats["total_incidents"] == 8
    assert stats["prevention_rate_pct"] == 75.0
