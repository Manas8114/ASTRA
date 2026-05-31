from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=3600))
    anomalies: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    healing: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))
    lock: Lock = field(default_factory=Lock)

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("timestamp", utc_now())
        with self.lock:
            self.events.append(event)
            if event.get("type") == "KPI_UPDATE":
                self.latest_kpi = event["kpis"]
                self.history.append(event)
            elif event.get("type") == "ANOMALY_DETECTED":
                self.anomalies.append(event)
                self.latest_attribution = event.get("attention_weights")
            elif event.get("type") == "DT_SIMULATION":
                self.latest_simulation = event
            elif event.get("type") == "HEALING_APPLIED":
                self.healing.append(event)
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
