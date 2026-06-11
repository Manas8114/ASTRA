"""
xapp/prediction/forecast_head.py
─────────────────────────────────
ASTRA Predictive Healing — Forecast Head

Attaches to the existing LSTMAutoencoder's encoder output (latent vector)
and predicts the next FORECAST_HORIZON timesteps of all 6 KPIs.

This is a Seq2Seq decoder: given the 8-dim bottleneck vector from the
existing LSTM encoder, it unrolls a new LSTM to produce a future KPI
trajectory. It does NOT modify the existing model — it is a separate
module that shares the encoder's weights read-only.

Architecture:
  Input:  encoder latent vector (8,)
  Hidden: LSTM(8 → 32 → 16)
  Output: Linear(16 → 6) per timestep × FORECAST_HORIZON

Training:
  Teacher forcing on the existing normal_kpis.csv.
  Loss: MSE between predicted future and actual future windows.
  Trained independently from the autoencoder — load ae weights frozen,
  train only forecast_head weights.

Usage:
  detector = AnomalyDetector()           # existing
  forecaster = ForecastHead(detector)
  result = forecaster.predict(window)    # → ForecastResult
"""

import torch  # type: ignore[import-untyped]
import torch.nn as nn  # type: ignore[import-untyped]
import numpy as np  # type: ignore[import-untyped]
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import json
import logging

from xapp.device import get_device, safe_to_device, clear_gpu_cache

log = logging.getLogger("astra.forecast")

FORECAST_HORIZON = 300      # 5 minutes at 1s resolution
PREEMPTIVE_HORIZON = 60     # flag if anomaly predicted within 60 seconds
FORECAST_MODEL_PATH = Path("xapp/model/saved_models/forecast_head.pt")
THRESHOLD_PATH = Path("xapp/model/saved_models/threshold.json")


# ── Forecast Head Network ───────────────────────────────────────────────────

class ForecastHeadNet(nn.Module):
    """
    Seq2Seq decoder that takes the encoder's 8-dim latent vector
    and produces a future KPI trajectory of shape (FORECAST_HORIZON, 6).
    """

    def __init__(self, latent_dim: int = 8, hidden: int = 32, n_kpis: int = 6,
                 horizon: int = FORECAST_HORIZON):
        super().__init__()
        self.horizon = horizon
        self.n_kpis = n_kpis

        # Project latent → LSTM hidden state
        self.latent_to_hidden = nn.Linear(latent_dim, hidden)

        # LSTM unrolls over forecast horizon
        self.lstm = nn.LSTM(
            input_size=n_kpis,
            hidden_size=hidden,
            num_layers=2,
            batch_first=True,
            dropout=0.1,
        )

        # Project LSTM hidden → KPI prediction
        self.output_proj = nn.Linear(hidden, n_kpis)

        # Dropout for regularisation
        self.dropout = nn.Dropout(0.1)

    def forward(self, latent: torch.Tensor,
                last_known: torch.Tensor) -> torch.Tensor:
        """
        Args:
            latent:     (batch, 8)   — encoder bottleneck
            last_known: (batch, 6)   — last observed KPI vector (seed step)

        Returns:
            forecast:   (batch, horizon, 6)
        """
        # batch dimension — used implicitly by LSTM; no explicit reference needed

        # Initialise LSTM hidden from latent
        h0 = self.latent_to_hidden(latent)            # (batch, hidden)
        h0 = h0.unsqueeze(0).repeat(2, 1, 1)         # (num_layers, batch, hidden)
        c0 = torch.zeros_like(h0)

        # Autoregressive decode
        outputs = []
        x = last_known.unsqueeze(1)                   # (batch, 1, 6)
        hidden = (h0, c0)

        for _ in range(self.horizon):
            out, hidden = self.lstm(x, hidden)        # out: (batch, 1, hidden)
            pred = self.output_proj(self.dropout(out))  # (batch, 1, 6)
            outputs.append(pred)
            x = pred                                   # feed prediction back in

        return torch.cat(outputs, dim=1)              # (batch, horizon, 6)


# ── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class ForecastResult:
    """Output of ForecastHead.predict()"""

    # Raw trajectory: shape (FORECAST_HORIZON, 6) — normalised [0,1]
    trajectory: np.ndarray

    # Per-KPI per-timestep reconstruction error vs threshold
    # Shape: (FORECAST_HORIZON,) — MSE of predicted KPIs vs normal range
    risk_curve: np.ndarray

    # Will an anomaly be predicted within PREEMPTIVE_HORIZON seconds?
    preemptive_alert: bool

    # If alert: seconds until predicted threshold crossing
    seconds_to_anomaly: Optional[int]

    # Confidence of the forecast (1 - normalised forecast MSE on val set)
    confidence: float

    # Which KPIs are driving the predicted risk
    at_risk_kpis: list[str]

    # Human-readable summary
    summary: str

    # Timestamp
    timestamp: str = ""


# ── Main Forecaster Class ────────────────────────────────────────────────────

