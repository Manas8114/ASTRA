"""
cr2e/tests/test_ranker.py
─────────────────────────────────────────────────────────────────────────────
Phase 5 Gate Test — Root-Cause Ranker

KEY GATE REQUIREMENT:
  "Ranking logic unit-tested against at least one synthetic case with a known
  planted cause." — master prompt Phase 5 gate.

Test structure:
  1. Create synthetic EffectEstimates with one KNOWN planted significant cause.
  2. Assert that the ranker places it at rank 1.
  3. Assert CI-first ordering: significant causes rank above non-significant.
  4. Assert refutation-honest: failing refutations included with warning flag.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import pytest

from cr2e.inference.causal_query import AnomalyEvent
from cr2e.inference.estimator import EffectEstimate, RefutationResult
from cr2e.inference.ranker import RootCauseRanker, RankingResult
from cr2e.inference.root_cause_report import RootCauseReport


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_estimate(
    treatment: str,
    outcome: str = "latency_ms",
    ate: float = 0.0,
    ci_lower: float = -0.1,
    ci_upper: float = 0.1,
    refutations_passed: bool = True,
    insufficient_data: bool = False,
    fault_id: str = "fault-001",
    provenance: str = "[SYNTHETIC]",
) -> EffectEstimate:
    """Construct a synthetic EffectEstimate for testing."""
    return EffectEstimate(
        treatment_kpi=treatment,
        outcome_kpi=outcome,
        fault_id=fault_id,
        cell_id="cell_001",
        ate=ate,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        estimator="LinearDML (EconML)",
        data_provenance_tag=provenance,
        identifiability_assumption="Test assumption.",
        refutation_results=[
            RefutationResult(
                test_name="placebo_treatment",
                passed=refutations_passed,
            )
        ],
        all_refutations_passed=refutations_passed,
        n_samples=500,
        insufficient_data=insufficient_data,
    )


def _make_fault_event(fault_id: str = "fault-001") -> AnomalyEvent:
    return AnomalyEvent(
        fault_id=fault_id,
        cell_id="cell_001",
        anomaly_type="CONGESTION",
        timestamp="2026-07-16T00:00:00+00:00",
        data_provenance_tag="[SYNTHETIC]",
    )


# ── Phase 5 Gate: Planted Cause Ranks #1 ─────────────────────────────────────

class TestPlantedCauseRankFirst:
    """
    GATE TEST: planted significant cause must appear at rank 1.
    """

    def test_planted_significant_cause_ranks_first(self):
        """
        Scenario: We have 3 treatment candidates.
        - slice_utilisation_pct has a strong, significant ATE (planted cause).
        - rsrp_dbm has a weak, non-significant ATE.
        - handover_success_rate has moderate ATE but fails refutation.

        Expected: slice_utilisation_pct is ranked #1.
        """
        estimates = [
            _make_estimate(
                "rsrp_dbm",
                ate=0.05,
                ci_lower=-0.02,
                ci_upper=0.12,  # CI contains 0 → not significant
                refutations_passed=True,
            ),
            _make_estimate(
                "slice_utilisation_pct",
                ate=0.80,
                ci_lower=0.60,
                ci_upper=1.00,  # strongly significant — PLANTED CAUSE
                refutations_passed=True,
            ),
            _make_estimate(
                "handover_success_rate",
                ate=-0.30,
                ci_lower=-0.50,
                ci_upper=-0.10,  # significant but smaller |ATE|
                refutations_passed=True,
            ),
        ]

        ranker = RootCauseRanker(top_k=3)
        result = ranker.rank(_make_fault_event(), estimates)

        assert result.report.top_cause == "slice_utilisation_pct", (
            f"Expected planted cause at rank 1, got: {result.report.top_cause}"
        )
        assert result.report.ranked_causes[0].kpi == "slice_utilisation_pct"
        assert result.report.ranked_causes[0].rank == 1

    def test_significant_causes_rank_above_non_significant(self):
        """Significant causes must rank higher than non-significant ones, regardless of ATE magnitude."""
        estimates = [
            _make_estimate(
                "rsrp_dbm",
                ate=5.0,           # huge ATE but CI contains 0
                ci_lower=-1.0,
                ci_upper=11.0,
                refutations_passed=True,
            ),
            _make_estimate(
                "slice_utilisation_pct",
                ate=0.1,           # small ATE but SIGNIFICANT
                ci_lower=0.05,
                ci_upper=0.15,
                refutations_passed=True,
            ),
        ]

        ranker = RootCauseRanker(top_k=2)
        result = ranker.rank(_make_fault_event(), estimates)

        assert result.report.ranked_causes[0].kpi == "slice_utilisation_pct", (
            "Significant cause should rank above non-significant even with smaller ATE"
        )
        assert result.report.ranked_causes[0].is_significant is True

    def test_among_significant_rank_by_absolute_ate(self):
        """Among significant causes, larger |ATE| ranks higher."""
        estimates = [
            _make_estimate("bler_pct", ate=0.2, ci_lower=0.1, ci_upper=0.3),
            _make_estimate("slice_utilisation_pct", ate=0.8, ci_lower=0.5, ci_upper=1.1),
            _make_estimate("rsrp_dbm", ate=-0.5, ci_lower=-0.7, ci_upper=-0.3),
        ]
        ranker = RootCauseRanker(top_k=3)
        result = ranker.rank(_make_fault_event(), estimates)

        ranked_kpis = [rc.kpi for rc in result.report.ranked_causes]
        assert ranked_kpis[0] == "slice_utilisation_pct", f"Got: {ranked_kpis}"
        assert ranked_kpis[1] == "rsrp_dbm", f"Got: {ranked_kpis}"
        assert ranked_kpis[2] == "bler_pct", f"Got: {ranked_kpis}"


# ── Top-K Limiting ────────────────────────────────────────────────────────────

class TestTopKLimiting:
    def test_report_contains_at_most_top_k(self):
        estimates = [
            _make_estimate(kpi, ate=float(i), ci_lower=float(i) - 0.1, ci_upper=float(i) + 0.1)
            for i, kpi in enumerate(
                ["slice_utilisation_pct", "latency_ms", "bler_pct", "rsrp_dbm", "handover_success_rate"],
                start=1,
            )
        ]
        ranker = RootCauseRanker(top_k=3)
        result = ranker.rank(_make_fault_event(), estimates)
        assert len(result.report.ranked_causes) <= 3

    def test_ranks_are_sequential(self):
        estimates = [
            _make_estimate("slice_utilisation_pct", ate=1.0, ci_lower=0.5, ci_upper=1.5),
            _make_estimate("bler_pct", ate=0.5, ci_lower=0.2, ci_upper=0.8),
        ]
        ranker = RootCauseRanker(top_k=2)
        result = ranker.rank(_make_fault_event(), estimates)
        ranks = [rc.rank for rc in result.report.ranked_causes]
        assert ranks == list(range(1, len(ranks) + 1))


# ── Refutation Honesty ────────────────────────────────────────────────────────

class TestRefutationHonesty:
    def test_refutation_failures_included_not_hidden(self):
        """An estimate with a failing refutation must appear in the report (with a warning count)."""
        estimates = [
            _make_estimate(
                "slice_utilisation_pct",
                ate=0.5,
                ci_lower=0.2,
                ci_upper=0.8,
                refutations_passed=False,  # failing refutation
            ),
        ]
        ranker = RootCauseRanker(top_k=3)
        result = ranker.rank(_make_fault_event(), estimates)

        assert result.refutation_warning_count >= 1
        # The estimate is still included (not hidden)
        assert result.report.ranked_causes[0].kpi == "slice_utilisation_pct"


# ── Insufficient Data Exclusion ───────────────────────────────────────────────

class TestInsufficientDataExclusion:
    def test_insufficient_data_estimates_excluded(self):
        estimates = [
            _make_estimate("slice_utilisation_pct", insufficient_data=True),
            _make_estimate("bler_pct", ate=0.5, ci_lower=0.3, ci_upper=0.7),
        ]
        ranker = RootCauseRanker(top_k=2)
        result = ranker.rank(_make_fault_event(), estimates)

        assert result.excluded_count == 1
        ranked_kpis = [rc.kpi for rc in result.report.ranked_causes]
        assert "slice_utilisation_pct" not in ranked_kpis
        assert "bler_pct" in ranked_kpis

    def test_all_insufficient_gives_empty_ranking(self):
        estimates = [
            _make_estimate("slice_utilisation_pct", insufficient_data=True),
            _make_estimate("bler_pct", insufficient_data=True),
        ]
        ranker = RootCauseRanker(top_k=3)
        result = ranker.rank(_make_fault_event(), estimates)

        assert result.excluded_count == 2
        assert result.report.top_cause == "unknown"


# ── Provenance Tag Propagation ────────────────────────────────────────────────

class TestProvenanceTagPropagation:
    def test_provenance_tag_in_report(self):
        estimates = [
            _make_estimate("slice_utilisation_pct", ate=0.5, ci_lower=0.3, ci_upper=0.7,
                           provenance="[REAL:testbed]"),
        ]
        ranker = RootCauseRanker(top_k=1)
        result = ranker.rank(_make_fault_event(), estimates)
        assert result.report.data_provenance_tag == "[REAL:testbed]"

    def test_provenance_tag_in_ranked_causes(self):
        estimates = [
            _make_estimate("slice_utilisation_pct", ate=0.5, ci_lower=0.3, ci_upper=0.7,
                           provenance="[SYNTHETIC]"),
        ]
        ranker = RootCauseRanker(top_k=1)
        result = ranker.rank(_make_fault_event(), estimates)
        for rc in result.report.ranked_causes:
            assert rc.data_provenance_tag == "[SYNTHETIC]"
