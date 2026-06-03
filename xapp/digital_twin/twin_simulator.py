"""
xapp/digital_twin/twin_simulator.py
─────────────────────────────────────────────────────────────────────────────
Local Digital Twin Simulator — M/M/1 Queuing Model Engine

Uses the same M/M/1 queuing theory as the gRPC twin-service:
  ρ  = λ / μ      (utilisation)
  W  = 1 / (μ(1-ρ))  (mean system time → latency)
  Lq = ρ² / (1-ρ)    (mean queue length)

Healing actions modify λ (arrival rate) and μ (service rate):
  ADMISSION_CONTROL     → reduces λ by pct
  SLICE_REBALANCE       → reduces λ + slight μ increase
  POWER_CONTROL         → increases μ (better link → faster service)
  HANDOVER_THRESHOLD    → reduces handover overhead on μ

BLER modelled as load-dependent: bler ∝ ρ^1.5
Throughput = μ × (1 - ρ)
"""

from __future__ import annotations

import math
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
    queue_metrics: dict[str, float] | None = None


# ── M/M/1 Queuing Primitives ──────────────────────────────────────────────

def _mm1_latency(rho: float, mu: float) -> float:
    """W = 1 / (μ(1 - ρ))"""
    rho = min(rho, 0.98)
    if mu <= 0:
        return 999.0
    return 1.0 / (mu * (1.0 - rho))


def _mm1_queue_length(rho: float) -> float:
    """Lq = ρ² / (1 - ρ)"""
    rho = min(rho, 0.98)
    return (rho ** 2) / (1.0 - rho)


def _load_bler(rho: float, base_bler: float) -> float:
    """BLER ∝ ρ^1.5"""
    return base_bler * (rho ** 1.5)


def _derive_queue_params(state: dict[str, float]) -> tuple[float, float, float]:
    """
    Derive (λ, μ, ρ) from KPI state.

    slice_utilisation_pct ≈ ρ × 100
    dl_throughput_mbps    ≈ μ × (1 - ρ)
    """
    rho = min(max(state.get("slice_utilisation_pct", 50.0) / 100.0, 0.01), 0.98)
    throughput = max(state.get("dl_throughput_mbps", 100.0), 1.0)
    mu = throughput / (1.0 - rho)
    lam = rho * mu
    return lam, mu, rho


# ── Healing Action → Queue Parameter Mapping ──────────────────────────────

def _apply_action(action: HealingAction, lam: float, mu: float, state: dict) -> tuple[float, float, dict]:
    """Apply healing action to λ and μ, return (new_λ, new_μ, state_overrides)."""
    overrides = {}
    params = action.parameters

    if action.action_type == "ADMISSION_CONTROL":
        pct = params.get("pct", 0.10)
        lam *= (1.0 - pct)

    elif action.action_type == "SLICE_REBALANCE":
        pct = params.get("pct", 0.15)
        lam *= (1.0 - pct)
        mu *= 1.05

    elif action.action_type == "POWER_CONTROL":
        db = params.get("db", 5.0)
        mu *= (1.0 + 0.02 * db)
        overrides["rsrp_dbm"] = state.get("rsrp_dbm", -75.0) + db

    elif action.action_type == "HANDOVER_THRESHOLD_ADJUST":
        db = params.get("db", 1.0)
        mu *= (1.0 + 0.01 * db)
        ho = state.get("handover_success_rate", 95.0)
        overrides["handover_success_rate"] = min(99.5, ho + 3.0 * db)

    return lam, mu, overrides


