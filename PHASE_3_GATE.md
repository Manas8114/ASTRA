# PHASE 3 GATE — Causal Discovery

**Date completed:** 2026-07-16  
**Status:** ✅ PASSED  

---

## 1. Discovery Architecture
- **Algorithm selection:** Configurable (`pc` or `notears`) in `cr2e/config.py`.
- **Constraint injection:** Background knowledge (required/forbidden edges) translated from Domain DAG to `causal-learn` format (`bk.add_required_by_node`, `bk.add_forbidden_by_node`).
- **DAG diffing & logging:** Novel edges accepted conditionally. Forbidden edges flagged with explicit hypotheses and discarded (no silent merging).

---

## 2. Structural Diff Summary (Verification Run)
Running PC algorithm on synthetic KPI dataset (500 samples, α=0.05, Fisher-Z test):
- **Agreed edges:** `rsrp_dbm → bler_pct`, `bler_pct → dl_throughput_mbps`, `slice_utilisation_pct → latency_ms`.
- **Domain-only overrides:** `rsrp_dbm → handover_success_rate` (weak signal in sample context, force-injected from domain constraints).
- **Discovery-only (novel):** None in default synthetic profile.
- **Reversed/Violations:** Zero violations detected.

*If violations occur during rolling runs, the engine flags the violation to logs/MLflow and drops the edge, ensuring domain safety takes precedence.*

---

## 3. Unit Test Verification
- `test_domain_dag.py` verifies the PC/NOTEARS background knowledge configuration.
- Rolling snapshots are persisted to `cr2e/data/dag_snapshot.json` and a history file for audit trails.

**Gate Decision:** PASSED. Causal discovery pipeline integrated and constraint enforcement validated.
