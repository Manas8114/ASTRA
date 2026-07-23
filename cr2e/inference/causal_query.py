"""
cr2e/inference/causal_query.py
─────────────────────────────────────────────────────────────────────────────
Phase 4 — Causal Query Schema

A CausalQuery formalises what to estimate:
  treatment = upstream KPI suspected as cause
  outcome   = downstream KPI that failed (as detected by ASTRA)
  dataset   = the KPI history slice around the fault event

Each query carries provenance from ASTRA's anomaly event, ensuring the
data_provenance_tag flows through to every downstream result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


@dataclass
class AnomalyEvent:
    """
    Lightweight representation of an ASTRA anomaly event.
    CR²E reads these from xapp.state.LiveState.anomalies.
    """

    fault_id: str                    # unique identifier
    cell_id: str
    anomaly_type: str                # AnomalyType.value string
    timestamp: str                   # ISO 8601
    attention_weights: dict[str, float] = field(default_factory=dict)
    # data_provenance_tag derived from KPI_SOURCE at collection time
    data_provenance_tag: str = "[SYNTHETIC]"


@dataclass
class CausalQuery:
    """
    One causal query to be estimated by the DoWhy + LinearDML pipeline.

    Attributes
    ----------
    treatment_kpi : str
        The upstream KPI suspected as the cause (e.g. "slice_utilisation_pct").
    outcome_kpi : str
        The failing KPI that ASTRA flagged (e.g. "latency_ms").
    fault_event : AnomalyEvent
        The triggering ASTRA anomaly event.
    dataset : pd.DataFrame
        The KPI history window around the fault (columns = KPI_NAMES, rows = samples).
    window_start : str
        ISO 8601 timestamp of the first row in `dataset`.
    window_end : str
        ISO 8601 timestamp of the last row in `dataset`.
    n_rows : int
        Number of rows in `dataset` (set automatically from dataset.shape[0]).
    data_provenance_tag : str
        Inherited from AnomalyEvent; "[SYNTHETIC]" | "[REAL:*]".
    """

    treatment_kpi: str
    outcome_kpi: str
    fault_event: AnomalyEvent
    dataset: pd.DataFrame
    window_start: str = ""
    window_end: str = ""
    n_rows: int = 0
    data_provenance_tag: str = "[SYNTHETIC]"

    def __post_init__(self) -> None:
        if self.n_rows == 0 and self.dataset is not None:
            self.n_rows = len(self.dataset)
        if not self.data_provenance_tag:
            self.data_provenance_tag = self.fault_event.data_provenance_tag

    def label(self) -> str:
        """Human-readable label for logging and reports."""
        return (
            f"CausalQuery(treatment={self.treatment_kpi}, "
            f"outcome={self.outcome_kpi}, "
            f"fault={self.fault_event.fault_id}, "
            f"n={self.n_rows}, "
            f"tag={self.data_provenance_tag})"
        )


def build_queries_for_event(
    fault_event: AnomalyEvent,
    kpi_history: pd.DataFrame,
    treatment_candidates: Optional[list[str]] = None,
    outcome_kpi: Optional[str] = None,
    window_seconds: int = 300,
    data_provenance_tag: str = "[SYNTHETIC]",
) -> list[CausalQuery]:
    """
    Build one CausalQuery per treatment candidate for a given fault event.

    Parameters
    ----------
    fault_event : AnomalyEvent
    kpi_history : pd.DataFrame
        Full rolling KPI history. Must have a 'timestamp' column or DatetimeIndex.
    treatment_candidates : list[str] | None
        KPIs to test as treatments. If None, use all KPIs except the outcome.
    outcome_kpi : str | None
        The KPI to explain. If None, infer from anomaly_type mapping.
    window_seconds : int
        How many seconds before and after the fault to include.
    data_provenance_tag : str

    Returns
    -------
    list[CausalQuery]
    """
    # Infer outcome from anomaly type if not given
    if outcome_kpi is None:
        outcome_kpi = _infer_outcome(fault_event.anomaly_type)

    all_kpis = [c for c in kpi_history.columns if c != "timestamp"]
    if treatment_candidates is None:
        treatment_candidates = [k for k in all_kpis if k != outcome_kpi]

    # Slice the history window around the fault
    try:
        fault_ts = pd.Timestamp(fault_event.timestamp)
        delta = pd.Timedelta(seconds=window_seconds)

        if "timestamp" in kpi_history.columns:
            kpi_history = kpi_history.copy()
            kpi_history["timestamp"] = pd.to_datetime(kpi_history["timestamp"])
            mask = (
                (kpi_history["timestamp"] >= fault_ts - delta) &
                (kpi_history["timestamp"] <= fault_ts + delta)
            )
            window_df = kpi_history.loc[mask].drop(columns=["timestamp"], errors="ignore")
        else:
            # Assume DatetimeIndex
            window_df = kpi_history.loc[
                (kpi_history.index >= fault_ts - delta) &
                (kpi_history.index <= fault_ts + delta)
            ]
        window_start = str(window_df.index.min() if hasattr(window_df.index, "min") else "")
        window_end = str(window_df.index.max() if hasattr(window_df.index, "max") else "")
    except Exception:
        # Fallback: use the entire history (for demo mode with no timestamps)
        window_df = kpi_history.select_dtypes(include="number")
        window_start = ""
        window_end = ""

    queries = []
    for treatment in treatment_candidates:
        if treatment not in window_df.columns or outcome_kpi not in window_df.columns:
            continue
        queries.append(
            CausalQuery(
                treatment_kpi=treatment,
                outcome_kpi=outcome_kpi,
                fault_event=fault_event,
                dataset=window_df.copy(),
                window_start=window_start,
                window_end=window_end,
                data_provenance_tag=data_provenance_tag,
            )
        )
    return queries


_OUTCOME_MAP: dict[str, str] = {
    "CONGESTION": "latency_ms",
    "HIGH_LATENCY": "latency_ms",
    "PACKET_LOSS": "dl_throughput_mbps",
    "SLICE_OVERFLOW": "dl_throughput_mbps",
    "NOVEL": "dl_throughput_mbps",  # conservative default
    "NORMAL": "dl_throughput_mbps",
}


def _infer_outcome(anomaly_type: str) -> str:
    return _OUTCOME_MAP.get(anomaly_type.upper(), "dl_throughput_mbps")
