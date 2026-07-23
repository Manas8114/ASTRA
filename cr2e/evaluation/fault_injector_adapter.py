"""
cr2e/evaluation/fault_injector_adapter.py
─────────────────────────────────────────────────────────────────────────────
Phase 10 — Fault Injector Adapter

Maps ASTRA AnomalyType → expected root-cause KPI for ground-truth comparison.
Reads fault-injection records from ASTRA's injection/ directory.

Anti-fabrication:
  Ground truth = actual injected fault type, not inferred labels.
  Precision/recall computed against this explicit mapping.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("cr2e.evaluation.fault_injector_adapter")


# Ground-truth mapping: injected anomaly type → expected rank-1 root cause KPI
# Derived from ASTRA's action_engine.py and Phase 1 gate.
GROUND_TRUTH_MAP: dict[str, str] = {
    "CONGESTION":    "slice_utilisation_pct",  # high load → latency/throughput degradation
    "HIGH_LATENCY":  "latency_ms",             # directly elevated latency
    "PACKET_LOSS":   "bler_pct",               # high BLER → throughput drop
    "SLICE_OVERFLOW": "slice_utilisation_pct", # slice capacity exceeded
    "NOVEL":         None,                     # no ground truth for novel faults
}


@dataclass
class InjectionRecord:
    """One fault-injection event with known ground truth."""
    fault_id: str
    anomaly_type: str
    expected_root_cause_kpi: Optional[str]
    data_provenance_tag: str = "[SYNTHETIC:injected-fault-demo]"
    timestamp: str = ""
    notes: str = ""


def load_injection_records(astra_injection_dir: str | Path = "injection/") -> list[InjectionRecord]:
    """
    Load injection records from ASTRA's injection/ directory.

    Looks for JSON files with {anomaly_type, timestamp, fault_id} fields.
    Falls back to synthetic records if directory is empty or missing.
    """
    injection_dir = Path(astra_injection_dir)
    records: list[InjectionRecord] = []

    if injection_dir.exists():
        for jf in sorted(injection_dir.glob("*.json")):
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                anomaly_type = data.get("anomaly_type", "NOVEL")
                records.append(
                    InjectionRecord(
                        fault_id=data.get("fault_id", jf.stem),
                        anomaly_type=anomaly_type,
                        expected_root_cause_kpi=GROUND_TRUTH_MAP.get(anomaly_type),
                        data_provenance_tag=data.get(
                            "data_provenance_tag", "[REAL:injected-fault-ground-truth]"
                        ),
                        timestamp=data.get("timestamp", ""),
                        notes=data.get("notes", ""),
                    )
                )
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Could not load injection record %s: %s", jf, exc)

    if not records:
        log.info(
            "No injection records found in %s — using synthetic demo records "
            "([SYNTHETIC:injected-fault-demo])",
            injection_dir,
        )
        # Synthetic demo records (one per known anomaly type)
        for anomaly_type, expected_kpi in GROUND_TRUTH_MAP.items():
            if expected_kpi is None:
                continue
            records.append(
                InjectionRecord(
                    fault_id=f"demo-{anomaly_type.lower()}",
                    anomaly_type=anomaly_type,
                    expected_root_cause_kpi=expected_kpi,
                    data_provenance_tag="[SYNTHETIC:injected-fault-demo]",
                    notes="Auto-generated demo record — no real testbed injection.",
                )
            )

    log.info("Loaded %d injection records.", len(records))
    return records
