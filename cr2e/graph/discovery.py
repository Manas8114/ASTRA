"""
cr2e/graph/discovery.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — Causal Discovery (PC Algorithm + NOTEARS)

Learns causal edges from historical KPI data, constrained by the domain DAG.
Cross-checks discovered edges against domain constraints and flags anomalies
with a one-line hypothesis (never silently merges contradictions).

Anti-fabrication:
  All discovery results carry a data_provenance_tag inherited from the input
  DataFrame. Results tagged [SYNTHETIC] if data came from dev mode.

References:
  - Spirtes, Glymour, Scheines (2000) "Causation, Prediction, and Search"
    (PC algorithm original formulation).
  - Zheng et al. (2018) "DAGs with NO TEARS" — NeurIPS 2018 (NOTEARS).
    https://arxiv.org/abs/1803.01422
  - causal-learn library: https://causal-learn.readthedocs.io/
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from cr2e.graph.domain_dag import DOMAIN_DAG, DomainDAG, KPI_NODES

log = logging.getLogger("cr2e.graph.discovery")


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class DiscoveredEdge:
    source: str
    target: str
    weight: float = 1.0  # edge strength (NOTEARS) or 1.0 for PC orientation
    is_domain_required: bool = False
    is_domain_forbidden: bool = False
    violation_hypothesis: Optional[str] = None


@dataclass
class DiscoveredDAG:
    """
    Output of one causal discovery run.

    Attributes
    ----------
    algorithm : str
        "pc" or "notears"
    edges : list of DiscoveredEdge
        All directed edges in the learned graph (after merging domain constraints).
    undirected_edges : list of tuple[str, str]
        Edges where PC could not determine orientation (Markov equivalence class).
    violations : list of dict
        Edges that contradicted domain constraints — flagged, not silently merged.
    data_provenance_tag : str
        "[SYNTHETIC]", "[REAL:testbed]", or "[REAL:injected-fault-ground-truth]"
    n_samples : int
        Number of data rows used.
    runtime_seconds : float
        Wall-clock time for discovery.
    alpha : float
        PC independence test significance level (if algorithm == "pc").
    ci_test : str
        Conditional independence test used.
    """

    algorithm: str
    edges: list[DiscoveredEdge] = field(default_factory=list)
    undirected_edges: list[tuple[str, str]] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    data_provenance_tag: str = "[SYNTHETIC]"
    n_samples: int = 0
    runtime_seconds: float = 0.0
    alpha: float = 0.05
    ci_test: str = "fisherz"

    def directed_pairs(self) -> list[tuple[str, str]]:
        """Return all directed edges as (source, target) pairs."""
        return [(e.source, e.target) for e in self.edges]

    def to_networkx(self):
        """Return as networkx DiGraph for visualization / diff."""
        try:
            import networkx as nx
        except ImportError as exc:
            raise ImportError("networkx required: pip install networkx") from exc
        G = nx.DiGraph()
        G.add_nodes_from(KPI_NODES)
        for e in self.edges:
            G.add_edge(e.source, e.target, weight=e.weight)
        return G

    def summary(self) -> str:
        lines = [
            f"Discovered DAG ({self.algorithm}, n={self.n_samples}, "
            f"α={self.alpha}, ci={self.ci_test})",
            f"  Tag: {self.data_provenance_tag}",
            f"  Directed edges: {len(self.edges)}",
            f"  Undirected edges: {len(self.undirected_edges)}",
            f"  Domain violations: {len(self.violations)}",
            f"  Runtime: {self.runtime_seconds:.2f}s",
        ]
        if self.violations:
            lines.append("\n  ⚠ Violations (flagged, not merged):")
            for v in self.violations:
                lines.append(f"    {v['edge']} — {v['hypothesis']}")
        return "\n".join(lines)


# ── PC Algorithm Wrapper ──────────────────────────────────────────────────────

def run_pc(
    df: pd.DataFrame,
    domain_dag: DomainDAG = DOMAIN_DAG,
    alpha: float = 0.05,
    ci_test: str = "fisherz",
    data_provenance_tag: str = "[SYNTHETIC]",
) -> DiscoveredDAG:
    """
    Run PC algorithm on `df` with domain DAG as background knowledge.

    Parameters
    ----------
    df : pd.DataFrame
        Columns must be a subset of KPI_NODES; rows are time-ordered samples.
    domain_dag : DomainDAG
        Provides required/forbidden edges as background knowledge.
    alpha : float
        Significance level for conditional independence tests.
    ci_test : str
        causal-learn CI test identifier.
    data_provenance_tag : str
        Propagated to the returned DiscoveredDAG.

    Returns
    -------
    DiscoveredDAG
    """
    try:
        from causallearn.search.ConstraintBased.PC import pc
        from causallearn.utils.GraphUtils import GraphUtils
        from causallearn.graph.Endpoint import Endpoint
        import causallearn.utils.PCUtils.BackgroundKnowledge as bk_module
    except ImportError as exc:
        raise ImportError(
            "causal-learn required: pip install causal-learn"
        ) from exc

    # Only use columns present in KPI_NODES
    cols = [c for c in KPI_NODES if c in df.columns]
    if len(cols) < 2:
        raise ValueError(f"Need ≥2 KPI columns for discovery; got: {cols}")

    data = df[cols].dropna().values.astype(float)
    n_samples = len(data)
    log.info(
        "PC discovery: %d rows × %d cols, α=%.3f, ci=%s, tag=%s",
        n_samples, len(cols), alpha, ci_test, data_provenance_tag,
    )

    # Build causal-learn background knowledge
    bk = bk_module.BackgroundKnowledge()
    req_pairs, forb_pairs = domain_dag.to_causal_learn_format()

    node_names = cols
    for src, tgt in req_pairs:
        if src in node_names and tgt in node_names:
            bk.add_required_by_node(node_names.index(src), node_names.index(tgt))
    for src, tgt in forb_pairs:
        if src in node_names and tgt in node_names:
            bk.add_forbidden_by_node(node_names.index(src), node_names.index(tgt))

    t0 = time.perf_counter()
    cg = pc(
        data,
        alpha=alpha,
        indep_test=ci_test,
        background_knowledge=bk,
        show_progress=False,
    )
    runtime = time.perf_counter() - t0

    # Parse result graph
    directed: list[DiscoveredEdge] = []
    undirected: list[tuple[str, str]] = []

    adj = cg.G.graph  # shape (n, n); 1 means edge endpoint
    n = len(cols)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if adj[i, j] == -1 and adj[j, i] == 1:
                # directed i → j
                directed.append(
                    DiscoveredEdge(source=cols[i], target=cols[j], weight=1.0)
                )
            elif adj[i, j] == -1 and adj[j, i] == -1 and i < j:
                # undirected
                undirected.append((cols[i], cols[j]))

    # Annotate domain status
    req_set = {(e.source, e.target) for e in domain_dag.required_edges}
    forb_set = {(e.source, e.target) for e in domain_dag.forbidden_edges}
    for e in directed:
        e.is_domain_required = (e.source, e.target) in req_set
        e.is_domain_forbidden = (e.source, e.target) in forb_set

    # Add required edges that PC may have missed (domain override)
    present = {(e.source, e.target) for e in directed}
    for de in domain_dag.required_edges:
        if de.source in cols and de.target in cols:
            if (de.source, de.target) not in present:
                log.debug(
                    "Domain-required edge %s→%s not discovered; adding.",
                    de.source, de.target,
                )
                directed.append(
                    DiscoveredEdge(
                        source=de.source,
                        target=de.target,
                        weight=1.0,
                        is_domain_required=True,
                    )
                )

    # Check violations
    violations = domain_dag.validate_against([(e.source, e.target) for e in directed])
    if violations:
        log.warning("PC found %d domain violations — flagged, not merged.", len(violations))
        for v in violations:
            for e in directed:
                if (e.source, e.target) == tuple(v["edge"]):
                    e.is_domain_forbidden = True
                    e.violation_hypothesis = v["hypothesis"]

    return DiscoveredDAG(
        algorithm="pc",
        edges=directed,
        undirected_edges=undirected,
        violations=violations,
        data_provenance_tag=data_provenance_tag,
        n_samples=n_samples,
        runtime_seconds=runtime,
        alpha=alpha,
        ci_test=ci_test,
    )


# ── NOTEARS Wrapper ──────────────────────────────────────────────────────────

def run_notears(
    df: pd.DataFrame,
    domain_dag: DomainDAG = DOMAIN_DAG,
    lambda1: float = 0.1,
    loss_type: str = "l2",
    data_provenance_tag: str = "[SYNTHETIC]",
    weight_threshold: float = 0.3,
) -> DiscoveredDAG:
    """
    Run NOTEARS on `df`.  GPU path (Phase 8) is enabled via cr2e.config settings.

    causal-learn ships a NOTEARS implementation in
    `causallearn.search.ScoreBased.notears`.
    """
    try:
        from causallearn.search.ScoreBased.notears import notears_linear
    except ImportError as exc:
        raise ImportError(
            "causal-learn required: pip install causal-learn"
        ) from exc

    cols = [c for c in KPI_NODES if c in df.columns]
    data = df[cols].dropna().values.astype(float)
    n_samples = len(data)

    log.info(
        "NOTEARS discovery: %d rows × %d cols, λ=%.3f, tag=%s",
        n_samples, len(cols), lambda1, data_provenance_tag,
    )

    t0 = time.perf_counter()
    W = notears_linear(data, lambda1=lambda1, loss_type=loss_type)
    runtime = time.perf_counter() - t0

    # Threshold weight matrix
    directed: list[DiscoveredEdge] = []
    n = len(cols)
    for i in range(n):
        for j in range(n):
            if abs(W[i, j]) > weight_threshold:
                directed.append(
                    DiscoveredEdge(
                        source=cols[i],
                        target=cols[j],
                        weight=float(W[i, j]),
                    )
                )

    # Apply domain constraints: remove forbidden, add required
    forb_set = {(e.source, e.target) for e in domain_dag.forbidden_edges}
    violations = domain_dag.validate_against([(e.source, e.target) for e in directed])
    directed = [e for e in directed if (e.source, e.target) not in forb_set]

    present = {(e.source, e.target) for e in directed}
    for de in domain_dag.required_edges:
        if de.source in cols and de.target in cols:
            if (de.source, de.target) not in present:
                directed.append(
                    DiscoveredEdge(
                        source=de.source,
                        target=de.target,
                        weight=0.5,
                        is_domain_required=True,
                    )
                )

    return DiscoveredDAG(
        algorithm="notears",
        edges=directed,
        undirected_edges=[],
        violations=violations,
        data_provenance_tag=data_provenance_tag,
        n_samples=n_samples,
        runtime_seconds=runtime,
        lambda1=lambda1 if False else lambda1,  # keep linter happy
    )


# ── Dispatch ─────────────────────────────────────────────────────────────────

def run_discovery(
    df: pd.DataFrame,
    algorithm: str = "pc",
    data_provenance_tag: str = "[SYNTHETIC]",
    **kwargs: Any,
) -> DiscoveredDAG:
    """
    Dispatch to the correct discovery algorithm.

    Parameters
    ----------
    df : pd.DataFrame
        KPI history (columns = KPI_NAMES, rows = time-ordered samples).
    algorithm : {"pc", "notears"}
    data_provenance_tag : str
        "[SYNTHETIC]" | "[REAL:testbed]" | "[REAL:injected-fault-ground-truth]"
    **kwargs
        Forwarded to the algorithm-specific function.
    """
    if algorithm == "pc":
        return run_pc(df, data_provenance_tag=data_provenance_tag, **kwargs)
    elif algorithm == "notears":
        return run_notears(df, data_provenance_tag=data_provenance_tag, **kwargs)
    else:
        raise ValueError(f"Unknown discovery algorithm: {algorithm!r}. Use 'pc' or 'notears'.")
