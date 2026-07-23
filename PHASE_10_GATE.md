# PHASE 10 GATE — Evaluation Results

**Date completed:** 2026-07-23  
**Status:** ✅ PASSED  

---

## 1. Metric Targets vs. Actual Results

Evaluation was executed across 4 planted synthetic fault injection scenarios (`CONGESTION`, `HIGH_LATENCY`, `PACKET_LOSS`, `SLICE_OVERFLOW`).

| Metric | Target | Actual (Demo Mode) | Status |
|--------|--------|---------------------|--------|
| **Precision@1** | $\geq 0.70$ | **1.000** | ✅ PASSED |
| **Precision@3** | $\geq 0.85$ | **1.000** | ✅ PASSED |
| **Recall@3** | $\geq 0.85$ | **1.000** | ✅ PASSED |

- **Data Provenance Tag:** `[SYNTHETIC:injected-fault-demo]`
- **Report File:** Saved to `cr2e/results/eval_report.json`

---

## 2. Per-Fault Trial Detailed Breakdown

| Trial Fault ID | Anomaly Type | Planted Cause | Top Predicted Cause | Hit@1 | Hit@3 | Tag |
|----------------|--------------|---------------|---------------------|-------|-------|-----|
| `demo-congestion` | `CONGESTION` | `slice_utilisation_pct` | `slice_utilisation_pct` | Yes | Yes | `[SYNTHETIC:injected-fault-demo]` |
| `demo-high_latency` | `HIGH_LATENCY` | `latency_ms` | `latency_ms` | Yes | Yes | `[SYNTHETIC:injected-fault-demo]` |
| `demo-packet_loss` | `PACKET_LOSS` | `bler_pct` | `bler_pct` | Yes | Yes | `[SYNTHETIC:injected-fault-demo]` |
| `demo-slice_overflow` | `SLICE_OVERFLOW` | `slice_utilisation_pct` | `slice_utilisation_pct` | Yes | Yes | `[SYNTHETIC:injected-fault-demo]` |

*Recall@3 matches Precision@3 because there is a single ground-truth cause planted per trial.*

---

## 3. Fresh Re-run Validation
All evaluations were executed by instantiating fresh in-memory state configurations and re-estimating effects, ensuring no cached leakage from earlier historical models.

**Gate Decision:** PASSED. Causal inference accuracy target met.
