# PHASE 2 GATE — Causal Graph Scaffolding

**Date completed:** 2026-07-16  
**Status:** ✅ PASSED  

---

## 1. Domain Constraints Inventory

The following physical and protocol constraints are defined in `cr2e/graph/domain_dag.py` to prevent the causal-discovery algorithms from learning spurious or inverted directions:

### Required Edges (Fixed Direction)
- `rsrp_dbm → bler_pct`: Signal quality directly causes block error rate outcomes. (Ref: 3GPP TS 38.300 §16.10.3)
- `bler_pct → dl_throughput_mbps`: Higher BLER drives link adaptation to select lower MCS, reducing throughput. (Ref: 3GPP TS 38.214 §5.2)
- `slice_utilisation_pct → latency_ms`: Elevated resource utilisation increases queuing delay. (Ref: O-RAN WG2 §7.2, Papadimitriou 2021)
- `slice_utilisation_pct → dl_throughput_mbps`: Capacity-limited throughput is caused by resource block saturation. (Ref: O-RAN WG2 §7.2, 3GPP TS 38.214 §5.2)
- `rsrp_dbm → handover_success_rate`: RSRP thresholds trigger handover attempts; weak RSRP increases failure probability. (Ref: 3GPP TS 38.300 §16.10.3)
- `latency_ms → dl_throughput_mbps`: Transport layer (TCP) throughput is inversely proportional to RTT. (Ref: Papadimitriou 2021 §III-B)

### Forbidden Edges (Disallowed Direction)
- `dl_throughput_mbps → rsrp_dbm`: Achieved throughput cannot cause physical signal reception power.
- `dl_throughput_mbps → bler_pct`: Throughput is an outcome, not a cause of channel block errors.
- `handover_success_rate → rsrp_dbm`: Handover outcomes do not modify path loss or transmission power.
- `latency_ms → slice_utilisation_pct`: Packet latency does not modify resource block allocation billing/accounting directly.

---

## 2. Verification of Scaffolding Unit Tests
- `cr2e/tests/test_domain_dag.py` verifies that:
  - All nodes belong to the verified KPI names.
  - Overlaps between required and forbidden sets are impossible.
  - Critical inverses are correctly registered as forbidden.
  - Verification logic accurately flags forbidden edges in mock discovery runs.

**Gate Decision:** PASSED. Causal graph constraints successfully configured and verified.
