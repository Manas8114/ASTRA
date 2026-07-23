"""
cr2e/main.py
─────────────────────────────────────────────────────────────────────────────
Phase 7 — CR²E Service Entry Point

Runs as a FastAPI app on port 8001 (separate from ASTRA's 8000).
In demo mode, polls ASTRA's in-process state via HTTP.
In lab mode, subscribes to ASTRA's WebSocket stream.

The CR²E engine loop:
  1. On startup: run causal discovery on 24h KPI history → build DAG
  2. Listen for ANOMALY_DETECTED events from ASTRA
  3. For each event: estimate causal effects → rank → generate counterfactual → explain
  4. Broadcast ROOT_CAUSE_REPORT over WebSocket
  5. Every 6h (configurable): re-run discovery to update the DAG

Usage:
  python -m cr2e.main
  or via Docker Compose: cr2e-service
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cr2e.config import get_cr2e_settings
from cr2e.api.router import cr2e_router
from cr2e.graph.domain_dag import DOMAIN_DAG
from cr2e.graph.discovery import run_discovery, DiscoveredDAG
from cr2e.graph.dag_diff import compute_dag_diff, DagDiff
from cr2e.graph.dag_store import DagStore
from cr2e.inference.causal_query import (
    AnomalyEvent,
    build_queries_for_event,
)
from cr2e.inference.estimator import CausalEstimator
from cr2e.inference.ranker import RootCauseRanker
from cr2e.inference.root_cause_report import RootCauseReport
from cr2e.counterfactual.intervention_engine import InterventionEngine
from cr2e.counterfactual.intervention_validator import InterventionValidator
from cr2e.explanation.nl_explainer import NLExplainer

log = logging.getLogger("cr2e.main")

# ── Settings ──────────────────────────────────────────────────────────────────

_settings = get_cr2e_settings()

# ── CR²E Engine ──────────────────────────────────────────────────────────────


class CR2EEngine:
    """
    Central CR²E processing engine.

    Manages:
      - KPI history buffer
      - DAG discovery and storage
      - Per-fault causal estimation + ranking + counterfactual
      - WebSocket subscriber registry
    """

    def __init__(self) -> None:
        self.settings = _settings
        self._dag_store = DagStore(_settings.dag_snapshot_path)
        self._estimator: Optional[CausalEstimator] = None
        self._ranker = RootCauseRanker(top_k=_settings.top_k_causes)
        self._intervention_engine = InterventionEngine(
            target_resolution_pct=_settings.counterfactual_target_resolution_pct * 100
        )
        self._validator = InterventionValidator(mode=_settings.mode)
        self._explainer = NLExplainer(
            ollama_url=_settings.ollama_url,
            model=_settings.ollama_model,
            timeout=_settings.ollama_timeout,
        )

        # State
        self.current_dag: Optional[DiscoveredDAG] = None
        self.last_diff: Optional[DagDiff] = None
        self.latest_report: Optional[RootCauseReport] = None
        self._report_cache: dict[str, RootCauseReport] = {}
        self._counterfactual_cache: dict[str, object] = {}
        self._kpi_history: deque[dict] = deque(maxlen=_settings.history_window_hours * 3600)
        self._ws_subscribers: list[asyncio.Queue] = []
        self._discovery_running = False
        self._last_discovery_at: Optional[float] = None

        # MLflow
        self._mlflow = None
        if _settings.mlflow_enabled:
            try:
                import mlflow
                mlflow.set_tracking_uri(_settings.mlflow_uri)
                mlflow.set_experiment(_settings.mlflow_experiment)
                self._mlflow = mlflow
                log.info("MLflow tracking: %s / %s", _settings.mlflow_uri, _settings.mlflow_experiment)
            except ImportError:
                log.warning("mlflow not installed — tracking disabled.")

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "ok": True,
            "mode": self.settings.mode,
            "dag_available": self.current_dag is not None,
            "dag_algorithm": self.current_dag.algorithm if self.current_dag else None,
            "dag_n_samples": self.current_dag.n_samples if self.current_dag else 0,
            "dag_edges": len(self.current_dag.edges) if self.current_dag else 0,
            "last_discovery_at": (
                datetime.fromtimestamp(self._last_discovery_at, tz=timezone.utc).isoformat()
                if self._last_discovery_at else None
            ),
            "kpi_buffer_size": len(self._kpi_history),
            "reports_in_cache": len(self._report_cache),
            "latest_report_fault_id": self.latest_report.fault_id if self.latest_report else None,
        }

    def get_report(self, fault_id: str) -> Optional[RootCauseReport]:
        return self._report_cache.get(fault_id)

    def get_counterfactual(self, fault_id: str):
        return self._counterfactual_cache.get(fault_id)

    def get_evaluation_results(self) -> dict:
        eval_path = Path("cr2e/results/eval_report.json")
        if not eval_path.exists():
            return {"status": "not_available", "note": "Run Phase 10 evaluation first."}
        with open(eval_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── WebSocket subscriptions ───────────────────────────────────────────────

    def subscribe_ws(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._ws_subscribers.append(q)
        return q

    def unsubscribe_ws(self, q: asyncio.Queue) -> None:
        try:
            self._ws_subscribers.remove(q)
        except ValueError:
            pass

    async def _broadcast(self, report: RootCauseReport) -> None:
        payload = report.to_dict()
        for q in list(self._ws_subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("WebSocket subscriber queue full — dropping message.")

    # ── KPI History ───────────────────────────────────────────────────────────

    def ingest_kpi(self, kpi_dict: dict) -> None:
        """Add a KPI snapshot to the rolling history buffer."""
        self._kpi_history.append(kpi_dict)

    def _history_as_dataframe(self) -> pd.DataFrame:
        if not self._kpi_history:
            return pd.DataFrame()
        return pd.DataFrame(list(self._kpi_history))

    def _get_provenance_tag(self) -> str:
        source = os.getenv("KPI_SOURCE", "dev").lower()
        if source == "dev":
            return "[SYNTHETIC]"
        if source in ("open5gs", "open5gs_file"):
            return "[REAL:injected-fault-ground-truth]"
        return "[REAL:testbed]"

    # ── Causal Discovery ──────────────────────────────────────────────────────

    async def run_discovery(self) -> None:
        """Run causal discovery on the current KPI history (background task)."""
        if self._discovery_running:
            log.info("Discovery already running — skipping.")
            return
        self._discovery_running = True
        try:
            df = self._history_as_dataframe()
            tag = self._get_provenance_tag()

            if df.empty or len(df) < 50:
                log.warning(
                    "Insufficient history for discovery (%d rows). "
                    "Loading snapshot or using domain-only DAG.",
                    len(df),
                )
                self.current_dag = self._dag_store.load()
                if self.current_dag is None:
                    # Bootstrap: build a minimal DAG from domain constraints only
                    self.current_dag = _bootstrap_dag_from_domain(tag)
                self._update_estimator()
                return

            log.info(
                "Starting causal discovery: %d rows, algorithm=%s, tag=%s",
                len(df), self.settings.discovery_algorithm, tag,
            )

            run_fn = lambda: run_discovery(
                df=df,
                algorithm=self.settings.discovery_algorithm,
                data_provenance_tag=tag,
                alpha=self.settings.discovery_alpha,
                ci_test=self.settings.discovery_ci_test,
            )

            # Run in thread pool to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            dag = await loop.run_in_executor(None, run_fn)

            diff = compute_dag_diff(DOMAIN_DAG, dag)
            self._dag_store.save(dag, diff)
            self.current_dag = dag
            self.last_diff = diff
            self._last_discovery_at = time.monotonic()
            self._update_estimator()

            log.info("Discovery complete: %s", dag.summary())
            log.info("DAG diff: %s", diff.to_gate_markdown()[:400])

            # MLflow logging
            if self._mlflow:
                with self._mlflow.start_run(run_name=f"discovery-{dag.algorithm}"):
                    self._mlflow.log_params({
                        "algorithm": dag.algorithm,
                        "n_samples": dag.n_samples,
                        "alpha": dag.alpha,
                        "ci_test": dag.ci_test,
                        "data_provenance_tag": tag,
                    })
                    self._mlflow.log_metrics({
                        "n_edges": len(dag.edges),
                        "n_violations": len(dag.violations),
                        "runtime_seconds": dag.runtime_seconds,
                    })

        finally:
            self._discovery_running = False

    def _update_estimator(self) -> None:
        if self.current_dag is not None:
            self._estimator = CausalEstimator(
                dag=self.current_dag,
                refutation_tests=self.settings.refutation_tests,
                min_history_rows=self.settings.min_history_rows,
            )

    # ── Per-fault analysis ────────────────────────────────────────────────────

    async def process_anomaly(self, anomaly_event_dict: dict) -> Optional[RootCauseReport]:
        """
        Main CR²E processing path for one ASTRA anomaly event.

        Steps:
          1. Build CausalQuery objects for each treatment candidate
          2. Estimate effects via DoWhy + LinearDML
          3. Rank and build RootCauseReport
          4. Compute CounterfactualPlan
          5. Generate NL explanation
          6. Broadcast over WebSocket + cache + log to MLflow
        """
        if self._estimator is None:
            log.warning("No DAG available yet — skipping anomaly processing.")
            return None

        tag = self._get_provenance_tag()
        fault_event = AnomalyEvent(
            fault_id=anomaly_event_dict.get("fault_id", f"fault-{int(time.time())}"),
            cell_id=anomaly_event_dict.get("cell_id", "cell_001"),
            anomaly_type=anomaly_event_dict.get("anomaly_type", "NOVEL"),
            timestamp=anomaly_event_dict.get("timestamp", datetime.now(timezone.utc).isoformat()),
            attention_weights=anomaly_event_dict.get("attention_weights", {}),
            data_provenance_tag=tag,
        )

        log.info("Processing anomaly: %s / %s", fault_event.fault_id, fault_event.anomaly_type)

        df = self._history_as_dataframe()
        queries = build_queries_for_event(
            fault_event=fault_event,
            kpi_history=df,
            data_provenance_tag=tag,
        )

        if not queries:
            log.warning("No queries built for fault %s — empty history?", fault_event.fault_id)
            return None

        # Estimate (run in thread pool — DoWhy is CPU-bound)
        loop = asyncio.get_event_loop()
        estimates = await loop.run_in_executor(
            None,
            lambda: [self._estimator.estimate(q) for q in queries],
        )

        # NL explanation
        temp_report = self._ranker.rank(fault_event, estimates, self.settings.discovery_algorithm)
        explanation = self._explainer.explain(temp_report.report)

        # Final ranking with explanation
        result = self._ranker.rank(
            fault_event, estimates,
            discovery_algorithm=self.settings.discovery_algorithm,
            nl_explanation=explanation,
        )
        report = result.report

        # Counterfactual plan
        plan = self._intervention_engine.compute_plan(report, estimates)
        report.counterfactual_plan = plan.to_dict()
        self._counterfactual_cache[fault_event.fault_id] = plan

        # Validate counterfactual (demo mode always, testbed when available)
        validation = self._validator.validate(plan)
        log.info("Counterfactual validation: %s", validation.data_provenance_tag)

        # Cache and broadcast
        self._report_cache[fault_event.fault_id] = report
        self.latest_report = report
        await self._broadcast(report)

        log.info(report.summary())

        # MLflow logging
        if self._mlflow:
            with self._mlflow.start_run(run_name=f"root-cause-{fault_event.fault_id}"):
                self._mlflow.log_params({
                    "fault_id": fault_event.fault_id,
                    "anomaly_type": fault_event.anomaly_type,
                    "top_cause": report.top_cause,
                    "data_provenance_tag": tag,
                })
                if report.ranked_causes:
                    self._mlflow.log_metrics({
                        "top_ate": report.ranked_causes[0].ate,
                        "top_ci_lower": report.ranked_causes[0].ci_lower,
                        "top_ci_upper": report.ranked_causes[0].ci_upper,
                    })

        return report

    # ── Background loops ──────────────────────────────────────────────────────

    async def astra_poll_loop(self, astra_base_url: str = "http://localhost:8000") -> None:
        """Poll ASTRA's REST API for new anomalies (demo mode)."""
        seen_fault_ids: set[str] = set()
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                try:
                    resp = await client.get(f"{astra_base_url}/anomalies")
                    if resp.status_code == 200:
                        anomalies = resp.json()
                        for a in anomalies[-10:]:
                            fid = a.get("fault_id") or a.get("id") or str(a.get("timestamp", ""))
                            a["fault_id"] = fid
                            if fid not in seen_fault_ids:
                                seen_fault_ids.add(fid)
                                await self.process_anomaly(a)

                    kpi_resp = await client.get(f"{astra_base_url}/kpis/current")
                    if kpi_resp.status_code == 200:
                        self.ingest_kpi(kpi_resp.json())

                except Exception as exc:
                    log.debug("ASTRA poll error: %s", exc)
                await asyncio.sleep(2)

    async def discovery_refresh_loop(self, interval_hours: int = 6) -> None:
        """Periodically re-run causal discovery."""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            log.info("Scheduled discovery refresh.")
            await self.run_discovery()


