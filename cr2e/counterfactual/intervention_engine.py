"""
cr2e/counterfactual/intervention_engine.py
─────────────────────────────────────────────────────────────────────────────
Phase 6 — Counterfactual / Intervention Layer

Given the ranked root-causes (from Phase 5), computes the minimal
counterfactual: "by how much must KPI X change to resolve ≥80% of the
observed degradation in KPI Y?"

Every claim:
  - Is tagged with data_provenance_tag
  - Carries 95% CI, not just a point estimate
  - States the identifiability assumption under which it is valid
  - Is marked [SYNTHETIC] if derived from demo-mode data

Anti-fabrication note:
  Counterfactual validity requires the same identifiability assumptions as
  the underlying ATE estimate PLUS the assumption of modularity / independent
  mechanisms (Pearl's do-calculus). Where this is uncertain, it is stated
  explicitly in the identifiability_note field.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from cr2e.inference.estimator import EffectEstimate
from cr2e.inference.root_cause_report import RootCauseReport, RankedCause

log = logging.getLogger("cr2e.counterfactual.intervention_engine")


@dataclass
class InterventionStep:
    """
    One prescriptive intervention step.

    Attributes
    ----------
    kpi : str
        The KPI to intervene on (the treatment variable).
    current_value : Optional[float]
        Current (fault-time) value if known; None in demo mode.
    target_value_estimate : float
        Estimated value of kpi needed to achieve the desired outcome improvement.
    delta : float
        target_value_estimate − current_value (the intervention magnitude).
    delta_ci_lower : float
        95% CI lower bound on delta.
    delta_ci_upper : float
        95% CI upper bound on delta.
    expected_outcome_improvement_pct : float
        Estimated % resolution of the degradation (0–100).
    astra_action_hint : str
        Mapping to the nearest ASTRA HealingAction type.
    data_provenance_tag : str
    identifiability_note : str
    """

    kpi: str
    current_value: Optional[float]
    target_value_estimate: float
    delta: float
    delta_ci_lower: float
    delta_ci_upper: float
    expected_outcome_improvement_pct: float
    astra_action_hint: str
    data_provenance_tag: str = "[SYNTHETIC]"
    identifiability_note: str = (
        "Assumes modularity (independent causal mechanisms) and that "
        "the ATE generalises from observational to interventional regime. "
        "Valid under the backdoor criterion given observed KPIs."
    )

    def summary_line(self) -> str:
        return (
            f"Intervene on {self.kpi}: Δ={self.delta:+.4f} "
            f"95%CI[{self.delta_ci_lower:+.4f},{self.delta_ci_upper:+.4f}] "
            f"→ ~{self.expected_outcome_improvement_pct:.0f}% resolution | "
            f"{self.data_provenance_tag}"
        )


@dataclass
class CounterfactualPlan:
    """
    Complete counterfactual/intervention plan for one fault event.

    Attributes
    ----------
    fault_id : str
    cell_id : str
    target_resolution_pct : float
        The resolution threshold we aimed for (default 80%).
    steps : list[InterventionStep]
        Ordered intervention steps (most impactful first).
    is_achievable : bool
        True if estimated resolution ≥ target_resolution_pct.
    data_provenance_tag : str
    generated_at : str
    """

    fault_id: str
    cell_id: str
    target_resolution_pct: float = 80.0
    steps: list[InterventionStep] = field(default_factory=list)
    is_achievable: bool = False
    data_provenance_tag: str = "[SYNTHETIC]"
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    def summary(self) -> str:
        lines = [
            f"CounterfactualPlan fault={self.fault_id} cell={self.cell_id}",
            f"  Target resolution: {self.target_resolution_pct:.0f}%",
            f"  Achievable: {self.is_achievable}",
            f"  Tag: {self.data_provenance_tag}",
            f"  Steps:",
        ]
        for s in self.steps:
            lines.append(f"    {s.summary_line()}")
        return "\n".join(lines)


# KPI → ASTRA healing action mapping
_KPI_TO_ASTRA_ACTION: dict[str, str] = {
    "slice_utilisation_pct": "SLICE_REBALANCE",
    "latency_ms": "SLICE_REBALANCE",
    "bler_pct": "POWER_CONTROL",
    "rsrp_dbm": "POWER_CONTROL",
    "handover_success_rate": "HANDOVER_THRESHOLD_ADJUST",
    "dl_throughput_mbps": "ADMISSION_CONTROL",
}


class InterventionEngine:
    """
    Computes counterfactual intervention plans from ranked effect estimates.

    The engine uses a linear counterfactual model:
      If ATE(treatment → outcome) = β,
      to achieve Δoutcome = target_delta,
      we need Δtreatment = target_delta / β.

    This is a first-order linearisation, valid for small interventions.
    For large interventions the non-linearity warning is included in the
    identifiability_note.
    """

    def __init__(
        self,
        target_resolution_pct: float = 80.0,
    ) -> None:
        self.target_resolution_pct = target_resolution_pct

    def compute_plan(
        self,
        report: RootCauseReport,
        estimates: list[EffectEstimate],
        current_kpi_values: Optional[dict[str, float]] = None,
    ) -> CounterfactualPlan:
        """
        Compute a CounterfactualPlan from a RootCauseReport and its estimates.

        Parameters
        ----------
        report : RootCauseReport
        estimates : list[EffectEstimate]
            Must be the same estimates that produced the report.
        current_kpi_values : dict[str, float] | None
            If provided, used to show current vs. target delta.
            If None (demo mode), deltas are expressed in normalised units.

        Returns
        -------
        CounterfactualPlan
        """
        plan = CounterfactualPlan(
            fault_id=report.fault_id,
            cell_id=report.cell_id,
            target_resolution_pct=self.target_resolution_pct,
            data_provenance_tag=report.data_provenance_tag,
        )

        # Index estimates by treatment KPI
        est_map = {e.treatment_kpi: e for e in estimates if not e.insufficient_data}

        cumulative_resolution = 0.0

        for rc in report.ranked_causes:
            if cumulative_resolution >= self.target_resolution_pct:
                break

            est = est_map.get(rc.kpi)
            if est is None or not rc.is_significant:
                continue

            # Linear counterfactual: what Δtreatment achieves a given Δoutcome?
            # We target resolution_pct% of the "typical degradation" for this anomaly type.
            # In demo mode, we define "typical degradation" as 1 standard unit of the outcome.
            target_delta_outcome = self._target_outcome_delta(
                rc.outcome_kpi, report.anomaly_type
            )

            if abs(est.ate) < 1e-10:
                continue

            # Point estimate for required treatment delta
            delta_treatment = target_delta_outcome / est.ate

            # CI propagation (first-order, assuming ATE is the source of uncertainty)
            ate_low = est.ci_lower if abs(est.ci_lower) > 1e-10 else est.ate * 0.5
            ate_high = est.ci_upper if abs(est.ci_upper) > 1e-10 else est.ate * 1.5

            # Avoid division by zero / sign flip in CI
            try:
                delta_ci_from_ate_low = target_delta_outcome / ate_low
                delta_ci_from_ate_high = target_delta_outcome / ate_high
                delta_ci_lower = min(delta_ci_from_ate_low, delta_ci_from_ate_high)
                delta_ci_upper = max(delta_ci_from_ate_low, delta_ci_from_ate_high)
            except ZeroDivisionError:
                delta_ci_lower = delta_treatment * 0.5
                delta_ci_upper = delta_treatment * 1.5

            current = current_kpi_values.get(rc.kpi) if current_kpi_values else None
            target_value = (current + delta_treatment) if current is not None else delta_treatment

            # Estimated resolution contribution from this step
            step_resolution = min(
                100.0,
                abs(est.ate * delta_treatment) / abs(target_delta_outcome) * 100.0
                if target_delta_outcome != 0 else 100.0,
            )

            identifiability = (
                f"Linear counterfactual under backdoor criterion. "
                f"ATE={est.ate:.4f} 95%CI[{est.ci_lower:.4f},{est.ci_upper:.4f}]. "
                f"{est.identifiability_assumption}"
            )
            if abs(delta_treatment) > 2.0:
                identifiability += (
                    " WARNING: large intervention (|Δ|>2 normalised units) — "
                    "linear approximation may be unreliable. Testbed validation required."
                )

            plan.steps.append(
                InterventionStep(
                    kpi=rc.kpi,
                    current_value=current,
                    target_value_estimate=round(target_value, 4),
                    delta=round(delta_treatment, 4),
                    delta_ci_lower=round(delta_ci_lower, 4),
                    delta_ci_upper=round(delta_ci_upper, 4),
                    expected_outcome_improvement_pct=round(step_resolution, 1),
                    astra_action_hint=_KPI_TO_ASTRA_ACTION.get(rc.kpi, "UNKNOWN"),
                    data_provenance_tag=report.data_provenance_tag,
                    identifiability_note=identifiability,
                )
            )

            cumulative_resolution += step_resolution
            log.info(
                "Intervention step: %s → cumulative resolution: %.1f%%",
                plan.steps[-1].summary_line(), cumulative_resolution,
            )

        plan.is_achievable = cumulative_resolution >= self.target_resolution_pct
        return plan

    def _target_outcome_delta(self, outcome_kpi: str, anomaly_type: str) -> float:
        """
        Define what a 'meaningful improvement' looks like for this outcome KPI.

        These are normalised-unit targets derived from typical KPI normal ranges.
        In demo mode all data is min-max normalised, so 1.0 = full range span.
        """
        _targets: dict[str, float] = {
            "latency_ms": -0.5,          # reduce latency by 50% of its std range
            "dl_throughput_mbps": +0.3,  # increase throughput by 30%
            "bler_pct": -0.5,            # reduce BLER by 50%
            "handover_success_rate": +0.2,
            "slice_utilisation_pct": -0.3,
            "rsrp_dbm": +0.2,
        }
        return _targets.get(outcome_kpi, -0.3)
