"""
cr2e/evaluation/evaluator.py
─────────────────────────────────────────────────────────────────────────────
Phase 10 — Root-Cause Ranking Evaluation

Compares CR²E RootCauseReport rankings against known injected-fault ground
truth. Computes precision@1, precision@3, and recall@3.

Anti-fabrication:
  All evaluation numbers carry a data_provenance_tag.
  Results are saved to cr2e/results/eval_report.json with the tag embedded.
  The gate requires at least one fault-injection trial re-run fresh,
  not reusing only the original run (per master prompt Phase 10 gate rule).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cr2e.evaluation.fault_injector_adapter import InjectionRecord, load_injection_records
from cr2e.inference.root_cause_report import RootCauseReport

log = logging.getLogger("cr2e.evaluation.evaluator")


@dataclass
class SingleFaultEval:
    """Evaluation of one fault's root-cause ranking."""

    fault_id: str
    anomaly_type: str
    expected_root_cause: str
    top1_predicted: str
    top3_predicted: list[str]
    hit_at_1: bool      # correct at rank 1
    hit_at_3: bool      # correct in top 3
    data_provenance_tag: str = "[SYNTHETIC:injected-fault-demo]"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationReport:
    """
    Aggregate evaluation metrics across all fault injection trials.

    All metrics are labeled with data_provenance_tag.
    """

    n_trials: int = 0
    n_with_ground_truth: int = 0
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    recall_at_3: float = 0.0
    per_fault_evals: list[SingleFaultEval] = field(default_factory=list)
    data_provenance_tag: str = "[SYNTHETIC:injected-fault-demo]"
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        lines = [
            "=== CR²E Phase 10 Evaluation ===",
            f"  Data source : {self.data_provenance_tag}",
            f"  Trials      : {self.n_trials} (with ground truth: {self.n_with_ground_truth})",
            f"  Precision@1 : {self.precision_at_1:.3f}",
            f"  Precision@3 : {self.precision_at_3:.3f}",
            f"  Recall@3    : {self.recall_at_3:.3f}",
            f"  Evaluated at: {self.evaluated_at}",
        ]
        if self.notes:
            lines.append(f"  Notes       : {self.notes}")
        return "\n".join(lines)

    def to_gate_markdown(self) -> str:
        lines = [
            "# PHASE 10 GATE — Evaluation Results",
            "",
            f"**Data provenance:** `{self.data_provenance_tag}`",
            f"**Trials:** {self.n_trials}  |  **With ground truth:** {self.n_with_ground_truth}",
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Precision@1 | **{self.precision_at_1:.3f}** |",
            f"| Precision@3 | **{self.precision_at_3:.3f}** |",
            f"| Recall@3 | **{self.recall_at_3:.3f}** |",
            "",
            "## Per-Fault Results",
            "",
            "| Fault ID | Anomaly Type | Expected RC | Predicted #1 | Hit@1 | Hit@3 | Tag |",
            "|----------|-------------|-------------|--------------|-------|-------|-----|",
        ]
        for ev in self.per_fault_evals:
            h1 = "✓" if ev.hit_at_1 else "✗"
            h3 = "✓" if ev.hit_at_3 else "✗"
            lines.append(
                f"| {ev.fault_id} "
                f"| {ev.anomaly_type} "
                f"| {ev.expected_root_cause} "
                f"| {ev.top1_predicted} "
                f"| {h1} | {h3} "
                f"| `{ev.data_provenance_tag}` |"
            )

        lines += [
            "",
            f"> **Evaluated at:** {self.evaluated_at}",
            "",
        ]

        if "[SYNTHETIC" in self.data_provenance_tag:
            lines += [
                "> [!WARNING]",
                "> Results are on **synthetic/demo injection data** — not real testbed ground truth.",
                "> For full gate compliance, re-run against Open5GS testbed injection cycles.",
            ]
        else:
            lines += [
                "> [!NOTE]",
                "> Results validated against **real testbed injection** cycles.",
            ]

        return "\n".join(lines)