# ── Bootstrap minimal DAG ─────────────────────────────────────────────────────

def _bootstrap_dag_from_domain(tag: str) -> DiscoveredDAG:
    """
    Create a minimal DiscoveredDAG from domain constraints only.
    Used when there is insufficient history for PC/NOTEARS.
    """
    from cr2e.graph.discovery import DiscoveredDAG, DiscoveredEdge
    edges = [
        DiscoveredEdge(
            source=e.source,
            target=e.target,
            weight=1.0,
            is_domain_required=True,
        )
        for e in DOMAIN_DAG.required_edges
    ]
    return DiscoveredDAG(
        algorithm="domain-only",
        edges=edges,
        undirected_edges=[],
        violations=[],
        data_provenance_tag=tag,
        n_samples=0,
        runtime_seconds=0.0,
    )


# ── FastAPI app ───────────────────────────────────────────────────────────────

engine = CR2EEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks on startup."""
    # Load any persisted DAG snapshot
    loaded = engine._dag_store.load()
    if loaded:
        engine.current_dag = loaded
        engine._update_estimator()
        log.info("Loaded persisted DAG snapshot: %d edges", len(loaded.edges))
    else:
        # Bootstrap from domain constraints
        engine.current_dag = _bootstrap_dag_from_domain(engine._get_provenance_tag())
        engine._update_estimator()
        log.info("Bootstrapped domain-only DAG.")

    # Schedule initial discovery
    asyncio.create_task(engine.run_discovery())

    # Start ASTRA polling loop
    asyncio.create_task(
        engine.astra_poll_loop(
            astra_base_url=os.getenv("ASTRA_BASE_URL", "http://localhost:8000")
        )
    )

    # Schedule periodic discovery refresh
    asyncio.create_task(engine.discovery_refresh_loop(interval_hours=6))

    log.info("CR²E engine started in mode=%s", _settings.mode)
    yield
    log.info("CR²E engine shutting down.")


app = FastAPI(
    title="CR²E — Causal RAN Root-Cause Engine",
    description=(
        "Causal explanation and prescription layer for ASTRA. "
        "Answers: why did the RAN fail, and what is the minimal fix? "
        "Extends (does not replace) ASTRA's detect/predict capabilities."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cr2e_router(engine))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    uvicorn.run(
        "cr2e.main:app",
        host=_settings.host,
        port=_settings.port,
        reload=False,
    )
