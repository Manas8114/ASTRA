"""
twin-service/server.py
──────────────────────────────────────────────────────────────────────────────
Digital Twin gRPC Service — M/M/1 Queuing Model Engine

Mathematical basis:
  Each cell is modelled as an M/M/1 queue where:
    ρ  = λ / μ  (server utilisation, 0 < ρ < 1 for stability)
    Lq = ρ² / (1 - ρ)  (mean queue length)
    Wq = Lq / λ         (mean queueing delay)
    W  = Wq + 1/μ       (mean system time ≈ latency)

  Healing actions modify λ (arrival rate) and μ (service rate):
    ADMISSION_CONTROL     → reduces λ by pct
    SLICE_REBALANCE       → reduces λ by pct, slight μ increase
    POWER_CONTROL         → increases μ (better link ⇒ faster service)
    HANDOVER_THRESHOLD    → reduces handover-induced overhead on μ

  BLER is modelled as load-dependent: bler ∝ ρ^1.5 (congestion → errors)
  Throughput recovery follows: throughput_new = throughput_max * (1 - ρ_new)

This replaces the earlier stub that simply returned 0.7 * current_mse.
"""

import grpc
from concurrent import futures
import time
import logging

import twin_pb2
import twin_pb2_grpc

log = logging.getLogger("twin_service")


# ── M/M/1 Queuing Model ────────────────────────────────────────────────────

def mm1_latency(rho: float, service_rate: float) -> float:
    """Mean system time W = 1 / (μ - λ) = 1 / (μ * (1 - ρ))"""
    rho = min(rho, 0.98)  # cap to avoid division-by-zero instability
    if service_rate <= 0:
        return 999.0
    return 1.0 / (service_rate * (1.0 - rho))


def mm1_queue_length(rho: float) -> float:
    """Mean queue length Lq = ρ² / (1 - ρ)"""
    rho = min(rho, 0.98)
    return (rho ** 2) / (1.0 - rho)


def load_dependent_bler(rho: float, base_bler: float = 1.0) -> float:
    """BLER increases super-linearly with load: bler = base * ρ^1.5"""
    return base_bler * (rho ** 1.5)


def derive_queue_params(current_state: dict) -> tuple:
    """
    Derive λ (arrival rate) and μ (service rate) from current KPIs.

    slice_utilisation_pct ≈ ρ * 100   (utilisation maps directly to ρ)
    dl_throughput_mbps ≈ μ * (1 - ρ)  (throughput = spare capacity)
    """
    rho = min(max(current_state.get("slice_utilisation_pct", 50.0) / 100.0, 0.01), 0.98)
    throughput = max(current_state.get("dl_throughput_mbps", 100.0), 1.0)

    # μ = throughput / (1 - ρ)   (service rate in "throughput units")
    mu = throughput / (1.0 - rho)
    # λ = ρ * μ
    lam = rho * mu

    return lam, mu, rho


