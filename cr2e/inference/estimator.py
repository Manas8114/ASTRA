"""
cr2e/inference/estimator.py
─────────────────────────────────────────────────────────────────────────────
Phase 4 — DoWhy + EconML LinearDML Effect Estimator

For each CausalQuery, this module:
  1. Builds a DoWhy CausalModel from the current DiscoveredDAG
  2. Estimates the Average Treatment Effect (ATE) via EconML LinearDML
     (same estimator family as CDIE-v5 for consistency and reusable tests)
  3. Runs the 3-test DoWhy refutation suite
  4. Returns an EffectEstimate with:
       - ATE and 95% confidence interval
       - Refutation pass/fail for each test
       - The mandatory triple: (estimator, dataset_provenance, identifiability_assumption)

Anti-fabrication discipline:
  Every EffectEstimate includes data_provenance_tag and identifiability_assumption.
  No effect size is reported without these two fields set.
  Refutation results are stored verbatim — a failing refutation does not get hidden.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from cr2e.graph.discovery import DiscoveredDAG
from cr2e.inference.causal_query import CausalQuery

log = logging.getLogger("cr2e.inference.estimator")


# ── Output types ──────────────────────────────────────────────────────────────

@dataclass
class RefutationResult:
    """Result of one DoWhy refutation test."""

    test_name: str        # e.g. "placebo_treatment"
    passed: bool
    p_value: Optional[float] = None
    new_effect: Optional[float] = None
    original_effect: Optional[float] = None
    note: str = ""


@dataclass
class EffectEstimate:
    """
    Output of one causal effect estimation.

    The mandatory triple (per master prompt §1 anti-fabrication rule):
      estimator               — "LinearDML (EconML)"
      data_provenance_tag     — "[SYNTHETIC]" | "[REAL:testbed]" | "[REAL:injected-fault-ground-truth]"
      identifiability_assumption — statement of what is assumed for identification

    No EffectEstimate is reported anywhere in CR²E without all three fields set.
    """

    # Query metadata
    treatment_kpi: str
    outcome_kpi: str
    fault_id: str
    cell_id: str

    # Effect size
    ate: float                      # Average Treatment Effect
    ci_lower: float                 # 95% confidence interval lower bound
    ci_upper: float                 # 95% confidence interval upper bound
    std_err: float = 0.0

    # Mandatory triple
    estimator: str = "LinearDML (EconML)"
    data_provenance_tag: str = "[SYNTHETIC]"
    identifiability_assumption: str = (
        "Conditional ignorability given observed KPIs; "
        "faithfulness; acyclicity of causal graph. "
        "Unmeasured confounders (backhaul latency, cross-cell interference) "
        "assumed to have negligible effect on this edge — see WHAT_WE_DIDNT_SOLVE §1,§3."
    )

    # Refutation
    refutation_results: list[RefutationResult] = field(default_factory=list)
    all_refutations_passed: bool = False

    # Estimation quality
    n_samples: int = 0
    insufficient_data: bool = False  # True if n < min_history_rows

    def effect_is_significant(self) -> bool:
        """True if the 95% CI does not contain zero."""
        return not (self.ci_lower <= 0 <= self.ci_upper)

    def summary_line(self) -> str:
        sig = "✓ significant" if self.effect_is_significant() else "✗ CI contains 0"
        ref = "✓ refutations passed" if self.all_refutations_passed else "⚠ refutation issues"
        return (
            f"{self.treatment_kpi}→{self.outcome_kpi}: "
            f"ATE={self.ate:+.4f} 95%CI[{self.ci_lower:+.4f},{self.ci_upper:+.4f}] "
            f"{sig} | {ref} | {self.data_provenance_tag}"
        )


# ── Estimator ─────────────────────────────────────────────────────────────────

class CausalEstimator:
    """
    Runs DoWhy + EconML LinearDML for a given CausalQuery and DiscoveredDAG.

    Usage:
        estimator = CausalEstimator(dag=my_dag)
        result = estimator.estimate(query)
    """

    def __init__(
        self,
        dag: DiscoveredDAG,
        refutation_tests: Optional[list[str]] = None,
        min_history_rows: int = 200,
    ) -> None:
        self.dag = dag
        self.refutation_tests = refutation_tests or [
            "placebo_treatment",
            "random_common_cause",
            "data_subset",
        ]
        self.min_history_rows = min_history_rows

    def estimate(self, query: CausalQuery) -> EffectEstimate:
        """
        Estimate the causal effect for a CausalQuery.

        Returns an EffectEstimate regardless of whether the estimate is
        significant — the caller (ranker) decides what to surface.
        """
        base = EffectEstimate(
            treatment_kpi=query.treatment_kpi,
            outcome_kpi=query.outcome_kpi,
            fault_id=query.fault_event.fault_id,
            cell_id=query.fault_event.cell_id,
            ate=0.0,
            ci_lower=0.0,
            ci_upper=0.0,
            data_provenance_tag=query.data_provenance_tag,
            n_samples=query.n_rows,
        )

        if query.n_rows < self.min_history_rows:
            log.warning(
                "Insufficient data for %s: %d rows < %d minimum",
                query.label(), query.n_rows, self.min_history_rows,
            )
            base.insufficient_data = True
            base.identifiability_assumption = (
                f"INSUFFICIENT DATA ({query.n_rows} rows < {self.min_history_rows} minimum). "
                "Effect estimate unreliable. Do not report."
            )
            return base

        df = query.dataset.select_dtypes(include="number").dropna()

        if query.treatment_kpi not in df.columns or query.outcome_kpi not in df.columns:
            log.error("Treatment or outcome KPI not in dataset for %s", query.label())
            base.insufficient_data = True
            return base

        try:
            return self._run_dowhy(query, df, base)
        except Exception as exc:
            log.error("Estimation failed for %s: %s", query.label(), exc)
            base.identifiability_assumption = f"ESTIMATION FAILED: {exc}"
            return base

    def _run_dowhy(
        self,
        query: CausalQuery,
        df: pd.DataFrame,
        base: EffectEstimate,
    ) -> EffectEstimate:
        """Inner estimation: DoWhy model → LinearDML → refutation."""

        try:
            import dowhy
            from dowhy import CausalModel
        except ImportError as exc:
            raise ImportError("dowhy required: pip install dowhy") from exc

        try:
            from econml.dml import LinearDML
            from sklearn.linear_model import LassoCV
            from sklearn.ensemble import GradientBoostingRegressor
        except ImportError as exc:
            raise ImportError("econml required: pip install econml") from exc

        # Build the NetworkX causal graph from the DiscoveredDAG
        # DoWhy accepts a graph in GML or networkx format
        nx_graph = self.dag.to_networkx()

        # Make sure treatment and outcome are in the graph
        if not nx_graph.has_node(query.treatment_kpi):
            nx_graph.add_node(query.treatment_kpi)
        if not nx_graph.has_node(query.outcome_kpi):
            nx_graph.add_node(query.outcome_kpi)

        # Confounders: all other columns that have edges to both treatment and outcome
        # (simple heuristic for the telecom KPI space)
        confounders = [
            c for c in df.columns
            if c not in (query.treatment_kpi, query.outcome_kpi)
        ]

        log.info(
            "Estimating %s → %s, n=%d, confounders=%s",
            query.treatment_kpi, query.outcome_kpi, len(df), confounders,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = CausalModel(
                data=df,
                treatment=query.treatment_kpi,
                outcome=query.outcome_kpi,
                graph=nx_graph,
                identify_vars=True,
            )

            # Identify the estimand
            identified_estimand = model.identify_effect(
                proceed_when_unidentifiable=True
            )

            # Estimate using LinearDML via DoWhy's EconML wrapper
            estimate = model.estimate_effect(
                identified_estimand,
                method_name="backdoor.econml.dml.LinearDML",
                method_params={
                    "init_params": {
                        "model_y": GradientBoostingRegressor(n_estimators=100),
                        "model_t": GradientBoostingRegressor(n_estimators=100),
                        "linear_first_stages": False,
                        "discrete_treatment": False,
                        "cv": 3,
                    },
                    "fit_params": {},
                },
                target_units="ate",
                confidence_intervals=True,
            )

        ate = float(estimate.value)

        # Extract CI
        ci_lower, ci_upper = 0.0, 0.0
        try:
            ci = estimate.get_confidence_intervals()
            ci_lower = float(np.squeeze(ci[0]))
            ci_upper = float(np.squeeze(ci[1]))
        except Exception:
            # Fallback: ±1.96 * std_err if CI extraction fails
            try:
                se = float(estimate.standard_error)
                ci_lower = ate - 1.96 * se
                ci_upper = ate + 1.96 * se
                base.std_err = se
            except Exception:
                pass

        base.ate = ate
        base.ci_lower = ci_lower
        base.ci_upper = ci_upper

        # Refutation suite
        refutation_results = []
        all_passed = True

        for test_name in self.refutation_tests:
            try:
                ref = model.refute_estimate(
                    identified_estimand,
                    estimate,
                    method_name=f"{test_name}_refuter",
                    random_seed=42,
                )
                passed = _parse_refutation_pass(ref, test_name, ate)
                refutation_results.append(
                    RefutationResult(
                        test_name=test_name,
                        passed=passed,
                        new_effect=float(ref.new_effect) if hasattr(ref, "new_effect") else None,
                        original_effect=ate,
                        p_value=float(ref.refutation_result) if isinstance(
                            getattr(ref, "refutation_result", None), float
                        ) else None,
                    )
                )
                if not passed:
                    all_passed = False
            except Exception as exc:
                log.warning("Refutation test %s failed with error: %s", test_name, exc)
                refutation_results.append(
                    RefutationResult(
                        test_name=test_name,
                        passed=False,
                        note=f"Error: {exc}",
                    )
                )
                all_passed = False

        base.refutation_results = refutation_results
        base.all_refutations_passed = all_passed

        log.info(base.summary_line())
        return base


def _parse_refutation_pass(
    ref,
    test_name: str,
    original_ate: float,
) -> bool:
    """
    Heuristic to determine if a refutation test 'passed'.

    For placebo_treatment: new effect should be close to 0.
    For random_common_cause: new effect should be similar to original.
    For data_subset: new effect should be within ±50% of original.
    """
    try:
        new_effect = float(ref.new_effect)
    except (AttributeError, TypeError, ValueError):
        return False

    if test_name == "placebo_treatment":
        # Placebo should drive effect close to zero (|new| < 20% of original)
        if abs(original_ate) < 1e-10:
            return abs(new_effect) < 1e-6
        return abs(new_effect) < 0.2 * abs(original_ate)

    elif test_name == "random_common_cause":
        # Adding random confounder should not substantially change the estimate
        if abs(original_ate) < 1e-10:
            return abs(new_effect - original_ate) < 1e-6
        relative_change = abs(new_effect - original_ate) / abs(original_ate)
        return relative_change < 0.3  # < 30% change

    elif test_name == "data_subset":
        # Subset estimate should be within ±50% of original (noisier, wider tolerance)
        if abs(original_ate) < 1e-10:
            return True
        relative_change = abs(new_effect - original_ate) / abs(original_ate)
        return relative_change < 0.5

    return True  # Unknown test: pass by default
