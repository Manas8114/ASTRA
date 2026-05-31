import pytest
import numpy as np
from xapp.ingestion.kpi_schema import KPIVector
from xapp.ingestion.kpi_buffer import KPIBuffer

def test_kpi_buffer_initialization():
    buffer = KPIBuffer(window_size=10)
    assert buffer.window_size == 10
    assert not buffer.is_ready()
    assert buffer.get_window() is None

def test_kpi_buffer_push_and_ready():
    buffer = KPIBuffer(window_size=3)
    kpi = KPIVector(100.0, 10.0, 1.0, -70.0, 98.0, 50.0)
    
    buffer.push(kpi)
    assert not buffer.is_ready()
    assert buffer.get_window() is None
    
    buffer.push(kpi)
    buffer.push(kpi)
    assert buffer.is_ready()
    
    window = buffer.get_window()
    assert window is not None
    assert window.shape == (3, 6)
    assert np.allclose(window, [[100.0, 10.0, 1.0, -70.0, 98.0, 50.0]] * 3)

def test_kpi_buffer_recent_average():
    buffer = KPIBuffer(window_size=5)
    assert buffer.recent_average() is None
    
    kpi1 = KPIVector(10.0, 20.0, 1.0, -70.0, 98.0, 50.0)
    kpi2 = KPIVector(20.0, 40.0, 3.0, -80.0, 96.0, 60.0)
    
    buffer.push(kpi1)
    buffer.push(kpi2)
    
    avg = buffer.recent_average(n=2)
    assert avg is not None
    assert avg["dl_throughput_mbps"] == 15.0
    assert avg["latency_ms"] == 30.0
    assert avg["bler_pct"] == 2.0
    assert avg["rsrp_dbm"] == -75.0
    assert avg["handover_success_rate"] == 97.0
    assert avg["slice_utilisation_pct"] == 55.0