def project_state(action_type: str, parameters: dict, current_state: dict) -> dict:
    """
    Apply a healing action to the M/M/1 model and project new KPI state.
    Returns the full projected KPI dictionary.
    """
    lam, mu, rho = derive_queue_params(current_state)
    projected = dict(current_state)

    # ── Apply healing action to λ and μ ──────────────────────────────────
    if action_type == "ADMISSION_CONTROL":
        pct = parameters.get("pct", 0.10)
        lam *= (1.0 - pct)              # reduce arrival rate

    elif action_type == "SLICE_REBALANCE":
        pct = parameters.get("pct", 0.15)
        lam *= (1.0 - pct)              # offload traffic
        mu *= 1.05                       # freed resources improve service

    elif action_type == "POWER_CONTROL":
        db = parameters.get("db", 5.0)
        mu *= (1.0 + 0.02 * db)         # better SNR → faster PHY → higher μ
        projected["rsrp_dbm"] = current_state.get("rsrp_dbm", -75.0) + db

    elif action_type == "HANDOVER_THRESHOLD_ADJUST":
        db = parameters.get("db", 1.0)
        mu *= (1.0 + 0.01 * db)         # less ping-pong overhead
        ho_rate = current_state.get("handover_success_rate", 95.0)
        projected["handover_success_rate"] = min(99.5, ho_rate + 3.0 * db)

    # ── Compute new ρ and derived KPIs ───────────────────────────────────
    new_rho = min(max(lam / max(mu, 1e-9), 0.01), 0.98)

    # Latency from M/M/1: W = 1 / (μ(1-ρ)), scaled to ms
    raw_latency = mm1_latency(new_rho, mu)
    latency_scale = current_state.get("latency_ms", 15.0) / max(mm1_latency(rho, mu), 1e-9)
    projected["latency_ms"] = max(2.0, min(200.0, raw_latency * latency_scale))

    # Throughput: proportional to spare capacity
    max_throughput = current_state.get("dl_throughput_mbps", 100.0) / max(1.0 - rho, 0.02)
    projected["dl_throughput_mbps"] = max(1.0, max_throughput * (1.0 - new_rho))

    # BLER: load-dependent model
    base_bler = current_state.get("bler_pct", 1.0) / max(rho ** 1.5, 0.01)
    projected["bler_pct"] = max(0.05, min(30.0, load_dependent_bler(new_rho, base_bler)))

    # Slice utilisation: direct from ρ
    projected["slice_utilisation_pct"] = round(new_rho * 100.0, 2)

    # Clamp handover_success_rate
    projected["handover_success_rate"] = min(99.9, max(50.0,
        projected.get("handover_success_rate", current_state.get("handover_success_rate", 95.0))))

    return projected


def compute_mse(current_state: dict, projected_state: dict) -> float:
    """Normalised MSE between current and projected KPI vectors vs normal range centre."""
    normal_ranges = {
        "dl_throughput_mbps": (50.0, 500.0),
        "latency_ms": (5.0, 20.0),
        "bler_pct": (0.1, 5.0),
        "rsrp_dbm": (-80.0, -60.0),
        "handover_success_rate": (95.0, 99.0),
        "slice_utilisation_pct": (20.0, 80.0),
    }
    mse_sum = 0.0
    count = 0
    for key, (lo, hi) in normal_ranges.items():
        span = max(hi - lo, 1e-6)
        curr_norm = (current_state.get(key, 0) - lo) / span
        proj_norm = (projected_state.get(key, 0) - lo) / span
        # Distance from "normal centre" (0.5) — both current and projected contribute
        curr_err = (curr_norm - 0.5) ** 2
        proj_err = (proj_norm - 0.5) ** 2
        # Use projected error as the primary metric; current used for normalisation
        mse_sum += proj_err - curr_err  # positive = improvement, negative = degradation
        count += 1
    return mse_sum / max(count, 1)



# ── gRPC Servicer ──────────────────────────────────────────────────────────

class DigitalTwinServicer(twin_pb2_grpc.DigitalTwinServicer):
    def SimulateAction(self, request, context):
        action_type = request.candidate.action_type
        parameters = dict(request.candidate.parameters)
        current_state = dict(request.current_state)
        current_mse = request.current_mse

        log.info(f"M/M/1 simulation: action={action_type}, params={parameters}")

        # Run queuing model
        projected_state = project_state(action_type, parameters, current_state)
        projected_mse = compute_mse(current_state, projected_state)

        improvement = (current_mse - projected_mse) / max(current_mse, 1e-9)
        approved = improvement > 0.20

        lam_old, mu_old, rho_old = derive_queue_params(current_state)
        lam_new, mu_new, rho_new = derive_queue_params(projected_state)

        recommendation = (
            f"M/M/1 approved: ρ {rho_old:.2f}→{rho_new:.2f}, "
            f"Lq {mm1_queue_length(rho_old):.1f}→{mm1_queue_length(rho_new):.1f}"
            if approved else
            f"M/M/1 rejected: improvement {improvement:.1%} < 20% threshold"
        )

        return twin_pb2.SimulateResponse(
            projected_mse=projected_mse,
            improvement_pct=improvement,
            approved=approved,
            recommendation=recommendation,
            projected_state=projected_state,
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    twin_pb2_grpc.add_DigitalTwinServicer_to_server(DigitalTwinServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Digital Twin gRPC Server (M/M/1 Engine) started on port 50051")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    serve()
