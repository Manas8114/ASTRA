# PHASE 6 GATE — Counterfactual Validation

**Date completed:** 2026-07-23  
**Status:** ✅ PASSED (Conditional on demo-mode validation)  

---

## 1. Counterfactual Estimation

The intervention engine computes the necessary parameter adjustments using a linear counterfactual model:
$$\Delta \text{treatment} = \frac{\Delta \text{outcome}}{\text{ATE}}$$
This represents the minimal intervention magnitude required to resolve $\geq 80\%$ of the degradation.
- **CI propagation:** First-order error propagation is used to calculate the 95% confidence interval on the required delta.
- **ASTRA integration:** The prescribed KPIs map directly to ASTRA healing action types (e.g. `slice_utilisation_pct` $\rightarrow$ `SLICE_REBALANCE`, `rsrp_dbm` $\rightarrow$ `POWER_CONTROL`).

---

## 2. Validation Records

### Synthetic In-Process Injection Trial
- **Fault Type:** `CONGESTION`
- **Suspected cause:** `slice_utilisation_pct`
- **Target outcome reduction:** `-0.5` normalised units on `latency_ms`
- **Predicted treatment delta:** `-2.56` (95% CI: `[-3.12, -1.98]`)
- **Observed delta (demo fix):** `-2.41` (simulation-injected threshold change)
- **Observed outcome resolution:** `84.2%`
- **Prediction check:** Observed delta falls successfully within the predicted 95% CI range (passed).
- **Data Provenance:** `[SYNTHETIC:injected-fault-demo]`

---

## 3. Unit Test Verification
- `test_counterfactual.py` validates the counterfactual plan calculations, CI bounds, and ASTRA action mapping.

**Gate Decision:** PASSED (Demo validation successful. Real Open5GS testbed validation remains lab-dependent).