class Evaluator:
    """
    Evaluates CR²E's root-cause ranking accuracy against injection ground truth.
    """

    def __init__(
        self,
        reports: dict[str, RootCauseReport],
        injection_dir: str | Path = "injection/",
    ) -> None:
        self.reports = reports
        self.injection_dir = injection_dir

    def run(self) -> EvaluationReport:
        """
        Run the evaluation.

        For each injection record with a known expected root cause:
          - Find the corresponding CR²E report
          - Check if expected_root_cause appears at rank 1 or in top 3
          - Compute aggregate precision/recall
        """
        records = load_injection_records(self.injection_dir)

        # Determine overall provenance tag
        tags = {r.data_provenance_tag for r in records}
        overall_tag = (
            "[REAL:injected-fault-ground-truth]"
            if any("REAL" in t for t in tags)
            else "[SYNTHETIC:injected-fault-demo]"
        )

        per_fault = []
        hits_at_1 = 0
        hits_at_3 = 0
        n_with_gt = 0

        for rec in records:
            if rec.expected_root_cause_kpi is None:
                log.info("Skipping %s (no ground truth for NOVEL)", rec.fault_id)
                continue

            n_with_gt += 1
            report = self.reports.get(rec.fault_id)

            if report is None:
                log.warning(
                    "No CR²E report for fault_id=%s — counting as miss.", rec.fault_id
                )
                per_fault.append(
                    SingleFaultEval(
                        fault_id=rec.fault_id,
                        anomaly_type=rec.anomaly_type,
                        expected_root_cause=rec.expected_root_cause_kpi,
                        top1_predicted="N/A",
                        top3_predicted=[],
                        hit_at_1=False,
                        hit_at_3=False,
                        data_provenance_tag=rec.data_provenance_tag,
                        notes="No CR²E report found for this fault ID.",
                    )
                )
                continue

            top1 = report.ranked_causes[0].kpi if report.ranked_causes else "N/A"
            top3 = [rc.kpi for rc in report.ranked_causes[:3]]
            hit1 = top1 == rec.expected_root_cause_kpi
            hit3 = rec.expected_root_cause_kpi in top3

            if hit1:
                hits_at_1 += 1
            if hit3:
                hits_at_3 += 1

            per_fault.append(
                SingleFaultEval(
                    fault_id=rec.fault_id,
                    anomaly_type=rec.anomaly_type,
                    expected_root_cause=rec.expected_root_cause_kpi,
                    top1_predicted=top1,
                    top3_predicted=top3,
                    hit_at_1=hit1,
                    hit_at_3=hit3,
                    data_provenance_tag=rec.data_provenance_tag,
                )
            )

        precision_at_1 = hits_at_1 / n_with_gt if n_with_gt > 0 else 0.0
        precision_at_3 = hits_at_3 / n_with_gt if n_with_gt > 0 else 0.0
        recall_at_3 = precision_at_3  # for single ground-truth-per-fault, recall@k = precision@k

        eval_report = EvaluationReport(
            n_trials=len(records),
            n_with_ground_truth=n_with_gt,
            precision_at_1=round(precision_at_1, 4),
            precision_at_3=round(precision_at_3, 4),
            recall_at_3=round(recall_at_3, 4),
            per_fault_evals=per_fault,
            data_provenance_tag=overall_tag,
            notes=(
                "Demo mode — synthetic injection records. "
                "Re-run with open5gs testbed for testbed-validated numbers."
                if "[SYNTHETIC" in overall_tag else
                "Validated against real Open5GS testbed injection cycles."
            ),
        )

        log.info(eval_report.summary())
        return eval_report

    def save(self, eval_report: EvaluationReport, results_dir: str | Path = "cr2e/results/") -> Path:
        """Persist evaluation report to JSON."""
        out_dir = Path(results_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "eval_report.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(eval_report.to_dict(), f, indent=2)
        log.info("Evaluation report saved: %s", out)
        return out
