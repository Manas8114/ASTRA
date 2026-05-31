import pytest
from xapp.ingestion.kpi_schema import AnomalyType
from xapp.healing.action_engine import HealingActionEngine, HealingAction

def test_healing_engine_candidate_for():
    engine = HealingActionEngine()
    
    assert engine.candidate_for(AnomalyType.NOVEL) is None
    assert engine.candidate_for(AnomalyType.NORMAL) is None
    
    congestion_action = engine.candidate_for(AnomalyType.CONGESTION)
    assert congestion_action is not None
    assert congestion_action.action_type == "ADMISSION_CONTROL"
    assert congestion_action.parameters == {"pct": 0.20}
    
    packet_loss_action = engine.candidate_for(AnomalyType.PACKET_LOSS)
    assert packet_loss_action is not None
    assert packet_loss_action.action_type == "POWER_CONTROL"
    assert packet_loss_action.parameters == {"db": 10.0}

@pytest.mark.asyncio
async def test_healing_engine_execute():
    engine = HealingActionEngine()
    action = HealingAction("ADMISSION_CONTROL", {"pct": 0.20})
    
    class MockSimResult:
        improvement_pct = 0.50
        projected_state = {"dl_throughput_mbps": 80.0}
        
    sim_result = MockSimResult()
    kpi_before = {"dl_throughput_mbps": 100.0}
    
    res = await engine.execute(AnomalyType.CONGESTION, action, sim_result, kpi_before)
    assert res["type"] == "HEALING_APPLIED"
    assert res["anomaly_type"] == AnomalyType.CONGESTION.value
    assert res["action_type"] == "ADMISSION_CONTROL"
    assert res["parameters"] == {"pct": 0.20}
    assert res["dt_approval_pct"] == 50.0
    assert res["kpi_before"] == kpi_before
    assert res["kpi_after"] == {"dl_throughput_mbps": 80.0}
