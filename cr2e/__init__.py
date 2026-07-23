"""
cr2e/__init__.py
─────────────────────────────────────────────────────────────────────────────
CR²E — Causal RAN Root-Cause Engine

Explains *why* ASTRA's anomalies occur and prescribes minimal interventions.
Sits downstream of ASTRA; does not re-implement detection.

Story:  ASTRA detects/predicts  →  CR²E explains/prescribes

Anti-fabrication: every effect size, accuracy, or latency figure is tagged
[REAL:testbed], [REAL:injected-fault-ground-truth], or [SYNTHETIC] at the
dataclass level and propagated to every API response, log line, and gate doc.
"""

__version__ = "0.1.0"
__author__ = "CR²E — Causal RAN Root-Cause Engine"