class DigitalTwinSimulator:
    def __init__(self, detector: AnomalyDetector, approval_threshold: float = 0.20) -> None:
        self.detector = detector
        self.approval_threshold = approval_threshold
        import os
        self.mode = os.getenv("ASTRA_MODE", "demo")
        if self.mode == "prod":
            import grpc
            import sys
            sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../twin-service')))
            import twin_pb2
            import twin_pb2_grpc
            self.channel = grpc.insecure_channel('localhost:50051')
            self.stub = twin_pb2_grpc.DigitalTwinStub(self.channel)
            self.twin_pb2 = twin_pb2

    def _state_mse(self, state: dict[str, float]) -> float:
        """Score a projected state through the anomaly detector."""
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
        # ── gRPC mode: delegate to twin-service ────────────────────────
        if self.mode == "prod":
            req = self.twin_pb2.SimulateRequest(
                candidate=self.twin_pb2.CandidateAction(
                    action_type=action.action_type,
                    parameters=action.parameters
                ),
                current_state=current_state,
                current_mse=current_mse
            )
            try:
                resp = self.stub.SimulateAction(req, timeout=2.0)
                return SimResult(
                    projected_state=dict(resp.projected_state),
                    projected_mse=resp.projected_mse,
                    improvement_pct=resp.improvement_pct,
                    approved=resp.approved,
                    recommendation=resp.recommendation
                )
            except Exception as e:
                return SimResult(current_state, current_mse, 0.0, False, f"gRPC Twin Error: {e}")

        # ── Local M/M/1 queuing simulation ─────────────────────────────
        lam_old, mu_old, rho_old = _derive_queue_params(current_state)
        lam_new, mu_new, overrides = _apply_action(action, lam_old, mu_old, current_state)

        new_rho = min(max(lam_new / max(mu_new, 1e-9), 0.01), 0.98)

        projected = dict(current_state)
        projected.update(overrides)

        # Latency from M/M/1
        raw_latency = _mm1_latency(new_rho, mu_new)
        latency_scale = current_state.get("latency_ms", 15.0) / max(_mm1_latency(rho_old, mu_old), 1e-9)
        projected["latency_ms"] = max(2.0, min(200.0, raw_latency * latency_scale))

        # Throughput
        max_throughput = current_state.get("dl_throughput_mbps", 100.0) / max(1.0 - rho_old, 0.02)
        projected["dl_throughput_mbps"] = max(1.0, max_throughput * (1.0 - new_rho))

        # BLER (load-dependent)
        base_bler = current_state.get("bler_pct", 1.0) / max(rho_old ** 1.5, 0.01)
        projected["bler_pct"] = max(0.05, min(30.0, _load_bler(new_rho, base_bler)))

        # Utilisation
        projected["slice_utilisation_pct"] = round(new_rho * 100.0, 2)

        # Handover (preserve if not overridden)
        projected["handover_success_rate"] = min(99.9, max(50.0,
            projected.get("handover_success_rate", current_state.get("handover_success_rate", 95.0))))

        # Clamp all to safe ranges
        ranges = KPIVector.NORMAL_RANGES
        for key, (low, high) in ranges.items():
            projected[key] = float(max(low * 0.5, min(high * 1.5, projected[key])))

        # Score via detector
        projected_mse = self._state_mse(projected)
        improvement = (current_mse - projected_mse) / max(current_mse, 1e-9)
        approved = improvement >= self.approval_threshold

        # Build queue metrics for dashboard
        queue_metrics = {
            "rho_before": round(rho_old, 4),
            "rho_after": round(new_rho, 4),
            "queue_length_before": round(_mm1_queue_length(rho_old), 2),
            "queue_length_after": round(_mm1_queue_length(new_rho), 2),
            "model_type": "M/M/1",
        }

        recommendation = (
            f"M/M/1 approved: ρ {rho_old:.2f}→{new_rho:.2f}, "
            f"Lq {_mm1_queue_length(rho_old):.1f}→{_mm1_queue_length(new_rho):.1f}"
            if approved else
            f"M/M/1 rejected: improvement {improvement:.1%} < {self.approval_threshold:.0%} threshold"
        )

        return SimResult(projected, projected_mse, float(improvement), approved, recommendation, queue_metrics)
