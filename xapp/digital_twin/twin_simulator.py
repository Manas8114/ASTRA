from __future__ import annotations

from dataclasses import dataclass

from xapp.healing.action_engine import HealingAction
from xapp.ingestion.kpi_schema import KPIVector
from xapp.model.anomaly_detector import AnomalyDetector


@dataclass
class SimResult:
    projected_state: dict[str, float]
    projected_mse: float
    improvement_pct: float
    approved: bool
    recommendation: str


class DigitalTwinSimulator:
    def __init__(self, detector: AnomalyDetector, approval_threshold: float = 0.20) -> None:
        self.detector = detector
        self.approval_threshold = approval_threshold

    def _state_mse(self, state: dict[str, float]) -> float:
        vector = KPIVector.from_dict(state).to_list()
        import numpy as np

        window = np.array([vector for _ in range(30)], dtype=np.float32)
        return self.detector.score_window(window)[0]

    def simulate_action(
        self,
        action: HealingAction,
        current_state: dict[str, float],
        current_mse: float,
    ) -> SimResult:
        projected = dict(current_state)
        params = action.parameters
        if action.action_type == "ADMISSION_CONTROL":
            pct = params["pct"]
            projected["dl_throughput_mbps"] *= 1 - 0.3 * pct
            projected["latency_ms"] *= 1 - 0.4 * pct
            projected["slice_utilisation_pct"] *= 1 - pct
        elif action.action_type == "HANDOVER_THRESHOLD_ADJUST":
            db = params["db"]
            projected["handover_success_rate"] = min(99.0, projected["handover_success_rate"] + 8 * db)
            projected["latency_ms"] *= 0.95
        elif action.action_type == "SLICE_REBALANCE":
            pct = params["pct"]
            projected["slice_utilisation_pct"] *= 1 - pct
            projected["bler_pct"] *= 1 - 0.5 * pct
            projected["latency_ms"] *= 1 - 0.15 * pct
        elif action.action_type == "POWER_CONTROL":
            db = params["db"]
            projected["rsrp_dbm"] += db
            projected["bler_pct"] *= max(0.3, 1 - 0.1 * db)

        ranges = KPIVector.NORMAL_RANGES
        for key, (low, high) in ranges.items():
            projected[key] = float(max(low * 0.5, min(high * 1.5, projected[key])))

        projected_mse = self._state_mse(projected)
        improvement = (current_mse - projected_mse) / max(current_mse, 1e-9)
        approved = improvement >= self.approval_threshold
        recommendation = (
            "Digital Twin approved action." if approved else "Digital Twin rejected action; escalate."
        )
        return SimResult(projected, projected_mse, float(improvement), approved, recommendation)
