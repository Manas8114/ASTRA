from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
import asyncio
import atexit

import os
import logging

from xapp.persistence.redis_client import redis_client
from xapp.persistence.pg_audit import pg_audit_trail

log = logging.getLogger("astra.state")

# Shared thread pool for sync-blocking operations dispatched from async context.
# Bounded to avoid unbounded thread growth (memory leak).
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="astra-state")
atexit.register(_EXECUTOR.shutdown, wait=False)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ASTRA_MODE = os.getenv("ASTRA_MODE", "demo")


@dataclass
class LiveState:
    cell_id: str
    model_version: str = "dev-synthetic-v1"
    threshold: float = 0.02
    running: bool = True
    injected_anomaly: str | None = None
    started_at: str = field(default_factory=utc_now)
    latest_kpi: dict[str, float] | None = None
    latest_attribution: dict[str, Any] | None = None
    latest_simulation: dict[str, Any] | None = None
    # Bounded deques prevent unbounded memory growth
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=3600))
    anomalies: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    healing: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))
    lock: Lock = field(default_factory=Lock)

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("timestamp", utc_now())
        event_type = event.get("type", "UNKNOWN")

        with self.lock:
            self.events.append(event)
            if event_type == "KPI_UPDATE":
                self.latest_kpi = event["kpis"]
                self.history.append(event)
            elif event_type == "ANOMALY_DETECTED":
                self.anomalies.append(event)
                self.latest_attribution = event.get("attention_weights")
            elif event_type == "DT_SIMULATION":
                self.latest_simulation = event
            elif event_type == "HEALING_APPLIED":
                self.healing.append(event)
            elif event_type == "ROOT_CAUSE_REPORT":
                # CR²E Phase 7: store the latest root-cause report in events deque.
                # No separate deque needed — downstream consumers read from events.
                pass  # event already appended to self.events above


        # Async dispatch for Redis persistence (only in prod mode)
        if ASTRA_MODE == "prod":
            try:
                loop = asyncio.get_running_loop()
                if event_type == "KPI_UPDATE":
                    loop.create_task(redis_client.add_history(self.cell_id, event["kpis"]))
                elif event_type == "ANOMALY_DETECTED":
                    loop.create_task(redis_client.add_anomaly(self.cell_id, event))
                    loop.create_task(
                        redis_client.set_latest_attribution(
                            self.cell_id, event.get("attention_weights", {})
                        )
                    )
                elif event_type == "HEALING_APPLIED":
                    loop.create_task(redis_client.add_healing_action(self.cell_id, event))
            except RuntimeError:
                # No running event loop — we are in a sync context; skip Redis.
                pass

        # Dispatch PG audit trail off the main thread to avoid blocking.
        # Only for non-KPI events to reduce write pressure.
        if event_type != "KPI_UPDATE":
            try:
                loop = asyncio.get_running_loop()
                # In async context: offload blocking I/O to bounded thread pool.
                loop.run_in_executor(
                    _EXECUTOR,
                    pg_audit_trail.append_event,
                    self.cell_id,
                    event_type,
                    event,
                )
            except RuntimeError:
                # In sync context (e.g., tests): call directly.
                try:
                    pg_audit_trail.append_event(self.cell_id, event_type, event)
                except Exception as exc:
                    log.error("Failed to record PG audit event: %s", exc)
            except Exception as exc:
                log.error("Failed to dispatch PG audit event: %s", exc)

        return event

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            uptime = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(self.started_at)
            ).total_seconds()
            return {
                "running": self.running,
                "model_version": self.model_version,
                "threshold": self.threshold,
                "cell_id": self.cell_id,
                "uptime": uptime,
                "latest_kpi": self.latest_kpi,
                "latest_attribution": self.latest_attribution,
                "latest_simulation": self.latest_simulation,
                "history": list(self.history),
                "anomalies": list(self.anomalies),
                "healing": list(self.healing),
                "events": list(self.events),
            }


def dataclass_dict(value: Any) -> dict[str, Any]:
    data = asdict(value)
    for key, item in list(data.items()):
        if isinstance(item, datetime):
            data[key] = item.isoformat()
    return data

class StateManager:
    def __init__(self):
        self._states: dict[str, LiveState] = {}
        self._lock = Lock()

    def get_state(self, cell_id: str) -> LiveState:
        with self._lock:
            if cell_id not in self._states:
                self._states[cell_id] = LiveState(cell_id=cell_id)
            return self._states[cell_id]

    def get_all_states(self) -> dict[str, LiveState]:
        with self._lock:
            return dict(self._states)

