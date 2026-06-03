from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
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

        import os
        self.mode = os.getenv("ASTRA_MODE", "demo")
        
        if self.mode == "prod":
            import onnxruntime as ort
            onnx_path = Path("xapp/model/saved_models/lstm_ae_best.onnx")
            if onnx_path.exists():
                self.onnx_session = ort.InferenceSession(str(onnx_path))
            else:
                print(f"Warning: ONNX model not found at {onnx_path}")
                self.onnx_session = None
        else:
            from xapp.model.lstm_autoencoder import LSTMAutoencoder
            self.model = LSTMAutoencoder().to("cpu")
            ae_path = Path("xapp/model/saved_models/lstm_ae_best.pt")
            self.model_loaded = False
            if ae_path.exists():
                import torch
                try:
                    self.model.load_state_dict(torch.load(ae_path, map_location="cpu"))
                    self.model_loaded = True
                except Exception as e:
                    print(f"Warning: Failed to load model weights: {e}")
            self.model.eval()

        self._declared_anomalies_history: list[datetime] = []

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

        if declared:
            self._declared_anomalies_history.append(datetime.now(timezone.utc))
            
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

    def recent_declared_anomalies(self, window_seconds: int) -> list[datetime]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_seconds)
        self._declared_anomalies_history = [
            t for t in self._declared_anomalies_history
            if t > cutoff - timedelta(minutes=10)
        ]
        return [t for t in self._declared_anomalies_history if t > cutoff]


    def score_window(
        self, window: np.ndarray
    ) -> tuple[float, dict[str, float], dict[str, float]]:
        scaled = self.scaler.transform(window.astype(np.float32))
        
        # Use actual model for reconstruction error
        if self.mode == "prod" and hasattr(self, 'onnx_session') and self.onnx_session is not None:
            # ONNX Inference
            ort_inputs = {self.onnx_session.get_inputs()[0].name: np.expand_dims(scaled, axis=0)}
            reconstructed = self.onnx_session.run(None, ort_inputs)[0][0]
        else:
            # PyTorch Inference
            if getattr(self, "model_loaded", False):
                import torch
                with torch.no_grad():
                    input_tensor = torch.tensor(scaled).unsqueeze(0)
                    reconstructed = self.model(input_tensor).squeeze(0).numpy()
            else:
                reconstructed = np.full_like(scaled, 0.5)
                
        per_feature = ((scaled - reconstructed) ** 2).mean(axis=0)
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
