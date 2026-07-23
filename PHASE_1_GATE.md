# PHASE 1 GATE — Data Audit

**Date completed:** 2026-07-16  
**Status:** ✅ PASSED  
**Anti-fabrication tag:** All numbers below reflect code inspection of `xapp/ingestion/kpi_schema.py`, `xapp/ingestion/kpi_adapters.py`, and the existing `injection/` directory. No testbed is currently running.

---

## 1. KPI Inventory

Every KPI time-series ASTRA currently logs, with provenance and fault-injection availability.

| # | KPI Name | ASTRA Field | Normal Range | Data Source Tag | Notes |
|---|----------|-------------|--------------|-----------------|-------|
| 1 | Downlink Throughput | `dl_throughput_mbps` | 50–500 Mbps | **[SYNTHETIC]** (dev mode) / **[REAL:testbed]** (open5gs_file / prometheus) | Primary performance indicator |
| 2 | Air-interface Latency | `latency_ms` | 5–20 ms | **[SYNTHETIC]** / **[REAL:testbed]** | Includes backhaul component in dev model |
| 3 | Block Error Rate | `bler_pct` | 0.1–5 % | **[SYNTHETIC]** / **[REAL:testbed]** | HARQ retransmission proxy |
| 4 | Reference Signal Received Power | `rsrp_dbm` | −80 to −60 dBm | **[SYNTHETIC]** / **[REAL:testbed]** | UE signal quality; directionally drives BLER |
| 5 | Handover Success Rate | `handover_success_rate` | 95–99 % | **[SYNTHETIC]** / **[REAL:testbed]** | Mobility management health |
| 6 | Slice Utilisation | `slice_utilisation_pct` | 20–80 % | **[SYNTHETIC]** / **[REAL:testbed]** | Resource allocation efficiency |

**KPIs mentioned in master prompt but NOT currently in ASTRA schema:**

| KPI | Status | Mitigation |
|-----|--------|------------|
| PRB (Physical Resource Block) Utilisation | **ABSENT** — not in `KPI_NAMES` | Correlated with `slice_utilisation_pct` in dev adapter. Phase 2 domain DAG treats `prb_utilisation` as latent; CR²E uses `slice_utilisation_pct` as proxy. Gap logged in `WHAT_WE_DIDNT_SOLVE.md` §3. |
| Backhaul Latency (separate from air latency) | **ABSENT** — not disaggregated | ASTRA's `latency_ms` is end-to-end. Separate backhaul term is unmeasured confounder. Logged in `WHAT_WE_DIDNT_SOLVE.md` §1. |

---

## 2. Data Source Tag Logic (how tags propagate)

| `KPI_SOURCE` env var | Provenance Tag | Assigned at |
|----------------------|----------------|-------------|
| `dev` (default) | `[SYNTHETIC]` | `kpi_subscriber.py` → synthetic Gaussian generator |
| `open5gs_file` | `[REAL:injected-fault-ground-truth]` when `injection/` active; `[REAL:testbed]` otherwise | Determined by whether Open5GS fault-injection script is running |
| `prometheus` | `[REAL:testbed]` | Prometheus scrape of FlexRIC KPM counters |

CR²E's `RootCauseReport` inherits the provenance tag from the `KPIBuffer` that fed the causal model. This tag is stored in `data_provenance_tag` and appears in every API response, log line, and gate document.

---

## 3. Fault-Injection Capability (Phase 10 ground truth)

ASTRA already has `injection/` directory and `POST /inject/{anomaly_type}` endpoint.

| Injection Type | ASTRA `AnomalyType` | Expected Root-Cause KPI | Ground-Truth Available? |
|----------------|---------------------|--------------------------|------------------------|
| Cell Congestion | `CONGESTION` | `slice_utilisation_pct` → `latency_ms` | ✅ via `POST /inject/CONGESTION` |
| High Latency | `HIGH_LATENCY` | `latency_ms` | ✅ via `POST /inject/HIGH_LATENCY` |
| Packet Loss | `PACKET_LOSS` | `bler_pct` → `dl_throughput_mbps` | ✅ via `POST /inject/PACKET_LOSS` |
| Slice Overflow | `SLICE_OVERFLOW` | `slice_utilisation_pct` | ✅ via `POST /inject/SLICE_OVERFLOW` |
| Novel / Unknown | `NOVEL` | None planted | ⚠️ No ground truth — must be excluded from Phase 10 precision/recall |

**Open5GS testbed (CeNCRA 5G Lab):** Not currently reachable. All fault-injection ground truth is therefore **in-process demo injection** (`[SYNTHETIC:injected-fault-demo]`) until lab access is confirmed. Phase 6 and Phase 10 gates will distinguish demo-injection from true testbed injection.

---

## 4. What Is Still Assumed (not proven)

1. The normal ranges in `KPIVector.NORMAL_RANGES` are engineering estimates, not calibrated from production data.
2. `dev_kpi_stream` generates Gaussian noise around the normal range midpoints — this is a reasonable structural equation model proxy but is not a validated RAN channel simulator.
3. FlexRIC E2/KPM subscription would provide real PRB utilisation, SINR, and per-slice counters that ASTRA's current schema does not expose.

---

## Gate Decision

**PASSED.** CR²E Phase 2 may proceed.  
All KPIs tagged. Two gaps (PRB, backhaul latency as separate series) documented and logged in `WHAT_WE_DIDNT_SOLVE.md`. Fault-injection capability confirmed for 4 anomaly types in demo mode; testbed dependency noted.
