import pytest
from xapp.state import LiveState, utc_now

def test_live_state_snapshot():
    state = LiveState(cell_id="test_cell")
    assert state.cell_id == "test_cell"
    assert state.threshold == 0.02
    assert state.running
    
    event = state.record_event({"type": "KPI_UPDATE", "kpis": {"dl_throughput_mbps": 100.0}})
    assert event["timestamp"] is not None
    
    snap = state.snapshot()
    assert snap["running"]
    assert snap["cell_id"] == "test_cell"
    assert snap["latest_kpi"] == {"dl_throughput_mbps": 100.0}
    assert len(snap["events"]) == 1
