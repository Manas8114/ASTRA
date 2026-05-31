from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


KPI_NAMES = [
    "dl_throughput_mbps",
    "latency_ms",
    "bler_pct",
    "rsrp_dbm",
    "handover_success_rate",
    "slice_utilisation_pct",
]


class AnomalyType(str, Enum):
    CONGESTION = "CONGESTION"
    HIGH_LATENCY = "HIGH_LATENCY"
    PACKET_LOSS = "PACKET_LOSS"
    SLICE_OVERFLOW = "SLICE_OVERFLOW"
    NOVEL = "NOVEL"
    NORMAL = "NORMAL"


@dataclass(frozen=True)
class KPIVector:
    dl_throughput_mbps: float
    latency_ms: float
    bler_pct: float
    rsrp_dbm: float
    handover_success_rate: float
    slice_utilisation_pct: float

    NORMAL_RANGES = {
        "dl_throughput_mbps": (50.0, 500.0),
        "latency_ms": (5.0, 20.0),
        "bler_pct": (0.1, 5.0),
        "rsrp_dbm": (-80.0, -60.0),
        "handover_success_rate": (95.0, 99.0),
        "slice_utilisation_pct": (20.0, 80.0),
    }

    def to_list(self) -> list[float]:
        return [float(getattr(self, name)) for name in KPI_NAMES]

    def to_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in KPI_NAMES}

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> "KPIVector":
        return cls(**{name: float(data[name]) for name in KPI_NAMES})
