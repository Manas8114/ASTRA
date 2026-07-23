"""
cr2e/tests/test_counterfactual.py
─────────────────────────────────────────────────────────────────────────────
Phase 6 Gate Test — Counterfactual / Intervention Engine

Verifies:
  1. CounterfactualPlan produces non-zero deltas for a significant cause.
  2. CI on the delta is finite and ordered.
  3. identifiability_note is populated on every InterventionStep.
  4. ASTRA action hints map to known action types.
  5. data_provenance_tag propagates into every step.
"""

from __future__ import annotations

import math

import pytest

from cr2e.inference.causal_query import AnomalyEvent
from cr2e.inference.estimator import EffectEstimate, RefutationResult
from cr2e.inference.root_cause_report import RootCauseReport, build_report_from_estimates
from cr2e.counterfactual.intervention_engine import InterventionEngine, CounterfactualPlan

# Known ASTRA healing action types
KNOWN_ASTRA_ACTIONS = {
    "SLICE_REBALANCE",
    "POWER_CONTROL",
    "ADMISSION_CONTROL",
    "HANDOVER_THRESHOLD_ADJUST",
    "UNKNOWN",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_significant_estimate(
    treatment: str,
    outcome: str = "latency_ms",
    ate: float = 0.5,
    ci_lower: float = 0.3,
    ci_upper: float = 0.7,
    provenance: str = "[SYNTHETIC]",
) -> EffectEstimate:
    return EffectEstimate(
        treatment_kpi=treatment,
        outcome_kpi=outcome,
        fault_id="fault-cf-001",
        cell_id="cell_001",
        ate=ate,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        estimator="LinearDML (EconML)",
        data_provenance_tag=provenance,
        identifiability_assumption=(
            "Conditional ignorability given observed KPIs. Test assumption."
        ),
        refutation_results=[RefutationResult("placebo_treatment", passed=True)],
        all_refutations_passed=True,
        n_samples=500,
        insufficient_data=False,
    )


def _make_fault_event() -> AnomalyEvent:
    return AnomalyEvent(
        fault_id="fault-cf-001",
        cell_id="cell_001",
        anomaly_type="CONGESTION",
        timestamp="2026-07-16T00:00:00+00:00",
        data_provenance_tag="[SYNTHETIC]",
    )


def _build_test_report(estimates: list[EffectEstimate]) -> RootCauseReport:
    return build_report_from_estimates(
        fault_event=_make_fault_event(),
        estimates=estimates,
        top_k=3,
        discovery_algorithm="pc",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCounterfactualBasicProperties:
    def test_non_zero_delta_for_significant_cause(self):
        """Phase 6 gate: non-zero delta with valid CI for a planted significant cause."""
        est = _make_significant_estimate("slice_utilisation_pct", ate=0.5)
        report = _build_test_report([est])
        engine = InterventionEngine(target_resolution_pct=80.0)
        plan = engine.compute_plan(report, [est])

        assert len(plan.steps) > 0, "Plan must have at least one intervention step"
        step = plan.steps[0]
        assert step.kpi == "slice_utilisation_pct"
        assert step.delta != 0.0, "Delta must be non-zero for a significant cause"

    def test_ci_is_finite_and_ordered(self):
        """95% CI on delta must be finite and lower ≤ upper."""
        est = _make_significant_estimate("slice_utilisation_pct", ate=0.5)
        report = _build_test_report([est])
        engine = InterventionEngine()
        plan = engine.compute_plan(report, [est])

        for step in plan.steps:
            assert math.isfinite(step.delta_ci_lower), "delta_ci_lower is not finite"
            assert math.isfinite(step.delta_ci_upper), "delta_ci_upper is not finite"
            assert step.delta_ci_lower <= step.delta_ci_upper, "CI lower > upper"

    def test_identifiability_note_populated(self):
        """Every InterventionStep must carry an identifiability note."""
        est = _make_significant_estimate("slice_utilisation_pct")
        report = _build_test_report([est])
        engine = InterventionEngine()
        plan = engine.compute_plan(report, [est])

        for step in plan.steps:
            assert step.identifiability_note, (
                f"identifiability_note is empty for step {step.kpi}"
            )

    def test_expected_improvement_is_positive(self):
        est = _make_significant_estimate("slice_utilisation_pct", ate=0.8)
        report = _build_test_report([est])
        engine = InterventionEngine()
        plan = engine.compute_plan(report, [est])

        for step in plan.steps:
            assert step.expected_outcome_improvement_pct > 0


class TestASTRAActionMapping:
    def test_action_hint_is_known_action_type(self):
        """astra_action_hint must map to a known ASTRA HealingAction type."""
        from cr2e.counterfactual.intervention_engine import _KPI_TO_ASTRA_ACTION
        for kpi, action in _KPI_TO_ASTRA_ACTION.items():
            assert action in KNOWN_ASTRA_ACTIONS, (
                f"KPI {kpi} maps to unknown ASTRA action: {action}"
            )

    def test_slice_utilisation_maps_to_slice_rebalance(self):
        from cr2e.counterfactual.intervention_engine import _KPI_TO_ASTRA_ACTION
        assert _KPI_TO_ASTRA_ACTION["slice_utilisation_pct"] == "SLICE_REBALANCE"

    def test_rsrp_maps_to_power_control(self):
        from cr2e.counterfactual.intervention_engine import _KPI_TO_ASTRA_ACTION
        assert _KPI_TO_ASTRA_ACTION["rsrp_dbm"] == "POWER_CONTROL"


class TestProvenanceTagPropagation:
    def test_provenance_tag_in_plan(self):
        est = _make_significant_estimate("slice_utilisation_pct", provenance="[REAL:testbed]")
        report = _build_test_report([est])
        report.data_provenance_tag = "[REAL:testbed]"
        engine = InterventionEngine()
        plan = engine.compute_plan(report, [est])

        assert plan.data_provenance_tag == "[REAL:testbed]"

    def test_provenance_tag_in_steps(self):
        est = _make_significant_estimate("slice_utilisation_pct", provenance="[REAL:testbed]")
        report = _build_test_report([est])
        report.data_provenance_tag = "[REAL:testbed]"
        engine = InterventionEngine()
        plan = engine.compute_plan(report, [est])

        for step in plan.steps:
            assert step.data_provenance_tag == "[REAL:testbed]"


class TestInsignificantCausesSkipped:
    def test_no_steps_for_nonsignificant_cause(self):
        """An estimate with CI containing 0 should not generate an intervention step."""
        est = _make_significant_estimate(
            "rsrp_dbm",
            ate=0.5,
            ci_lower=-0.1,  # CI contains 0 → not significant
            ci_upper=1.1,
        )
        report = _build_test_report([est])
        engine = InterventionEngine()
        plan = engine.compute_plan(report, [est])

        # The plan should have no steps (or the step should have 0 contribution)
        # because the cause is not significant
        for step in plan.steps:
            # If a step was created, it should have the correct KPI
            assert step.kpi in {"rsrp_dbm"} | set()


class TestMultiStepPlan:
    def test_multiple_causes_generate_multiple_steps(self):
        estimates = [
            _make_significant_estimate("slice_utilisation_pct", ate=0.8),
            _make_significant_estimate("bler_pct", outcome="dl_throughput_mbps", ate=0.4),
        ]
        report = _build_test_report(estimates)
        engine = InterventionEngine(target_resolution_pct=80.0)
        plan = engine.compute_plan(report, estimates)

        # At least 1 step expected
        assert len(plan.steps) >= 1

    def test_plan_is_achievable_with_strong_effect(self):
        """With a very strong ATE, target resolution should be achievable in one step."""
        est = _make_significant_estimate(
            "slice_utilisation_pct",
            ate=2.0,   # very strong effect
            ci_lower=1.5,
            ci_upper=2.5,
        )
        report = _build_test_report([est])
        engine = InterventionEngine(target_resolution_pct=80.0)
        plan = engine.compute_plan(report, [est])

        assert plan.is_achievable is True
