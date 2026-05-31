from __future__ import annotations

from dataclasses import dataclass

from xapp.ingestion.kpi_schema import AnomalyType


@dataclass
class AnomalyClassification:
    anomaly_type: AnomalyType
    confidence: float
    top_kpis: list[str]
    reasoning: str


class AnomalyClassifier:
    def classify(self, per_feature_mse: dict[str, float]) -> AnomalyClassification:
        ranked = sorted(per_feature_mse, key=per_feature_mse.get, reverse=True)
        top1 = ranked[0]
        top2 = ranked[1] if len(ranked) > 1 else ""
        top3 = ranked[2] if len(ranked) > 2 else ""

        if top1 == "dl_throughput_mbps" and top2 == "latency_ms":
            anomaly_type = AnomalyType.CONGESTION
            reason = "Throughput and latency reconstruction errors dominate."
        elif top1 == "latency_ms" and "dl_throughput_mbps" not in ranked[:2]:
            anomaly_type = AnomalyType.HIGH_LATENCY
            reason = "Latency is the dominant independent error."
        elif top1 == "bler_pct" and "rsrp_dbm" in {top2, top3}:
            anomaly_type = AnomalyType.PACKET_LOSS
            reason = "BLER and RSRP errors point to radio degradation."
        elif top1 == "slice_utilisation_pct":
            anomaly_type = AnomalyType.SLICE_OVERFLOW
            reason = "Slice utilisation is the dominant abnormal KPI."
        else:
            anomaly_type = AnomalyType.NOVEL
            reason = "Error pattern does not match known anomaly signatures."

        total = sum(per_feature_mse.values()) or 1.0
        confidence = min(1.0, per_feature_mse[top1] / total + 0.25)
        return AnomalyClassification(anomaly_type, confidence, ranked, reason)
