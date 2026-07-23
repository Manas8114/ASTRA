"""
cr2e/api/router.py
─────────────────────────────────────────────────────────────────────────────
Phase 7 — CR²E REST + WebSocket API

Mounts under /cr2e/ on port 8001 (separate from ASTRA's 8000).
In demo mode: driven by in-process CR²E engine state.

Endpoints:
  GET  /cr2e/status                   — health + last discovery timestamp
  GET  /cr2e/dag                      — current DAG as JSON
  GET  /cr2e/dag/diff                 — domain vs. discovered diff
  GET  /cr2e/root-cause/{fault_id}    — full RootCauseReport by fault ID
  GET  /cr2e/root-cause/latest        — most recent report
  GET  /cr2e/counterfactual/{fault_id} — CounterfactualPlan for a fault
  POST /cr2e/run-discovery            — trigger a manual discovery run
  GET  /cr2e/evaluation               — latest Phase 10 eval metrics (if available)
  WS   /cr2e/ws                       — streams ROOT_CAUSE_REPORT events
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

log = logging.getLogger("cr2e.api.router")


def cr2e_router(engine) -> APIRouter:
    """
    Build the CR²E API router.

    Parameters
    ----------
    engine : CR2EEngine
        The running CR²E engine instance (from cr2e/main.py).
    """
    router = APIRouter(prefix="/cr2e", tags=["CR2E"])

    # ── Health / Status ───────────────────────────────────────────────────────

    @router.get("/status")
    async def status():
        """CR²E engine health and last discovery metadata."""
        return engine.status()

    @router.get("/health")
    async def health():
        return {"ok": True, "component": "cr2e"}

    # ── DAG ──────────────────────────────────────────────────────────────────

    @router.get("/dag")
    async def get_dag():
        """Return the current discovered DAG as a node-link JSON."""
        dag = engine.current_dag
        if dag is None:
            raise HTTPException(status_code=404, detail="No DAG available yet. Run discovery first.")
        return {
            "algorithm": dag.algorithm,
            "n_samples": dag.n_samples,
            "data_provenance_tag": dag.data_provenance_tag,
            "nodes": list({e.source for e in dag.edges} | {e.target for e in dag.edges}),
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "weight": round(e.weight, 4),
                    "is_domain_required": e.is_domain_required,
                    "violation_hypothesis": e.violation_hypothesis,
                }
                for e in dag.edges
            ],
            "undirected_edges": [list(p) for p in dag.undirected_edges],
            "violations": dag.violations,
        }

    @router.get("/dag/domain")
    async def get_domain_dag():
        """Return the hard-coded domain-constrained partial DAG."""
        from cr2e.graph.domain_dag import DOMAIN_DAG
        return DOMAIN_DAG.to_dict()

    @router.get("/dag/diff")
    async def get_dag_diff():
        """Return the diff between domain DAG and discovered DAG."""
        if engine.last_diff is None:
            raise HTTPException(status_code=404, detail="No diff available. Run discovery first.")
        diff = engine.last_diff
        return {
            "agreed": len(diff.agreed),
            "domain_only": [{"edge": list(d.edge), "hypothesis": d.hypothesis} for d in diff.domain_only],
            "discovery_only": [{"edge": list(d.edge), "hypothesis": d.hypothesis} for d in diff.discovery_only],
            "reversed_edges": [{"edge": list(d.edge), "hypothesis": d.hypothesis} for d in diff.reversed_edges],
            "violations": [{"edge": list(d.edge), "hypothesis": d.hypothesis} for d in diff.violations],
            "has_critical_violations": diff.has_critical_violations,
        }

    # ── Root-cause reports ───────────────────────────────────────────────────

    @router.get("/root-cause/latest")
    async def get_latest_root_cause():
        """Most recent RootCauseReport."""
        report = engine.latest_report
        if report is None:
            return {"status": "no_report_yet"}
        return report.to_dict()

    @router.get("/root-cause/{fault_id}")
    async def get_root_cause(fault_id: str):
        """RootCauseReport for a specific fault ID."""
        report = engine.get_report(fault_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"No report for fault_id={fault_id}")
        return report.to_dict()

    # ── Counterfactual plans ─────────────────────────────────────────────────

    @router.get("/counterfactual/{fault_id}")
    async def get_counterfactual(fault_id: str):
        """CounterfactualPlan for a specific fault ID."""
        plan = engine.get_counterfactual(fault_id)
        if plan is None:
            raise HTTPException(
                status_code=404,
                detail=f"No counterfactual plan for fault_id={fault_id}",
            )
        return plan.to_dict()

    # ── Manual discovery trigger ──────────────────────────────────────────────

    @router.post("/run-discovery")
    async def trigger_discovery():
        """Trigger a manual causal discovery run using the current KPI history."""
        asyncio.create_task(engine.run_discovery())
        return {"status": "discovery_started", "algorithm": engine.settings.discovery_algorithm}

    # ── Evaluation (Phase 10) ─────────────────────────────────────────────────

    @router.get("/evaluation")
    async def get_evaluation():
        """Latest Phase 10 evaluation metrics (if available)."""
        return engine.get_evaluation_results()

    # ── WebSocket stream ──────────────────────────────────────────────────────

    @router.websocket("/ws")
    async def websocket_stream(websocket: WebSocket):
        """
        WebSocket endpoint that streams ROOT_CAUSE_REPORT events.

        Each message is a JSON-serialised RootCauseReport.
        """
        await websocket.accept()
        queue = engine.subscribe_ws()
        log.info("WebSocket client connected to /cr2e/ws")
        try:
            while True:
                report_dict = await queue.get()
                await websocket.send_text(json.dumps(report_dict))
        except WebSocketDisconnect:
            log.info("WebSocket client disconnected from /cr2e/ws")
        finally:
            engine.unsubscribe_ws(queue)

    return router
