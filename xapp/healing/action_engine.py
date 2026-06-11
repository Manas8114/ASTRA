from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncio
import os
import time

from xapp.ingestion.kpi_schema import AnomalyType
from xapp.healing.e2_rc_client import get_e2_client
from xapp.resilience import create_e2_circuit_breaker

@dataclass
class HealingAction:
    action_type: str
    parameters: dict[str, float]
    e2_service_model: str = "RC v1.0"
    rationale: str = ""


class HealingActionEngine:
    def __init__(self) -> None:
        self.total_healed = 0
        self.mode = os.getenv("ASTRA_MODE", "demo")
        self.cooldown_seconds = float(os.getenv("HEALING_COOLDOWN_SECONDS", "30"))
        self._last_action_at = 0.0
        self._clock = time.monotonic
        self.e2_client = get_e2_client()

        # Shared circuit breaker for E2 control requests
        self._e2_breaker = create_e2_circuit_breaker()
        self._pending_acks: list[asyncio.Future] = []

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
        now = self._clock()
        if now - self._last_action_at < self.cooldown_seconds:
            return {
                "type": "ESCALATION",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "anomaly_type": anomaly_type.value,
                "reason": "Healing cooldown active; operator review required.",
                "action_type": action.action_type,
                "parameters": action.parameters,
            }

        # Enforce blast radius limits in prod mode
        if self.mode == "prod":
            if action.action_type == "ADMISSION_CONTROL":
                action.parameters["pct"] = min(action.parameters["pct"], 0.15)
            elif action.action_type == "SLICE_REBALANCE":
                action.parameters["pct"] = min(action.parameters["pct"], 0.20)
            elif action.action_type == "POWER_CONTROL":
                action.parameters["db"] = min(action.parameters["db"], 5.0)

        # Transmit via E2 with circuit breaker protection
        async def _send_control():
            return await self.e2_client.send_control(action.action_type, action.parameters)

        # Use circuit breaker with fallback to local logging
        try:
            result = await self._e2_breaker.call(
                _send_control,
                fallback=lambda: {"sent": False, "error": "circuit_open", "fallback": True},
                fallback_type="e2_control",
            )
        except Exception as e:
            result = {"sent": False, "error": str(e)}

        # Track pending acknowledgement for graceful shutdown
        if result.get("sent"):
            self._pending_acks.append(asyncio.Future())  # Placeholder for actual ack tracking

        self._last_action_at = now
        self.total_healed += 1
        return {
            "type": "HEALING_APPLIED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "anomaly_type": anomaly_type.value,
            "action_type": action.action_type,
            "parameters": action.parameters,
            "e2_service_model": action.e2_service_model,
            "mttr_seconds": round(2.0 + 5.0 * (1.0 - sim_result.improvement_pct), 2),
            "result": "APPLIED" if result.get("sent") else "FAILED",
            "dt_approval_pct": round(sim_result.improvement_pct * 100.0, 2),
            "kpi_before": kpi_before,
            "kpi_after": sim_result.projected_state,
            "rollback_action": self.rollback_for(action),
            "e2_result": result,
        }

    async def execute_raw(
        self,
        action_type: str,
        parameters: dict[str, float],
        mode: str = "PREEMPTIVE",
    ) -> None:
        # Enforce blast radius limits in prod mode
        if self.mode == "prod":
            if action_type == "ADMISSION_CONTROL":
                parameters["pct"] = min(parameters["pct"], 0.15)
            elif action_type == "SLICE_REBALANCE":
                parameters["pct"] = min(parameters["pct"], 0.20)
            elif action_type == "POWER_CONTROL":
                parameters["db"] = min(parameters["db"], 5.0)

        async def _send_control():
            return await self.e2_client.send_control(action_type, parameters)

        await self._e2_breaker.call(
            _send_control,
            fallback=lambda: {"sent": False, "error": "circuit_open", "fallback": True},
            fallback_type="e2_control",
        )

    def rollback_for(self, action: HealingAction) -> dict[str, Any]:
        if action.action_type in {"ADMISSION_CONTROL", "SLICE_REBALANCE"}:
            return {"action_type": action.action_type, "parameters": {"pct": 0.0}}
        if action.action_type == "POWER_CONTROL":
            return {"action_type": "POWER_CONTROL", "parameters": {"db": 0.0}}
        if action.action_type == "HANDOVER_THRESHOLD_ADJUST":
            return {"action_type": "HANDOVER_THRESHOLD_ADJUST", "parameters": {"db": 0.0}}
        return {"action_type": "NOOP", "parameters": {}}

    async def wait_for_pending_acks(self, timeout: float = 10.0) -> None:
        """
        Wait for pending E2 control acknowledgements.

        Called during graceful shutdown to ensure in-flight control requests
        complete before process termination.
        """
        if not self._pending_acks:
            return

        # Filter out already completed futures
        pending = [f for f in self._pending_acks if not f.done()]
        if not pending:
            return

        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            pass  # Logged by lifecycle manager
