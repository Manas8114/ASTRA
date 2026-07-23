"""
cr2e/inference/root_cause_report.py
─────────────────────────────────────────────────────────────────────────────
Primary output dataclass of CR²E per fault event.

A RootCauseReport is what gets:
  - Stored in cr2e/results/
  - Broadcast as a ROOT_CAUSE_REPORT WebSocket event to the ASTRA dashboard
  - Returned by GET /cr2e/root-cause/{fault_id}
  - Logged to MLflow

Every numeric field in a RootCauseReport carries data_provenance_tag.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from cr2e.inference.estimator import EffectEstimate


@dataclass
class RankedCause:
    """One ranked root-cause entry."""

    rank: int
    kpi: str                     # treatment KPI identified as a cause
    outcome_kpi: str             # the failing KPI it drives
    ate: float                   # Average Treatment Effect
    ci_lower: float
    ci_upper: float
    is_significant: bool         # 95% CI does not contain zero
    all_refutations_passed: bool
    data_provenance_tag: str
    identifiability_assumption: str
    effect_label: str = ""       # human-readable magnitude label

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RootCauseReport:
    """
    Complete causal root-cause analysis for one ASTRA fault event.

    Attributes
    ----------
    fault_id : str
        Matches the originating AnomalyEvent.fault_id.
    cell_id : str
    anomaly_type : str
        ASTRA AnomalyType string (e.g. "CONGESTION").
    timestamp : str
        ISO 8601 time when this report was generated.
    top_cause : str
        KPI ranked #1 (largest absolute significant ATE).
    ranked_causes : list[RankedCause]
        All candidates, sorted by |ATE|, significant ones first.
    data_provenance_tag : str
        Overall tag — inherits from the fault event.
    discovery_algorithm : str
        "pc" or "notears".
    n_kpi_samples : int
        Number of rows in the estimation window.
    nl_explanation : str
        Natural-language explanation from local LLM (or template fallback).
    """

    fault_id: str
    cell_id: str
    anomaly_type: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    top_cause: str = ""
    ranked_causes: list[RankedCause] = field(default_factory=list)
    data_provenance_tag: str = "[SYNTHETIC]"
    discovery_algorithm: str = "pc"
    n_kpi_samples: int = 0
    nl_explanation: str = ""
    # Counterfactual plan (Phase 6) — set by intervention_engine
    counterfactual_plan: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def summary(self) -> str:
        lines = [
            f"RootCauseReport fault={self.fault_id} cell={self.cell_id}",
            f"  Anomaly type : {self.anomaly_type}",
            f"  Top cause    : {self.top_cause}",
            f"  Data tag     : {self.data_provenance_tag}",
            f"  Ranked causes:",
        ]
        for rc in self.ranked_causes:
            sig = "✓" if rc.is_significant else "✗"
            lines.append(
                f"    #{rc.rank} {rc.kpi}→{rc.outcome_kpi}: "
                f"ATE={rc.ate:+.4f} 95%CI[{rc.ci_lower:+.4f},{rc.ci_upper:+.4f}] "
                f"{sig}"
            )
        if self.nl_explanation:
            lines.append(f"  Explanation  : {self.nl_explanation[:120]}...")
        return "\n".join(lines)


def build_report_from_estimates(
    fault_event,  # AnomalyEvent
    estimates: list[EffectEstimate],
    top_k: int = 3,
    discovery_algorithm: str = "pc",
    nl_explanation: str = "",
) -> RootCauseReport:
    """
    Aggregate EffectEstimates into a RootCauseReport.

    Sorting policy:
      1. Significant estimates (CI doesn't contain 0) sort first.
      2. Within each group, sort by |ATE| descending.
    """
    # Filter out insufficient-data estimates
    valid = [e for e in estimates if not e.insufficient_data]

    # Sort: significant first, then by |ATE|
    def sort_key(e: EffectEstimate):
        sig = 0 if e.effect_is_significant() else 1
        return (sig, -abs(e.ate))

    valid.sort(key=sort_key)
    top = valid[:top_k]

    ranked_causes = []
    for i, e in enumerate(top):
        ranked_causes.append(
            RankedCause(
                rank=i + 1,
                kpi=e.treatment_kpi,
                outcome_kpi=e.outcome_kpi,
                ate=round(e.ate, 6),
                ci_lower=round(e.ci_lower, 6),
                ci_upper=round(e.ci_upper, 6),
                is_significant=e.effect_is_significant(),
                all_refutations_passed=e.all_refutations_passed,
                data_provenance_tag=e.data_provenance_tag,
                identifiability_assumption=e.identifiability_assumption,
                effect_label=_magnitude_label(e.ate),
            )
        )

    top_cause = ranked_causes[0].kpi if ranked_causes else "unknown"
    provenance = estimates[0].data_provenance_tag if estimates else "[SYNTHETIC]"
    n_samples = estimates[0].n_samples if estimates else 0

    return RootCauseReport(
        fault_id=fault_event.fault_id,
        cell_id=fault_event.cell_id,
        anomaly_type=fault_event.anomaly_type,
        top_cause=top_cause,
        ranked_causes=ranked_causes,
        data_provenance_tag=provenance,
        discovery_algorithm=discovery_algorithm,
        n_kpi_samples=n_samples,
        nl_explanation=nl_explanation,
    )


def _magnitude_label(ate: float) -> str:
    """Qualitative effect label for display."""
    a = abs(ate)
    if a < 0.01:
        return "negligible"
    if a < 0.1:
        return "weak"
    if a < 0.5:
        return "moderate"
    return "strong"
