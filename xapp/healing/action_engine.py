from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from xapp.ingestion.kpi_schema import AnomalyType


@dataclass
class HealingAction:
    action_type: str
    parameters: dict[str, float]
    e2_service_model: str = "RC v1.0"
    rationale: str = ""


class HealingActionEngine:
    def __init__(self) -> None:
        self.total_healed = 0

    def candidate_for(self, anomaly_type: AnomalyType) -> HealingAction | None:
        mapping = {
            AnomalyType.CONGESTION: HealingAction(
                "ADMISSION_CONTROL", {"pct": 0.20}, rationale="Reduce load to restore latency."
            ),
            AnomalyType.HIGH_LATENCY: HealingAction(
                "SLICE_REBALANCE", {"pct": 0.25}, rationale="Move delay-sensitive load away."
            ),
            AnomalyType.PACKET_LOSS: HealingAction(
                "POWER_CONTROL", {"db": 10.0}, rationale="Improve RSRP and reduce BLER."
            ),
            AnomalyType.SLICE_OVERFLOW: HealingAction(
                "SLICE_REBALANCE", {"pct": 0.30}, rationale="Shift overloaded slice traffic."
            ),
        }
        return mapping.get(anomaly_type)

    async def execute(
        self,
        anomaly_type: AnomalyType,
        action: HealingAction,
        sim_result: Any,
        kpi_before: dict[str, float],
    ) -> dict[str, Any]:
        self.total_healed += 1
        return {
            "type": "HEALING_APPLIED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "anomaly_type": anomaly_type.value,
            "action_type": action.action_type,
            "parameters": action.parameters,
            "e2_service_model": action.e2_service_model,
            "mttr_seconds": round(2.0 + 5.0 * (1.0 - sim_result.improvement_pct), 2),
            "result": "APPLIED",
            "dt_approval_pct": round(sim_result.improvement_pct * 100.0, 2),
            "kpi_before": kpi_before,
            "kpi_after": sim_result.projected_state,
        }

    async def execute_raw(
        self,
        action_type: str,
        parameters: dict[str, float],
        mode: str = "PREEMPTIVE",
    ) -> None:
        # Simulate execution in the E2 RC service by printing/logging
        pass

