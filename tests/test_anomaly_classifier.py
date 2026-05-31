import pytest
from xapp.ingestion.kpi_schema import AnomalyType
from xapp.classifier.anomaly_classifier import AnomalyClassifier

def test_anomaly_classifier_congestion():
    classifier = AnomalyClassifier()
    mse = {
        "dl_throughput_mbps": 1.0,
        "latency_ms": 0.8,
        "bler_pct": 0.1,
        "rsrp_dbm": 0.1,
        "handover_success_rate": 0.05,
        "slice_utilisation_pct": 0.2
    }
    result = classifier.classify(mse)
    assert result.anomaly_type == AnomalyType.CONGESTION
    assert result.top_kpis[0] == "dl_throughput_mbps"
    assert result.top_kpis[1] == "latency_ms"

def test_anomaly_classifier_high_latency():
    classifier = AnomalyClassifier()
    mse = {
        "dl_throughput_mbps": 0.1,
        "latency_ms": 1.0,
        "bler_pct": 0.1,
        "rsrp_dbm": 0.1,
        "handover_success_rate": 0.05,
        "slice_utilisation_pct": 0.2
    }
    result = classifier.classify(mse)
    assert result.anomaly_type == AnomalyType.HIGH_LATENCY
    assert result.top_kpis[0] == "latency_ms"

def test_anomaly_classifier_packet_loss():
    classifier = AnomalyClassifier()
    mse = {
        "dl_throughput_mbps": 0.1,
        "latency_ms": 0.1,
        "bler_pct": 1.0,
        "rsrp_dbm": 0.8,
        "handover_success_rate": 0.05,
        "slice_utilisation_pct": 0.2
    }
    result = classifier.classify(mse)
    assert result.anomaly_type == AnomalyType.PACKET_LOSS
    assert result.top_kpis[0] == "bler_pct"
    assert "rsrp_dbm" in result.top_kpis[1:3]

def test_anomaly_classifier_slice_overflow():
    classifier = AnomalyClassifier()
    mse = {
        "dl_throughput_mbps": 0.1,
        "latency_ms": 0.1,
        "bler_pct": 0.1,
        "rsrp_dbm": 0.1,
        "handover_success_rate": 0.05,
        "slice_utilisation_pct": 1.0
    }
    result = classifier.classify(mse)
    assert result.anomaly_type == AnomalyType.SLICE_OVERFLOW
    assert result.top_kpis[0] == "slice_utilisation_pct"

def test_anomaly_classifier_novel():
    classifier = AnomalyClassifier()
    mse = {
        "dl_throughput_mbps": 0.1,
        "latency_ms": 0.1,
        "bler_pct": 0.1,
        "rsrp_dbm": 0.1,
        "handover_success_rate": 1.0,
        "slice_utilisation_pct": 0.1
    }
    result = classifier.classify(mse)
    assert result.anomaly_type == AnomalyType.NOVEL
