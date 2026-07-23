"""
cr2e/inference/ranker.py
─────────────────────────────────────────────────────────────────────────────
Phase 5 — Root-Cause Ranking

Aggregates per-KPI EffectEstimates for a single fault event into a ranked
list. Includes confidence intervals, not just point estimates.

Ranking policy (documented here, not just in code):
  1. Estimates where the 95% CI does not contain zero rank first.
  2. Within each group, rank by absolute ATE descending.
  3. Estimates flagged as insufficient_data are excluded from the ranking
     but included in the report metadata so the gate log shows full picture.

Anti-fabrication:
  The ranker does NOT filter out estimates with failing refutations — it
  marks them with a warning flag and lets the caller decide. Hiding
  refutation failures would violate the anti-fabrication discipline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from cr2e.inference.estimator import EffectEstimate
from cr2e.inference.causal_query import AnomalyEvent
from cr2e.inference.root_cause_report import (
    RootCauseReport,
    build_report_from_estimates,
)

log = logging.getLogger("cr2e.inference.ranker")


@dataclass
class RankingResult:
    """
    Output of the ranker for one fault event.

    Attributes
    ----------
    report : RootCauseReport
        The ranked root-cause report.
    excluded_count : int
        Number of estimates excluded due to insufficient data.
    refutation_warning_count : int
        Number of included estimates with at least one failed refutation.
    """

    report: RootCauseReport
    all_estimates: list[EffectEstimate] = field(default_factory=list)
    excluded_count: int = 0
    refutation_warning_count: int = 0

    def summary(self) -> str:
        lines = [
            self.report.summary(),
            f"  Excluded (insufficient data): {self.excluded_count}",
            f"  Refutation warnings: {self.refutation_warning_count}",
        ]
        return "\n".join(lines)


class RootCauseRanker:
    """
    Ranks EffectEstimates for a fault event and produces a RootCauseReport.

    Usage:
        ranker = RootCauseRanker(top_k=3)
        result = ranker.rank(fault_event, estimates, discovery_algorithm="pc")
    """

    def __init__(self, top_k: int = 3) -> None:
        self.top_k = top_k

    def rank(
        self,
        fault_event: AnomalyEvent,
        estimates: list[EffectEstimate],
        discovery_algorithm: str = "pc",
        nl_explanation: str = "",
    ) -> RankingResult:
        """
        Rank estimates and build a RootCauseReport.

        Parameters
        ----------
        fault_event : AnomalyEvent
        estimates : list[EffectEstimate]
            All estimates computed by CausalEstimator for this fault event.
        discovery_algorithm : str
        nl_explanation : str
            Pre-generated NL explanation (from nl_explainer.py).

        Returns
        -------
        RankingResult
        """
        excluded = [e for e in estimates if e.insufficient_data]
        valid = [e for e in estimates if not e.insufficient_data]
        refutation_warnings = [e for e in valid if not e.all_refutations_passed]

        if not valid:
            log.warning(
                "All estimates for fault %s were excluded (insufficient data or errors).",
                fault_event.fault_id,
            )

        for e in refutation_warnings:
            log.warning(
                "Estimate %s→%s has refutation failures — included with warning flag.",
                e.treatment_kpi, e.outcome_kpi,
            )

        report = build_report_from_estimates(
            fault_event=fault_event,
            estimates=estimates,
            top_k=self.top_k,
            discovery_algorithm=discovery_algorithm,
            nl_explanation=nl_explanation,
        )

        return RankingResult(
            report=report,
            all_estimates=estimates,
            excluded_count=len(excluded),
            refutation_warning_count=len(refutation_warnings),
        )
