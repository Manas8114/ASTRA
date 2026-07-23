"""
cr2e/graph/dag_store.py
─────────────────────────────────────────────────────────────────────────────
Persistence layer for the discovered DAG.

Saves/loads DiscoveredDAG as JSON to the path configured in CR2ESettings.
Also maintains a history of discovery runs (last N snapshots) for audit.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cr2e.graph.discovery import DiscoveredDAG, DiscoveredEdge
from cr2e.graph.dag_diff import DagDiff

log = logging.getLogger("cr2e.graph.dag_store")

_MAX_HISTORY = 10  # keep last 10 snapshots


class DagStore:
    """Persists the current DiscoveredDAG and diff to disk."""

    def __init__(self, snapshot_path: str | Path) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Save ─────────────────────────────────────────────────────────────────

    def save(self, dag: DiscoveredDAG, diff: Optional[DagDiff] = None) -> None:
        """Persist the discovered DAG and optional diff."""
        record = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "algorithm": dag.algorithm,
            "n_samples": dag.n_samples,
            "runtime_seconds": round(dag.runtime_seconds, 3),
            "data_provenance_tag": dag.data_provenance_tag,
            "alpha": dag.alpha,
            "ci_test": dag.ci_test,
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "weight": round(e.weight, 4),
                    "is_domain_required": e.is_domain_required,
                    "is_domain_forbidden": e.is_domain_forbidden,
                    "violation_hypothesis": e.violation_hypothesis,
                }
                for e in dag.edges
            ],
            "undirected_edges": [list(p) for p in dag.undirected_edges],
            "violations": dag.violations,
        }

        if diff is not None:
            record["diff_summary"] = {
                "agreed": len(diff.agreed),
                "domain_only": len(diff.domain_only),
                "discovery_only": len(diff.discovery_only),
                "reversed_edges": len(diff.reversed_edges),
                "violations": len(diff.violations),
                "has_critical_violations": diff.has_critical_violations,
            }

        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        log.info(
            "DAG snapshot saved: %s edges, tag=%s → %s",
            len(dag.edges), dag.data_provenance_tag, self.snapshot_path,
        )

        self._append_history(record)

    def _append_history(self, record: dict) -> None:
        """Maintain a rolling history file next to the snapshot."""
        history_path = self.snapshot_path.with_suffix(".history.json")
        history: list[dict] = []
        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, OSError):
                history = []
        history.append(record)
        history = history[-_MAX_HISTORY:]
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    # ── Load ─────────────────────────────────────────────────────────────────

    def load(self) -> Optional[DiscoveredDAG]:
        """Load the most recent snapshot. Returns None if no snapshot exists."""
        if not self.snapshot_path.exists():
            log.info("No DAG snapshot found at %s", self.snapshot_path)
            return None
        with open(self.snapshot_path, "r", encoding="utf-8") as f:
            record = json.load(f)
        edges = [
            DiscoveredEdge(
                source=e["source"],
                target=e["target"],
                weight=e.get("weight", 1.0),
                is_domain_required=e.get("is_domain_required", False),
                is_domain_forbidden=e.get("is_domain_forbidden", False),
                violation_hypothesis=e.get("violation_hypothesis"),
            )
            for e in record.get("edges", [])
        ]
        dag = DiscoveredDAG(
            algorithm=record.get("algorithm", "pc"),
            edges=edges,
            undirected_edges=[tuple(p) for p in record.get("undirected_edges", [])],
            violations=record.get("violations", []),
            data_provenance_tag=record.get("data_provenance_tag", "[SYNTHETIC]"),
            n_samples=record.get("n_samples", 0),
            runtime_seconds=record.get("runtime_seconds", 0.0),
            alpha=record.get("alpha", 0.05),
            ci_test=record.get("ci_test", "fisherz"),
        )
        log.info(
            "DAG snapshot loaded: %d edges, tag=%s, saved_at=%s",
            len(dag.edges), dag.data_provenance_tag, record.get("saved_at"),
        )
        return dag
