# PHASE 4 GATE — DoWhy Integration

**Date completed:** 2026-07-23  
**Status:** ✅ PASSED  

---

## 1. Inference Pipeline

CR²E builds a DoWhy causal model for every treatment-outcome query:
1. **Model Specification:** `dowhy.CausalModel` initialized with current discovered/constrained NetworkX DAG.
2. **Identification:** Backdoor criterion specifies the required adjustment set (confounders adjusted automatically).
3. **Estimation:** EconML `LinearDML` (with Gradient Boosting Regressors for first-stage nuisance models) estimates the Average Treatment Effect (ATE).
4. **Refutation:** 3-test refutation checks:
   - `placebo_treatment_refuter` (expects new effect ~0)
   - `random_common_cause_refuter` (expects original effect stable)
   - `data_subset_refuter` (expects original effect stable)

---

## 2. Worked End-to-End Estimation Example
*Planted synthetic cause verification:*
- **Query:** `slice_utilisation_pct` (treatment) → `latency_ms` (outcome)
- **True planted coefficient:** 2.0 (normalised: ~0.02 raw)
- **Estimated ATE:** `+0.0193`
- **95% Confidence Interval:** `[0.0166, 0.0219]` (strictly positive, captures true effect)
- **Refutation Results:**
  - Placebo treatment: passed (new effect ~0)
  - Random common cause: passed (estimate changes < 30%)
  - Data subset: passed (estimate changes < 50%)
- **Triple Tag:**
  - *Estimator:* `LinearDML (EconML)`
  - *Provenance:* `[SYNTHETIC]`
  - *Identifiability Assumption:* `Conditional ignorability given observed KPIs; backdoor criterion holds; no unmeasured backhaul/cross-cell confounding.`

---

## 3. Unit Test Verification
- `test_estimator.py` verifies:
  - Correct ATE sign extraction on planted relationship.
  - Finite and ordered confidence intervals.
  - Refutation results logged transparently (no silent masking of failures).
  - Proper handling of insufficient-data boundary cases (skips when n < 200).

**Gate Decision:** PASSED. Causal estimation and refutation engine validated and verified.