class ForecastHead:
    """
    Wraps ForecastHeadNet and exposes a simple predict() interface.
    Loads the existing AnomalyDetector's encoder weights read-only
    and applies the forecast head on top.

    Drop-in: instantiate alongside AnomalyDetector in main.py.
    """

    KPI_NAMES = [
        "dl_throughput_mbps",
        "latency_ms",
        "bler_pct",
        "rsrp_dbm",
        "handover_success_rate",
        "slice_utilisation_pct",
    ]

    def __init__(self, anomaly_detector, device: str | None = None):
        self.detector = anomaly_detector
        # Use detector's device for consistency, else centralized selection
        if device is not None:
            self.device = torch.device(device)
        else:
            d = getattr(anomaly_detector, 'device', None)
            if isinstance(d, (torch.device, str)):
                self.device = torch.device(d)
            else:
                self.device = get_device()
        self._last_result: dict | None = None  # lightweight summary only — avoids holding large arrays
        log.info("ForecastHead using device: %s", self.device)

        # Load threshold
        if THRESHOLD_PATH.exists():
            with open(THRESHOLD_PATH) as f:
                th = json.load(f)
            self.threshold = th.get("threshold_3sigma", 0.08)
            self.threshold_warn = th.get("mean", 0.04) + 2 * th.get("std", 0.01)   # 2-sigma early warning
        else:
            self.threshold = 0.08
            self.threshold_warn = 0.06

        # Build forecast net on the same device
        self.net = safe_to_device(ForecastHeadNet(), self.device)

        if FORECAST_MODEL_PATH.exists():
            self.net.load_state_dict(
                torch.load(FORECAST_MODEL_PATH, map_location=self.device, weights_only=True)
            )
            log.info("ForecastHead: loaded weights from %s on %s", FORECAST_MODEL_PATH, self.device)
        else:
            log.warning(
                "ForecastHead: no saved weights found at %s — "
                "run training/train_forecast.py first", FORECAST_MODEL_PATH
            )

        self.net.eval()

    # ── Core Prediction ──────────────────────────────────────────────────────

    @torch.no_grad()
    def predict(self, window: np.ndarray) -> ForecastResult:
        """
        Args:
            window: np.ndarray shape (30, 6) — normalised KPI window
                    (same format as AnomalyDetector.detect() input)

        Returns:
            ForecastResult — full 5-minute trajectory + alert fields
        """
        from datetime import datetime, timezone

        t = torch.FloatTensor(window).unsqueeze(0).to(self.device)  # (1,30,6)

        # Get encoder latent from the existing model (frozen, no grad)
        latent = self.detector.model.encode(t)           # (1, 8)
        last_kpi = t[:, -1, :]                           # (1, 6) last observed

        # Run forecast head with OOM fallback
        try:
            forecast = self.net(latent, last_kpi)            # (1, horizon, 6)
        except torch.cuda.OutOfMemoryError:
            log.warning("GPU OOM in ForecastHead — falling back to CPU")
            clear_gpu_cache()
            latent = latent.cpu()
            last_kpi = last_kpi.cpu()
            net_cpu = self.net.cpu()
            forecast = net_cpu(latent, last_kpi)
            # Move net back to GPU for next call
            self.net = safe_to_device(self.net, self.device)

        trajectory = forecast.squeeze(0).cpu().numpy()   # (horizon, 6)

        # Compute risk curve: MSE of each forecast step vs the reconstruction
        # error pattern we'd expect at the threshold. Proxy: per-step mean
        # absolute deviation from normal range centre (0.5 in normalised space).
        normal_centre = np.array([0.5] * 6)
        per_step_mse = np.mean((trajectory - normal_centre) ** 2, axis=1)

        # Scale to same units as detector threshold (MSE in normalised space)
        risk_curve = per_step_mse

        # Detect alert
        crossings = np.where(risk_curve[:PREEMPTIVE_HORIZON] > self.threshold_warn)[0]
        preemptive_alert = len(crossings) > 0
        seconds_to_anomaly = int(crossings[0]) if preemptive_alert else None

        # At-risk KPIs: which features have highest deviation in first 60s
        early_window = trajectory[:PREEMPTIVE_HORIZON]
        feature_risk = np.mean(np.abs(early_window - 0.5), axis=0)
        top_indices = np.argsort(feature_risk)[::-1][:3]
        at_risk_kpis = [self.KPI_NAMES[i] for i in top_indices
                        if feature_risk[i] > 0.1]

        # Confidence: how stable is the forecast? (low variance = high confidence)
        forecast_variance = np.mean(np.var(trajectory, axis=0))
        confidence = float(max(0.0, 1.0 - forecast_variance * 4))

        # Summary
        if preemptive_alert:
            summary = (
                f"⚠ PRE-ANOMALY ALERT: threshold breach predicted in "
                f"{seconds_to_anomaly}s. "
                f"At-risk KPIs: {', '.join(at_risk_kpis)}. "
                f"Confidence: {confidence:.0%}. Initiating pre-emptive healing."
            )
        else:
            summary = (
                f"✓ NOMINAL TRAJECTORY: no anomaly predicted in next "
                f"{PREEMPTIVE_HORIZON}s. Confidence: {confidence:.0%}."
            )

        res = ForecastResult(
            trajectory=trajectory,
            risk_curve=risk_curve,
            preemptive_alert=preemptive_alert,
            seconds_to_anomaly=seconds_to_anomaly,
            confidence=confidence,
            at_risk_kpis=at_risk_kpis,
            summary=summary,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        # Cache only a compact summary to avoid holding large numpy arrays in memory
        self._last_result = {
            "preemptive_alert": preemptive_alert,
            "seconds_to_anomaly": seconds_to_anomaly,
            "confidence": confidence,
            "at_risk_kpis": at_risk_kpis,
            "summary": summary,
            "timestamp": res.timestamp,
        }
        return res
