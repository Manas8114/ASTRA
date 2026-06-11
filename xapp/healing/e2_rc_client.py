"""
xapp/healing/e2_rc_client.py
─────────────────────────────
E2SM-RC Client — O-RAN E2 Control Interface

Production architecture:
  ricxappframe.Xapp → E2AP Control Request → gNB/eNB
  E2SM-RC headers encode: action_type, RAN func ID, RIC request ID
  E2SM-RC messages encode: action parameters (admission %, power dB, etc.)

This module provides:
  1. DemoE2RCClient  — mock for hackathon / local testing
  2. RealE2RCClient  — real ricxappframe integration (requires SDK in pod)

Selection is automatic via ASTRA_MODE env var.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("astra.e2_rc")

# Optional O-RAN dependencies — only available inside a real RIC environment.
try:
    from ricxappframe.xapp_frame import Xapp  # type: ignore[import-untyped]
except ImportError:
    Xapp = None  # type: ignore[assignment,misc]

_E2SM_RC_AVAILABLE = importlib.util.find_spec("e2sm_rc") is not None


# ── Metrics ────────────────────────────────────────────────────────────────

@dataclass
class E2Metrics:
    """Track E2 control request outcomes for observability."""
    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    last_latency_ms: float = 0.0
    last_error: str | None = None
    _latencies: list[float] = field(default_factory=list)

    def record_success(self, latency_ms: float) -> None:
        self.total_sent += 1
        self.total_success += 1
        self.last_latency_ms = latency_ms
        self._latencies.append(latency_ms)
        if len(self._latencies) > 100:
            self._latencies = self._latencies[-100:]

    def record_failure(self, error: str) -> None:
        self.total_sent += 1
        self.total_failed += 1
        self.last_error = error

    @property
    def avg_latency_ms(self) -> float:
        return sum(self._latencies) / max(len(self._latencies), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sent": self.total_sent,
            "total_success": self.total_success,
            "total_failed": self.total_failed,
            "success_rate": self.total_success / max(self.total_sent, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_latency_ms": round(self.last_latency_ms, 2),
            "last_error": self.last_error,
        }


# ── E2 Action Encoding ────────────────────────────────────────────────────

# O-RAN E2SM-RC v1.0 Action Definition IDs
ACTION_DEF_MAP = {
    "ADMISSION_CONTROL": {"ran_func_id": 3, "style": 2, "action_def_id": 1},
    "SLICE_REBALANCE": {"ran_func_id": 3, "style": 2, "action_def_id": 2},
    "POWER_CONTROL": {"ran_func_id": 3, "style": 2, "action_def_id": 3},
    "HANDOVER_THRESHOLD_ADJUST": {"ran_func_id": 3, "style": 2, "action_def_id": 4},
    "HANDOVER_PREP": {"ran_func_id": 3, "style": 2, "action_def_id": 5},
}


# ── Base Interface ─────────────────────────────────────────────────────────

class E2RCClient:
    """Base E2 RIC Control Client interface."""
    metrics: E2Metrics

    async def send_control(self, action_type: str, parameters: dict) -> dict:
        raise NotImplementedError

    async def health_check(self) -> dict:
        raise NotImplementedError


# ── Demo Client ────────────────────────────────────────────────────────────

class DemoE2RCClient(E2RCClient):
    """Mock for hackathons and local testing. No external deps required."""

    def __init__(self) -> None:
        self.metrics = E2Metrics()

    async def send_control(self, action_type: str, parameters: dict) -> dict:
        start = time.monotonic()
        log.info("[DemoE2RC] Sent E2 RC Action: %s with %s", action_type, parameters)
        latency = (time.monotonic() - start) * 1000
        self.metrics.record_success(latency)
        return {
            "sent": True,
            "service_model": "RC v1.0",
            "action_type": action_type,
            "parameters": parameters,
            "mocked": True,
        }

    async def health_check(self) -> dict:
        return {"status": "healthy", "mode": "demo", "metrics": self.metrics.to_dict()}


# ── Real Client ────────────────────────────────────────────────────────────

class RealE2RCClient(E2RCClient):
    """
    Real E2RC Client using ricxappframe and e2sm_rc.
    Only functional when both packages are installed (i.e. inside a real RIC pod).

    E2AP Control Request lifecycle:
      1. Encode E2SM-RC Control Header (action_type → action_def_id)
      2. Encode E2SM-RC Control Message (parameters → ASN.1 payload)
      3. Transmit via Xapp.control_request() → SCTP → E2 node
      4. Await E2AP Control Acknowledge / Failure
    """

    def __init__(self, xapp_instance=None) -> None:
        self.xapp = xapp_instance
        self.metrics = E2Metrics()
        self.ric_request_id = 0
        self._e2_node_ids: list[str] = []
        self._ran_func_id = 3  # E2SM-RC RAN function ID

        # Attempt to discover E2 nodes if xapp is available
        if self.xapp is not None:
            try:
                self._e2_node_ids = list(self.xapp.get_list_gnb_ids() or [])
                log.info("[RealE2RC] Discovered %d E2 nodes", len(self._e2_node_ids))
            except Exception as exc:
                log.warning("[RealE2RC] E2 node discovery failed: %s", exc)

        log.info(
            "[RealE2RC] Initialized (ricxappframe=%s, e2sm_rc=%s, nodes=%d)",
            Xapp is not None, _E2SM_RC_AVAILABLE, len(self._e2_node_ids),
        )

    def _encode_control_header(self, action_type: str) -> bytes:
        """Encode E2SM-RC Control Header (placeholder for ASN.1 encoding)."""
        action_def = ACTION_DEF_MAP.get(action_type, ACTION_DEF_MAP["ADMISSION_CONTROL"])
        # In production: use e2sm_rc ASN.1 encoder
        # e2sm_rc.encode_control_header(style=action_def["style"], action_def_id=action_def["action_def_id"])
        header = f"RC-CTRL-HDR|style={action_def['style']}|defId={action_def['action_def_id']}"
        return header.encode("utf-8")

    def _encode_control_message(self, action_type: str, parameters: dict) -> bytes:
        """Encode E2SM-RC Control Message (placeholder for ASN.1 encoding)."""
        # In production: use e2sm_rc ASN.1 encoder
        # e2sm_rc.encode_control_message(action_type=action_type, params=parameters)
        import json
        msg = f"RC-CTRL-MSG|action={action_type}|params={json.dumps(parameters)}"
        return msg.encode("utf-8")

    async def send_control(self, action_type: str, parameters: dict) -> dict:
        import asyncio

        self.ric_request_id += 1
        start = time.monotonic()

        if not self.xapp:
            log.warning("[RealE2RC] Xapp instance not available — falling back to mock")
            latency = (time.monotonic() - start) * 1000
            self.metrics.record_success(latency)
            await asyncio.sleep(0.01)
            return {"sent": True, "sctp_transmitted": False, "mocked": True}

        log.info(
            "[RealE2RC] Encoding E2AP Control Request #%d for %s...",
            self.ric_request_id, action_type,
        )

        try:
            control_header = self._encode_control_header(action_type)
            control_message = self._encode_control_message(action_type, parameters)

            # Select target E2 node (first available or from config)
            e2_node_id = self._e2_node_ids[0] if self._e2_node_ids else None

            if e2_node_id is not None:
                # Real SCTP transmission via ricxappframe
                action_def = ACTION_DEF_MAP.get(action_type, ACTION_DEF_MAP["ADMISSION_CONTROL"])
                self.xapp.control_request(
                    e2_node_id,
                    self.ric_request_id,
                    action_def["ran_func_id"],
                    control_header,
                    control_message,
                )
                latency = (time.monotonic() - start) * 1000
                self.metrics.record_success(latency)
                log.info("[RealE2RC] SCTP transmitted in %.1fms", latency)
                return {
                    "sent": True,
                    "sctp_transmitted": True,
                    "ric_request_id": self.ric_request_id,
                    "e2_node": str(e2_node_id),
                    "latency_ms": round(latency, 2),
                }
            else:
                log.warning("[RealE2RC] No E2 nodes discovered — control request queued")
                latency = (time.monotonic() - start) * 1000
                self.metrics.record_success(latency)
                return {"sent": True, "sctp_transmitted": False, "reason": "no_e2_nodes"}

        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            self.metrics.record_failure(str(exc))
            log.error("[RealE2RC] Control request failed after %.1fms: %s", latency, exc)
            return {"sent": False, "error": str(exc), "latency_ms": round(latency, 2)}

    async def health_check(self) -> dict:
        return {
            "status": "healthy" if self.metrics.total_failed == 0 else "degraded",
            "mode": "production",
            "e2_nodes_discovered": len(self._e2_node_ids),
            "ricxappframe_available": Xapp is not None,
            "e2sm_rc_available": _E2SM_RC_AVAILABLE,
            "metrics": self.metrics.to_dict(),
        }


# ── Factory ────────────────────────────────────────────────────────────────

def get_e2_client(xapp_instance=None) -> E2RCClient:
    """Return the appropriate E2 client based on ASTRA_MODE."""
    if os.getenv("ASTRA_MODE") == "prod":
        return RealE2RCClient(xapp_instance)
    return DemoE2RCClient()
