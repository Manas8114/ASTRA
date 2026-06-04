import pytest
# pyrefly: ignore [missing-import]
import numpy as np
from xapp.model.anomaly_detector import AnomalyDetector, MinMaxScalerLite

def test_min_max_scaler_lite():
    mins = np.array([0.0, 10.0])
    maxs = np.array([100.0, 50.0])
    scaler = MinMaxScalerLite(mins, maxs)
    
    data = np.array([[0.0, 10.0], [50.0, 30.0], [100.0, 50.0]])
    transformed = scaler.transform(data)
    assert np.allclose(transformed, [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]])
    
    inverse = scaler.inverse_transform(transformed)
    assert np.allclose(inverse, data)

def test_anomaly_detector_initialization():
    # Uses default mock fallback if files don't exist
    detector = AnomalyDetector(threshold_path="nonexistent_threshold.json", scaler_path="nonexistent_scaler.pkl")
    assert detector.threshold == 0.08
    assert detector.consecutive_trigger == 5
    assert detector.consecutive_anomaly_count == 0

def test_anomaly_detector_score_window():
    detector = AnomalyDetector(threshold_path="nonexistent_threshold.json", scaler_path="nonexistent_scaler.pkl")
    
    # normal_center = 0.5 in MinMaxScalerLite. For the default ranges, normal center means midpoints:
    # dl_throughput_mbps: (50+500)/2 = 275
    # latency_ms: (5+20)/2 = 12.5
    # bler_pct: (0.1+5)/2 = 2.55
    # rsrp_dbm: (-80 + -60)/2 = -70
    # handover_success_rate: (95+99)/2 = 97
    # slice_utilisation_pct: (20+80)/2 = 50
    
    # Let's construct a perfectly centered normal window
    normal_vector = [275.0, 12.5, 2.55, -70.0, 97.0, 50.0]
    window = np.array([normal_vector for _ in range(30)], dtype=np.float32)
    
    total_mse, per_feature, attention = detector.score_window(window)
    # The scaled vector should be all 0.5
    # (scaled - normal_center) ** 2 should be small
    assert abs(total_mse) < 1e-2
    for key in per_feature:
        assert per_feature[key] < 1e-2

def test_anomaly_detector_detect():
    detector = AnomalyDetector(threshold_path="nonexistent_threshold.json", scaler_path="nonexistent_scaler.pkl", consecutive_trigger=3)
    
    # Construct normal window
    normal_vector = [275.0, 12.5, 2.55, -70.0, 97.0, 50.0]
    window_normal = np.array([normal_vector for _ in range(30)], dtype=np.float32)
    
    # Construct highly anomalous window (values far from normal range)
    anomaly_vector = [1000.0, 100.0, 20.0, -20.0, 10.0, 150.0]
    window_anomaly = np.array([anomaly_vector for _ in range(30)], dtype=np.float32)
    
    # 1. First normal window detect
    res = detector.detect(window_normal)
    assert not res.is_anomaly
    assert detector.consecutive_anomaly_count == 0
    assert not res.declared
    
    # 2. First anomaly window detect
    res = detector.detect(window_anomaly)
    assert res.is_anomaly
    assert detector.consecutive_anomaly_count == 1
    assert not res.declared
    
    # 3. Second anomaly window detect
    res = detector.detect(window_anomaly)
    assert detector.consecutive_anomaly_count == 2
    assert not res.declared
    
    # 4. Third anomaly window detect -> should declare!
    res = detector.detect(window_anomaly)
    assert detector.consecutive_anomaly_count == 3
    assert res.declared
    
    # 5. Normal window -> resets counter
    res = detector.detect(window_normal)
    assert not res.is_anomaly
    assert detector.consecutive_anomaly_count == 0
    assert not res.declared

def test_anomaly_detector_dynamic_threshold():
    detector = AnomalyDetector(
        threshold_path="nonexistent_threshold.json", 
        scaler_path="nonexistent_scaler.pkl", 
        min_samples=5
    )
    assert detector.threshold == 0.08
    
    normal_vector = [275.0, 12.5, 2.55, -70.0, 97.0, 50.0]
    window_normal = np.array([normal_vector for _ in range(30)], dtype=np.float32)
    
    for _ in range(5):
        res = detector.detect(window_normal)
        assert not res.is_anomaly
        assert detector.threshold == 0.08
        
    res = detector.detect(window_normal)
    assert detector.threshold == pytest.approx(0.0, abs=1e-2)
    
    anomaly_vector = [350.0, 12.5, 2.55, -70.0, 97.0, 50.0]
    window_anomaly = np.array([anomaly_vector for _ in range(30)], dtype=np.float32)
    
    res_anomaly = detector.detect(window_anomaly)
    assert res_anomaly.is_anomaly
    assert len(detector._normal_mse_history) == 6
