from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

import os
import json
import sqlite3
ASTRA_MODE = os.getenv("ASTRA_MODE", "demo")
redis_client = None
if ASTRA_MODE == "prod":
    try:
        import redis
        redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0)
    except Exception as e:
        print(f"Warning: Failed to connect to Redis: {e}")


class EventStore:
    def __init__(self, path: str = "data/astra_events.db") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def append(self, cell_id: str, event: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO events(cell_id, event_type, timestamp, payload) VALUES (?, ?, ?, ?)",
            (
                cell_id,
                str(event.get("type", "UNKNOWN")),
                str(event.get("timestamp", utc_now())),
                json.dumps(event),
            ),
        )
        self.conn.commit()


def make_event_store() -> EventStore | None:
    if os.getenv("ASTRA_DISABLE_EVENT_DB", "").lower() == "true":
        return None
    try:
        return EventStore(os.getenv("ASTRA_EVENT_DB", "data/astra_events.db"))
    except Exception as exc:
        print(f"Warning: event DB disabled: {exc}")
        return None


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
    event_store: EventStore | None = field(default_factory=make_event_store)
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
            if self.event_store:
                try:
                    self.event_store.append(self.cell_id, event)
                except Exception:
                    pass
                
            if redis_client:
                try:
                    redis_client.lpush(f"astra:{self.cell_id}:events", json.dumps(event))
                    redis_client.ltrim(f"astra:{self.cell_id}:events", 0, 1000)
                except Exception:
                    pass
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
