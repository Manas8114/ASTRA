"""
cr2e/explanation/nl_explainer.py
─────────────────────────────────────────────────────────────────────────────
Phase 7 — Natural-Language Explanation Layer

Generates a 2–3 sentence human-readable root-cause explanation from a
RootCauseReport by calling a local Ollama LLM (default: qwen2.5:7b).

Design decisions:
  - Ollama local (matches OpenClaw stack, no extra cloud dependency)
  - Template fallback if Ollama is unreachable or model not loaded
  - Every explanation is PREPENDED with the data_provenance_tag so it
    cannot be mistaken for a claim from real testbed data
  - The LLM is prompted explicitly NOT to invent numbers not in the report

Anti-fabrication:
  The LLM is given only facts from the RootCauseReport (ATE values, CI,
  anomaly type). The prompt explicitly forbids fabricating numbers.
  The template fallback produces a deterministic, fully traceable string.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from cr2e.inference.root_cause_report import RootCauseReport

log = logging.getLogger("cr2e.explanation.nl_explainer")

_SYSTEM_PROMPT = """You are a 5G RAN network operations analyst. Your task is to write a
2-3 sentence plain-English explanation of a root-cause analysis result.

STRICT RULES:
1. Only use numbers and KPI names explicitly provided in the USER message.
2. Do NOT invent, extrapolate, or hallucinate any metric values.
3. Do NOT recommend specific parameter values unless they appear in the report.
4. Keep the explanation under 100 words.
5. Start the explanation with: "Root cause analysis indicates..."
"""

_USER_TEMPLATE = """Fault type: {anomaly_type}
Cell: {cell_id}
Data source: {data_provenance_tag}
Top cause: {top_cause}

Ranked causes:
{cause_lines}

Write a 2-3 sentence plain-English explanation following the STRICT RULES above."""


class NLExplainer:
    """
    Generates natural-language root-cause explanations via Ollama.

    Falls back to a template string if Ollama is unavailable.
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout: float = 30.0,
    ) -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def explain(self, report: RootCauseReport) -> str:
        """
        Generate a NL explanation for a RootCauseReport.

        Returns a string prefixed with the data_provenance_tag.
        If Ollama is unreachable, returns a template-based explanation.
        """
        try:
            text = self._call_ollama(report)
        except Exception as exc:
            log.warning(
                "Ollama call failed (%s); using template fallback.", exc
            )
            text = self._template_fallback(report)

        # Prepend provenance tag — always, without exception
        return f"{report.data_provenance_tag} {text}"

    def _call_ollama(self, report: RootCauseReport) -> str:
        cause_lines = "\n".join(
            f"  #{rc.rank} {rc.kpi} → {rc.outcome_kpi}: "
            f"ATE={rc.ate:+.4f} 95%CI[{rc.ci_lower:+.4f},{rc.ci_upper:+.4f}] "
            f"({'significant' if rc.is_significant else 'not significant'})"
            for rc in report.ranked_causes
        )

        user_msg = _USER_TEMPLATE.format(
            anomaly_type=report.anomaly_type,
            cell_id=report.cell_id,
            data_provenance_tag=report.data_provenance_tag,
            top_cause=report.top_cause,
            cause_lines=cause_lines or "No significant causes identified.",
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "top_p": 0.9, "num_predict": 150},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()

    def _template_fallback(self, report: RootCauseReport) -> str:
        """Deterministic, citation-free fallback explanation."""
        if not report.ranked_causes:
            return (
                f"Root cause analysis indicates no statistically significant "
                f"causal driver was identified for the {report.anomaly_type} event "
                f"on cell {report.cell_id}. "
                "Possible causes: insufficient KPI history, unmeasured confounders, "
                "or a truly novel fault pattern outside the training distribution."
            )

        top = report.ranked_causes[0]
        sig_note = "a statistically significant" if top.is_significant else "a (non-significant)"
        second = ""
        if len(report.ranked_causes) > 1:
            rc2 = report.ranked_causes[1]
            second = (
                f" Secondary contributor: {rc2.kpi} "
                f"(ATE={rc2.ate:+.4f} 95%CI[{rc2.ci_lower:+.4f},{rc2.ci_upper:+.4f}])."
            )

        return (
            f"Root cause analysis indicates {sig_note} causal effect of "
            f"{top.kpi} on {top.outcome_kpi} "
            f"(ATE={top.ate:+.4f}, 95% CI [{top.ci_lower:+.4f}, {top.ci_upper:+.4f}]), "
            f"suggesting {top.kpi} is the primary driver of the {report.anomaly_type} "
            f"event on cell {report.cell_id}.{second} "
            f"Prescriptive intervention: reduce {top.kpi} as estimated by the "
            "counterfactual plan (see intervention_engine output)."
        )
