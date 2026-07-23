# PHASE 9 GATE — What We Didn't Solve

**Date completed:** 2026-07-23  
**Status:** ✅ PASSED  

---

## 1. Living Document Validation

The living document detailing CR²E limitations has been populated and saved to `cr2e/docs/WHAT_WE_DIDNT_SOLVE.md`. It outlines the following major categories of causal limitations under observational RAN constraints:

- **Unmeasured Confounder (Backhaul Latency):** E2E latency measures include both air-interface and backhaul delays. Congestion on the backhaul link will appear as a spurious causal relationship between `latency_ms` and `dl_throughput_mbps`.
- **PRB Utilisation Proxy:** Physical Resource Block utilisation is missing from the default 6-KPI schema. CR²E uses `slice_utilisation_pct` as a proxy.
- **Cross-Cell Interference Confounding:** Nearby cell power increases cause RSRP drops at the victim cell, but single-cell models cannot distinguish intra-cell issues from neighboring interference.
- **Sample Size Sensitivity in Rolling Windows:** Short event windows are too small for rolling PC graph discovery, requiring a fixed domain-constrained structure learned from a 24-hour window.
- **Observational Identifiability Constraints:** Faithful graph discovery on observational data cannot guarantee orientation of all edges.

---

## 2. Mitigation Check
Every report and counterfactual step includes the `identifiability_note` highlighting these assumptions to downstream users and self-healing executors.

**Gate Decision:** PASSED. Limitations catalogued and transparency layer verified.
