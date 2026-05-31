import pytest
from xapp.ingestion.kpi_schema import KPIVector, AnomalyType, KPI_NAMES

def test_kpi_vector_initialization():
    vector = KPIVector(
        dl_throughput_mbps=100.0,
        latency_ms=10.0,
        bler_pct=1.0,
        rsrp_dbm=-70.0,
        handover_success_rate=98.0,
        slice_utilisation_pct=50.0
    )
    assert vector.dl_throughput_mbps == 100.0
    assert vector.latency_ms == 10.0
    assert vector.bler_pct == 1.0
    assert vector.rsrp_dbm == -70.0
    assert vector.handover_success_rate == 98.0
    assert vector.slice_utilisation_pct == 50.0

def test_kpi_vector_to_list():
    vector = KPIVector(
        dl_throughput_mbps=100.0,
        latency_ms=10.0,
        bler_pct=1.0,
        rsrp_dbm=-70.0,
        handover_success_rate=98.0,
        slice_utilisation_pct=50.0
    )
    lst = vector.to_list()
    assert len(lst) == 6
    assert lst == [100.0, 10.0, 1.0, -70.0, 98.0, 50.0]

def test_kpi_vector_to_dict():
    vector = KPIVector(
        dl_throughput_mbps=100.0,
        latency_ms=10.0,
        bler_pct=1.0,
        rsrp_dbm=-70.0,
        handover_success_rate=98.0,
        slice_utilisation_pct=50.0
    )
    d = vector.to_dict()
    assert d == {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 10.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 50.0
    }

def test_kpi_vector_from_dict():
    data = {
        "dl_throughput_mbps": 100.0,
        "latency_ms": 10.0,
        "bler_pct": 1.0,
        "rsrp_dbm": -70.0,
        "handover_success_rate": 98.0,
        "slice_utilisation_pct": 50.0
    }
    vector = KPIVector.from_dict(data)
    assert vector.dl_throughput_mbps == 100.0
    assert vector.rsrp_dbm == -70.0
