from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from xapp.ingestion.kpi_schema import KPI_NAMES, KPIVector


@dataclass
class AnomalyResult:
    is_anomaly: bool
    total_mse: float
    per_feature_mse: dict[str, float]
    anomaly_score_normalised: float
    attention_weights: dict[str, float]
    consecutive_anomaly_count: int
    declared: bool
    timestamp: datetime


class MinMaxScalerLite:
    def __init__(self, mins: np.ndarray, maxs: np.ndarray) -> None:
        self.mins = mins.astype(np.float32)
        self.maxs = maxs.astype(np.float32)
        self.span = np.maximum(self.maxs - self.mins, 1e-6)

    def transform(self, data: np.ndarray) -> np.ndarray:
        return (data - self.mins) / self.span

    def inverse_transform(self, data: np.ndarray) -> np.ndarray:
        return data * self.span + self.mins


from collections import deque

class AnomalyDetector:
    def __init__(
        self,
        threshold_path: str = "xapp/model/saved_models/threshold.json",
        scaler_path: str = "training/data/scaler.pkl",
        consecutive_trigger: int = 5,
        min_samples: int = 30,
    ) -> None:
        self.threshold = self._load_threshold(threshold_path)
        self.scaler = self._load_scaler(scaler_path)
        self.consecutive_trigger = consecutive_trigger
        self.consecutive_anomaly_count = 0
        self._normal_mse_history: deque[float] = deque(maxlen=300)
        self.min_samples = min_samples

    def _load_threshold(self, path: str) -> float:
        file_path = Path(path)
        if not file_path.exists():
            return 0.08
        data = json.loads(file_path.read_text())
        return float(data.get("threshold_3sigma", data.get("threshold", 0.08)))

    def _load_scaler(self, path: str) -> MinMaxScalerLite:
        file_path = Path(path)
        if file_path.exists():
            with file_path.open("rb") as handle:
                return pickle.load(handle)
        mins = np.array([r[0] for r in KPIVector.NORMAL_RANGES.values()], dtype=np.float32)
        maxs = np.array([r[1] for r in KPIVector.NORMAL_RANGES.values()], dtype=np.float32)
        return MinMaxScalerLite(mins, maxs)

    def detect(self, window: np.ndarray) -> AnomalyResult:
        total_mse, per_feature, attention = self.score_window(window)
        
        if len(self._normal_mse_history) >= self.min_samples:
            mean_mse = np.mean(self._normal_mse_history)
            std_mse = np.std(self._normal_mse_history)
            self.threshold = float(mean_mse + 3.0 * std_mse)
            
        is_anomaly = total_mse > self.threshold
        self.consecutive_anomaly_count = (
            self.consecutive_anomaly_count + 1 if is_anomaly else 0
        )
        declared = self.consecutive_anomaly_count >= self.consecutive_trigger
        
        if not is_anomaly:
            self._normal_mse_history.append(total_mse)
            
        return AnomalyResult(
            is_anomaly=is_anomaly,
            total_mse=total_mse,
            per_feature_mse=per_feature,
            anomaly_score_normalised=min(1.0, total_mse / max(self.threshold * 10, 1e-9)),
            attention_weights=attention,
            consecutive_anomaly_count=self.consecutive_anomaly_count,
            declared=declared,
            timestamp=datetime.now(timezone.utc),
        )

    def score_window(
        self, window: np.ndarray
    ) -> tuple[float, dict[str, float], dict[str, float]]:
        scaled = self.scaler.transform(window.astype(np.float32))
        normal_center = np.full_like(scaled, 0.5)
        per_feature = ((scaled - normal_center) ** 2).mean(axis=0)
        total_mse = float(per_feature.mean())
        total = float(per_feature.sum()) or 1.0
        attention = {
            name: float(per_feature[i] / total) for i, name in enumerate(KPI_NAMES)
        }
        return (
            total_mse,
            {name: float(per_feature[i]) for i, name in enumerate(KPI_NAMES)},
            attention,
        )
