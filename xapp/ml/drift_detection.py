"""
xapp/ml/drift_detection.py
──────────────────────────────────────────────────────────────────────────────
Drift Detection for ASTRA xApp ML Models.

Monitors model performance and data distribution for:
- Concept drift (changes in KPI distributions)
- Prediction drift (changes in reconstruction error distribution)
- Data quality issues

Implements:
- Kolmogorov-Smirnov (KS) test for distribution comparison
- Population Stability Index (PSI) for feature-level drift
- Alert generation with configurable thresholds
- Automatic retraining triggers

Usage:
    from xapp.ml.drift_detection import DriftDetector

    detector = DriftDetector()
    detector.add_reference_window(reconstruction_errors)
    alerts = detector.check_drift(current_errors)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import numpy as np
from prometheus_client import Counter, Gauge, Histogram
from scipy import stats

from xapp.config import get_settings
from xapp.observability import get_logger

log = get_logger("astra.drift")

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_DRIFT_CHECKS = Counter(
    "astra_drift_checks_total",
    "Total drift detection checks",
    ["result"],  # result: no_drift, warning, critical
)

_DRIFT_KS_STATISTIC = Gauge(
    "astra_drift_ks_statistic",
    "KS test statistic for reconstruction error distribution",
)

_DRIFT_PSI = Gauge(
    "astra_drift_psi",
    "Population Stability Index for features",
    ["feature"],
)

_DRIFT_ALERTS = Counter(
    "astra_drift_alerts_total",
    "Total drift alerts generated",
    ["severity", "type"],  # severity: warning, critical; type: ks, psi
)

_RETRAINING_TRIGGERS = Counter(
    "astra_retraining_triggers_total",
    "Total retraining triggers activated",
    ["trigger_type"],
)


# ── Enums and Data Classes ───────────────────────────────────────────────────

class DriftSeverity(str, Enum):
    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"


class DriftType(str, Enum):
    KS_TEST = "ks_test"
    PSI = "psi"
    FEATURE_DRIFT = "feature_drift"
    PREDICTION_DRIFT = "prediction_drift"


@dataclass
class DriftAlert:
    """Represents a drift detection alert."""
    severity: DriftSeverity
    drift_type: DriftType
    message: str
    feature: Optional[str] = None
    ks_statistic: Optional[float] = None
    ks_pvalue: Optional[float] = None
    psi_value: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftConfig:
    """Configuration for drift detection."""
    # KS test thresholds
    ks_warning_threshold: float = 0.05  # p-value < 0.05 = warning
    ks_critical_threshold: float = 0.001  # p-value < 0.001 = critical

    # PSI thresholds (per feature)
    psi_warning_threshold: float = 0.1  # PSI > 0.1 = warning
    psi_critical_threshold: float = 0.25  # PSI > 0.25 = critical

    # Minimum samples for reliable test
    min_samples: int = 100

    # Window sizes
    reference_window_size: int = 1000
    current_window_size: int = 500

    # Check interval
    check_interval_seconds: float = 300.0  # 5 minutes

    # Retraining trigger
    enable_retraining_trigger: bool = True
    retraining_cooldown_hours: float = 24.0


# ── Drift Detector ───────────────────────────────────────────────────────────

class DriftDetector:
    """
    Detects drift in model inputs and outputs.

    Monitors:
    1. Reconstruction error distribution (KS test)
    2. Per-feature KPI distributions (PSI)
    3. Feature mean/variance shifts
    """

    def __init__(
        self,
        config: Optional[DriftConfig] = None,
        feature_names: Optional[list[str]] = None,
    ) -> None:
        self._config = config or DriftConfig()
        self._feature_names = feature_names or [
            "dl_throughput_mbps",
            "latency_ms",
            "bler_pct",
            "rsrp_dbm",
            "handover_success_rate",
            "slice_utilisation_pct",
        ]

        # Reference distributions (from training/normal operation)
        self._reference_errors: deque[float] = deque(maxlen=self._config.reference_window_size)
        self._current_errors: deque[float] = deque(maxlen=self._config.current_window_size)

        # Per-feature reference statistics
        self._reference_features: dict[str, deque[float]] = {
            name: deque(maxlen=self._config.reference_window_size)
            for name in self._feature_names
        }
        self._current_features: dict[str, deque[float]] = {
            name: deque(maxlen=self._config.current_window_size)
            for name in self._feature_names
        }

        # Reference statistics (computed from reference window)
        self._ref_error_mean: Optional[float] = None
        self._ref_error_std: Optional[float] = None
        self._ref_feature_means: dict[str, float] = {}
        self._ref_feature_stds: dict[str, float] = {}
        self._ref_feature_histograms: dict[str, np.ndarray] = {}

        # State
        self._last_check_time = 0.0
        self._last_retrain_time = 0.0
        self._alerts: deque[DriftAlert] = deque(maxlen=1000)
        self._running = False
        self._check_task: Optional[asyncio.Task] = None

        log.info(
            "DriftDetector initialized: features=%d, ref_window=%d, current_window=%d",
            len(self._feature_names), self._config.reference_window_size, self._config.current_window_size,
        )

    def add_reconstruction_error(self, error: float) -> None:
        """Add a reconstruction error to the current window."""
        self._current_errors.append(error)

    def add_feature_values(self, features: dict[str, float]) -> None:
        """Add feature values to current window."""
        for name, value in features.items():
            if name in self._current_features:
                self._current_features[name].append(value)

    def set_reference_window(self, errors: list[float], features: Optional[dict[str, list[float]]] = None) -> None:
        """
        Set the reference window from a known-good period.

        Args:
            errors: List of reconstruction errors from normal operation
            features: Optional dict of feature_name -> list of values
        """
        self._reference_errors.clear()
        self._reference_errors.extend(errors[-self._config.reference_window_size:])

        if features:
            for name, values in features.items():
                if name in self._reference_features:
                    self._reference_features[name].clear()
                    self._reference_features[name].extend(values[-self._config.reference_window_size:])

        self._compute_reference_stats()
        log.info("Reference window updated: %d errors, %d features",
                 len(self._reference_errors), len(self._reference_features))

    def _compute_reference_stats(self) -> None:
        """Compute statistics from reference window."""
        if len(self._reference_errors) >= self._config.min_samples:
            self._ref_error_mean = float(np.mean(self._reference_errors))
            self._ref_error_std = float(np.std(self._reference_errors))
        else:
            self._ref_error_mean = None
            self._ref_error_std = None

        # Per-feature statistics
        self._ref_feature_means = {}
        self._ref_feature_stds = {}
        self._ref_feature_histograms = {}

        for name in self._feature_names:
            values = list(self._reference_features[name])
            if len(values) >= self._config.min_samples:
                self._ref_feature_means[name] = float(np.mean(values))
                self._ref_feature_stds[name] = float(np.std(values))
                # Compute histogram for PSI
                hist, _ = np.histogram(values, bins=10, density=True)
                self._ref_feature_histograms[name] = hist
            else:
                self._ref_feature_means[name] = None
                self._ref_feature_stds[name] = None
                self._ref_feature_histograms[name] = None

    def check_drift(self) -> list[DriftAlert]:
        """
        Check for drift in current window vs reference.

        Returns:
            List of drift alerts (empty if no drift detected)
        """
        _DRIFT_CHECKS.labels(result="no_drift").inc()
        alerts = []
        now = time.monotonic()
        self._last_check_time = now

        # 1. KS test on reconstruction errors
        if len(self._current_errors) >= self._config.min_samples and self._ref_error_mean is not None:
            ks_alert = self._check_ks_test()
            if ks_alert:
                alerts.append(ks_alert)

        # 2. PSI for each feature
        feature_alerts = self._check_psi()
        alerts.extend(feature_alerts)

        # 3. Feature mean/variance shift
        shift_alerts = self._check_feature_shifts()
        alerts.extend(shift_alerts)

        # Update metrics and record alerts
        for alert in alerts:
            self._alerts.append(alert)
            _DRIFT_ALERTS.labels(severity=alert.severity.value, type=alert.drift_type.value).inc()
            _DRIFT_CHECKS.labels(result=alert.severity.value).inc()

            log.warning(
                "Drift detected: %s %s - %s",
                alert.severity.value, alert.drift_type.value, alert.message,
            )

        return alerts

    def _check_ks_test(self) -> Optional[DriftAlert]:
        """Kolmogorov-Smirnov test on reconstruction error distributions."""
        ref_data = np.array(self._reference_errors)
        cur_data = np.array(self._current_errors)

        if len(ref_data) < self._config.min_samples or len(cur_data) < self._config.min_samples:
            return None

        ks_stat, p_value = stats.ks_2samp(ref_data, cur_data)

        _DRIFT_KS_STATISTIC.set(ks_stat)

        if p_value < self._config.ks_critical_threshold:
            severity = DriftSeverity.CRITICAL
        elif p_value < self._config.ks_warning_threshold:
            severity = DriftSeverity.WARNING
        else:
            return None

        return DriftAlert(
            severity=severity,
            drift_type=DriftType.KS_TEST,
            message=f"KS test: p-value={p_value:.6f}, statistic={ks_stat:.4f}",
            ks_statistic=ks_stat,
            ks_pvalue=p_value,
            details={
                "reference_mean": self._ref_error_mean,
                "reference_std": self._ref_error_std,
                "current_mean": float(np.mean(cur_data)),
                "current_std": float(np.std(cur_data)),
                "reference_size": len(ref_data),
                "current_size": len(cur_data),
            },
        )

    def _check_psi(self) -> list[DriftAlert]:
        """Population Stability Index for each feature."""
        alerts = []

        for name in self._feature_names:
            ref_values = list(self._reference_features[name])
            cur_values = list(self._current_features[name])

            if len(ref_values) < self._config.min_samples or len(cur_values) < self._config.min_samples:
                continue

            # Use reference histogram bins
            ref_hist = self._ref_feature_histograms.get(name)
            if ref_hist is None:
                continue

            # Compute current histogram with same bins
            # First get bin edges from reference
            ref_data = np.array(ref_values)
            cur_data = np.array(cur_values)

            # Use quantile-based bins for robustness
            bins = np.percentile(ref_data, np.linspace(0, 100, 11))
            # Ensure unique bins
            bins = np.unique(bins)
            if len(bins) < 2:
                continue

            ref_hist, _ = np.histogram(ref_data, bins=bins, density=True)
            cur_hist, _ = np.histogram(cur_data, bins=bins, density=True)

            # PSI formula: sum((ref_i - cur_i) * ln(ref_i / cur_i))
            # Add small epsilon to avoid log(0)
            eps = 1e-10
            ref_hist = ref_hist + eps
            cur_hist = cur_hist + eps
            ref_hist = ref_hist / ref_hist.sum()
            cur_hist = cur_hist / cur_hist.sum()

            psi = np.sum((ref_hist - cur_hist) * np.log(ref_hist / cur_hist))

            _DRIFT_PSI.labels(feature=name).set(psi)

            if psi >= self._config.psi_critical_threshold:
                severity = DriftSeverity.CRITICAL
            elif psi >= self._config.psi_warning_threshold:
                severity = DriftSeverity.WARNING
            else:
                continue

            alerts.append(DriftAlert(
                severity=severity,
                drift_type=DriftType.PSI,
                message=f"PSI for {name}: {psi:.4f}",
                feature=name,
                psi_value=psi,
                details={
                    "reference_mean": self._ref_feature_means.get(name),
                    "reference_std": self._ref_feature_stds.get(name),
                    "current_mean": float(np.mean(cur_data)),
                    "current_std": float(np.std(cur_data)),
                },
            ))

        return alerts

    def _check_feature_shifts(self) -> list[DriftAlert]:
        """Check for significant mean/variance shifts per feature."""
        alerts = []

        for name in self._feature_names:
            ref_mean = self._ref_feature_means.get(name)
            ref_std = self._ref_feature_stds.get(name)
            cur_values = list(self._current_features[name])

            if ref_mean is None or ref_std is None or len(cur_values) < self._config.min_samples:
                continue

            cur_mean = np.mean(cur_values)
            cur_std = np.std(cur_values)

            # Z-score for mean shift
            if ref_std > 0:
                z_score = abs(cur_mean - ref_mean) / ref_std
                if z_score > 3.0:  # 3-sigma shift
                    severity = DriftSeverity.CRITICAL if z_score > 5.0 else DriftSeverity.WARNING
                    alerts.append(DriftAlert(
                        severity=severity,
                        drift_type=DriftType.FEATURE_DRIFT,
                        message=f"Feature {name} mean shift: z-score={z_score:.2f}",
                        feature=name,
                        details={
                            "reference_mean": ref_mean,
                            "reference_std": ref_std,
                            "current_mean": float(cur_mean),
                            "current_std": float(cur_std),
                            "z_score": z_score,
                        },
                    ))

        return alerts

    def should_trigger_retraining(self) -> bool:
        """Check if retraining should be triggered based on drift alerts."""
        if not self._config.enable_retraining_trigger:
            return False

        if self._last_retrain_time > 0:
            cooldown_seconds = self._config.retraining_cooldown_hours * 3600
            if time.monotonic() - self._last_retrain_time < cooldown_seconds:
                return False

        # Check for critical alerts in recent history
        recent_critical = [
            a for a in self._alerts
            if a.severity == DriftSeverity.CRITICAL
            and (time.monotonic() - a.timestamp.timestamp()) < 3600  # Last hour
        ]

        if len(recent_critical) >= 2:
            self._last_retrain_time = time.monotonic()
            _RETRAINING_TRIGGERS.labels(trigger_type="critical_drift").inc()
            log.critical("Retraining triggered due to critical drift alerts")
            return True

        return False

    async def start_monitoring(self, anomaly_detector: Any = None) -> None:
        """Start continuous drift monitoring."""
        self._running = True
        self._check_task = asyncio.create_task(self._monitor_loop(anomaly_detector))
        log.info("Drift monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop drift monitoring."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        log.info("Drift monitoring stopped")

    async def _monitor_loop(self, anomaly_detector: Any = None) -> None:
        """Periodic drift check loop."""
        while self._running:
            try:
                await asyncio.sleep(self._config.check_interval_seconds)
                if self._running:
                    self.check_drift()
                    if self.should_trigger_retraining():
                        log.critical("Retraining trigger activated")
                        # Could emit event or call retraining pipeline
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Drift monitor error: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get drift detector statistics."""
        return {
            "running": self._running,
            "reference_error_count": len(self._reference_errors),
            "current_error_count": len(self._current_errors),
            "reference_features": {k: len(v) for k, v in self._reference_features.items()},
            "current_features": {k: len(v) for k, v in self._current_features.items()},
            "ref_error_mean": self._ref_error_mean,
            "ref_error_std": self._ref_error_std,
            "recent_alerts": len(self._alerts),
            "last_check": self._last_check_time,
            "should_retrain": self.should_trigger_retraining(),
        }

    def get_recent_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent drift alerts."""
        return [
            {
                "severity": a.severity.value,
                "type": a.drift_type.value,
                "message": a.message,
                "feature": a.feature,
                "ks_statistic": a.ks_statistic,
                "ks_pvalue": a.ks_pvalue,
                "psi_value": a.psi_value,
                "timestamp": a.timestamp.isoformat(),
                "details": a.details,
            }
            for a in list(self._alerts)[-limit:]
        ]


# ── Global Instance ──────────────────────────────────────────────────────────

_drift_detector: Optional[DriftDetector] = None


def get_drift_detector() -> DriftDetector:
    """Get or create the global drift detector."""
    global _drift_detector
    if _drift_detector is None:
        _drift_detector = DriftDetector()
    return _drift_detector