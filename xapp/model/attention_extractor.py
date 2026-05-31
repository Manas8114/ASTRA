from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AttributionResult:
    weights: dict[str, float]
    top_cause: str
    explanation: str


class AttentionExtractor:
    def extract(self, weights: dict[str, float]) -> AttributionResult:
        top = max(weights, key=weights.get)
        pct = round(weights[top] * 100)
        labels = {
            "bler_pct": "BLER",
            "rsrp_dbm": "RSRP",
            "latency_ms": "latency",
            "dl_throughput_mbps": "throughput",
            "slice_utilisation_pct": "slice utilisation",
            "handover_success_rate": "handover success",
        }
        return AttributionResult(
            weights=weights,
            top_cause=top,
            explanation=f"{labels.get(top, top)} contributed {pct}% of anomaly score.",
        )
