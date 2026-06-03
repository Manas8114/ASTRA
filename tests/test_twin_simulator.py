import pytest
from xapp.model.anomaly_detector import AnomalyDetector
from xapp.digital_twin.twin_simulator import (
    DigitalTwinSimulator,
    _derive_queue_params,
    _mm1_latency,
    _mm1_queue_length,
)
from xapp.healing.action_engine import HealingAction


def test_mm1_queue_math():
    """Verify M/M/1 formulas are correct."""
    # ρ=0.5, μ=10 → W = 1/(10*0.5) = 0.2
    assert _mm1_latency(0.5, 10.0) == pytest.approx(0.2)
    # ρ=0.8, μ=10 → W = 1/(10*0.2) = 0.5
    assert _mm1_latency(0.8, 10.0) == pytest.approx(0.5)
    # Lq at ρ=0.5 → 0.25/0.5 = 0.5
    assert _mm1_queue_length(0.5) == pytest.approx(0.5)
    # Lq at ρ=0.8 → 0.64/0.2 = 3.2
    assert _mm1_queue_length(0.8) == pytest.approx(3.2)


def test_derive_queue_params():
    """Verify that λ, μ, ρ are correctly derived from KPI state."""
    state = {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 15.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 50.0,
    }
    lam, mu, rho = _derive_queue_params(state)
    assert rho == pytest.approx(0.5)
    # μ = throughput / (1 - ρ) = 100 / 0.5 = 200
    assert mu == pytest.approx(200.0)
    # λ = ρ * μ = 0.5 * 200 = 100
    assert lam == pytest.approx(100.0)


def test_twin_simulator_admission_control():
    detector = AnomalyDetector(
        threshold_path="nonexistent_threshold.json",
        scaler_path="nonexistent_scaler.pkl",
    )
    simulator = DigitalTwinSimulator(detector, approval_threshold=0.10)

    current_state = {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 15.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 50.0,
    }

    action = HealingAction("ADMISSION_CONTROL", {"pct": 0.20})
    res = simulator.simulate_action(action, current_state, current_mse=0.5)

    assert res.projected_state is not None
    # After ADMISSION_CONTROL, utilisation should decrease
    assert res.projected_state["slice_utilisation_pct"] < 50.0
    # Latency should improve (decrease)
    assert res.projected_state["latency_ms"] <= current_state["latency_ms"]
    # Queue metrics should be present
    assert res.queue_metrics is not None
    assert res.queue_metrics["model_type"] == "M/M/1"
    assert res.queue_metrics["rho_after"] < res.queue_metrics["rho_before"]


def test_twin_simulator_power_control():
    detector = AnomalyDetector(
        threshold_path="nonexistent_threshold.json",
        scaler_path="nonexistent_scaler.pkl",
    )
    simulator = DigitalTwinSimulator(detector, approval_threshold=0.10)

    current_state = {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 15.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 50.0,
    }

    action = HealingAction("POWER_CONTROL", {"db": 5.0})
    res = simulator.simulate_action(action, current_state, current_mse=0.5)

    assert res.projected_state is not None
    # RSRP should increase by db amount (clamped to range)
    assert res.projected_state["rsrp_dbm"] > current_state["rsrp_dbm"]
    # Recommendation should contain M/M/1 text
    assert "M/M/1" in res.recommendation


def test_twin_simulator_slice_rebalance():
    detector = AnomalyDetector(
        threshold_path="nonexistent_threshold.json",
        scaler_path="nonexistent_scaler.pkl",
    )
    simulator = DigitalTwinSimulator(detector, approval_threshold=0.10)

    current_state = {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 15.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 70.0,  # high utilisation
    }

    action = HealingAction("SLICE_REBALANCE", {"pct": 0.25})
    res = simulator.simulate_action(action, current_state, current_mse=0.5)

    assert res.projected_state["slice_utilisation_pct"] < 70.0
    assert res.queue_metrics["rho_after"] < res.queue_metrics["rho_before"]
    assert res.queue_metrics["queue_length_after"] < res.queue_metrics["queue_length_before"]
