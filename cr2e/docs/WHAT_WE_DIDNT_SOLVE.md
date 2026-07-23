# What We Didn't Solve

> **Living document.** Started in Phase 1. Appended through Phase 9. This is not a formality — it is what makes CR²E credible under audit.

---

## §1 — Unmeasured Confounder: Backhaul Latency (Phase 1)

**Issue:** ASTRA's `latency_ms` is an end-to-end air+backhaul measure. Backhaul latency as a *separate* KPI is not instrumented. If backhaul congestion causes both high `latency_ms` and reduced `dl_throughput_mbps`, these two KPIs will appear causally linked in the discovered DAG, but the true confounder (backhaul congestion) will be invisible.

**Impact:** Any causal claim of the form `latency_ms → dl_throughput_mbps` may be confounded. Effect estimates on this edge should be treated with lower confidence until backhaul latency is separately instrumented.

**Mitigation:** When reporting, the `identifiability_note` field in `EffectEstimate` must state: *"Assumes no unmeasured backhaul confounding. Unverified until disaggregated backhaul latency KPI is available."*

---

## §2 — PRB Utilisation Not in Schema (Phase 1)

**Issue:** Physical Resource Block (PRB) utilisation is a primary RAN causal variable (load → interference → RSRP drop → BLER rise). It is not in ASTRA's current 6-KPI schema. FlexRIC E2/KPM would expose it via `PM-Container` reports, but FlexRIC integration is lab-dependent.

**Impact:** Discovery algorithm cannot include PRB utilisation edges. `slice_utilisation_pct` is used as a proxy — it is correlated but not identical (PRB is a physical-layer resource; slice utilisation is a logical resource accounting figure).

**Mitigation:** Domain DAG notes `slice_utilisation_pct` as a proxy for PRB utilisation with an explicit note. Phase 2 gate cites this substitution.

---

## §3 — Cross-Cell Interference as Unmeasured Confounder (Phase 1)

**Issue:** In a multi-cell deployment, interference from neighboring cells affects RSRP and BLER at the victim cell. ASTRA has multi-cell coordination but does not log per-neighbor interference levels. This means CR²E's causal model is per-cell; it cannot distinguish *"RSRP dropped because of bad channel conditions at this cell"* from *"RSRP dropped because a neighboring cell increased its transmission power."*

**Impact:** RSRP-related causal edges may be incorrectly attributed to intra-cell causes when the true mechanism is inter-cell interference.

**Mitigation:** Explicitly assume single-cell causal closure. Any report involving `rsrp_dbm` must include identifiability note: *"Assumes cross-cell interference is constant across the observation window. Violations not detectable from current KPI schema."*

---

## §4 — Discovery Algorithm Sensitivity to Sample Size (Phase 1)

**Issue:** PC algorithm and NOTEARS can return different graph structures depending on sample size, especially for edge orientations in near-Markov-equivalent classes. With 1-second KPI polling and a 24-hour history window, we have ~86,400 rows — this is a comfortable regime for PC. However, for short fault events (sub-minute), the per-fault causal estimation window may contain only 30–120 samples, which is insufficient for reliable structure learning.

**Impact:** Per-fault effect estimates use a *fixed graph* (from the full history) rather than re-running discovery per fault. The fixed-graph assumption may be violated if network topology or traffic patterns change.

**Mitigation:** CR²E re-runs discovery on a 24-hour rolling window (not per-fault). Per-fault estimation uses the fixed graph. This design choice is explicit in Phase 3 gate and Phase 9.

---

## §5 — Causal Identifiability on Observational KPI Data (Phase 1)

**Issue:** Proving identifiability requires knowing the true causal graph. On observational network data (no interventions), we can identify Markov equivalence classes but not individual edge orientations without assumptions. Domain constraints (Phase 2) break some equivalences, but not all.

**Impact:** Some reported causal effects are identified only under the faithfulness assumption and the domain-constrained Markov condition. If either is violated, effect estimates may be biased.

**Mitigation:** Every `EffectEstimate` includes `identifiability_assumption` field. Gate documents are explicit about which edges are domain-fixed vs. discovery-inferred.

---

*Further entries will be appended at Phases 3, 6, 8, and 9.*
