import pytest
from xapp.model.anomaly_detector import AnomalyDetector
from xapp.digital_twin.twin_simulator import DigitalTwinSimulator
from xapp.healing.action_engine import HealingAction

def test_twin_simulator():
    detector = AnomalyDetector(threshold_path="nonexistent_threshold.json", scaler_path="nonexistent_scaler.pkl")
    simulator = DigitalTwinSimulator(detector, approval_threshold=0.10)
    
    current_state = {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 15.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 50.0
    }
    
    action = HealingAction("ADMISSION_CONTROL", {"pct": 0.20})
    # This should modify state values and then score them
    res = simulator.simulate_action(action, current_state, current_mse=0.5)
    assert res.projected_state is not None
    # For ADMISSION_CONTROL with pct=0.20:
    # dl_throughput_mbps *= 1 - 0.3 * 0.2 => 0.94
    # latency_ms *= 1 - 0.4 * 0.2 => 0.92
    # slice_utilisation_pct *= 1 - 0.2 => 0.8
    assert res.projected_state["dl_throughput_mbps"] == pytest.approx(94.0)
    assert res.projected_state["latency_ms"] == pytest.approx(13.8)
    assert res.projected_state["slice_utilisation_pct"] == pytest.approx(40.0)
    
    # Check other actions
    action_power = HealingAction("POWER_CONTROL", {"db": 5.0})
    res_power = simulator.simulate_action(action_power, current_state, current_mse=0.5)
    assert res_power.projected_state["rsrp_dbm"] == pytest.approx(-40.0)
    # bler_pct *= max(0.3, 1 - 0.1 * 5.0) => 0.5
    assert res_power.projected_state["bler_pct"] == pytest.approx(0.5)
