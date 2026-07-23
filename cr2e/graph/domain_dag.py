"""
cr2e/graph/domain_dag.py
─────────────────────────────────────────────────────────────────────────────
Phase 2 — Telecom Domain-Constrained Partial DAG

Encodes directional edges that are physically/protocolically fixed so that
the causal-discovery algorithm cannot contradict them. Each edge carries:
  - direction: fixed (required edge) or forbidden (anti-edge)
  - rationale: one-line causal mechanism
  - reference: DOI or standard section from which the constraint is derived

References used (Phase 2 gate: ≥2 domain references cited per constraint set):

  [R1] 3GPP TS 38.300 v17.3.0 — NR; NR and NG-RAN Overall Description.
       Section 16.10 (Radio Resource Management), §16.10.3 (RSRP measurement
       and handover threshold). Establishes RSRP as input to HO decisions
       and BLER as outcome of channel quality.

  [R2] 3GPP TS 38.214 v17.3.0 — NR; Physical layer procedures for data.
       Section 5.2 (Link adaptation): BLER drives CQI/MCS selection, which
       determines achievable DL throughput for a given PRB allocation.

  [R3] O-RAN WG2 — Near-RT RIC Architecture v03.00 (2022).
       Section 7.2: xApps observe E2 KPM counters including per-slice PRB
       allocation and latency; backhaul link latency affects E2E UE latency.

  [R4] Papadimitriou, P. et al. "A Survey on Mobile Network Traffic
       Modelling." IEEE Communications Surveys & Tutorials, 2021.
       DOI: 10.1109/COMST.2021.3070124 — establishes that UE arrival rate
       (traffic load) causes queue buildup, increasing latency before
       throughput degrades.

Anti-fabrication note:
  All edges in REQUIRED_EDGES are "directionally known" per the references
  above. They are NOT asserted to be the ONLY causal paths; they constrain
  the discovery algorithm from inverting physically impossible directions.
  Discovered edges (Phase 3) may add further paths.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

log = logging.getLogger("cr2e.graph.domain_dag")

# ── KPI node names (must match xapp/ingestion/kpi_schema.py KPI_NAMES) ──────

KPI_NODES: list[str] = [
    "dl_throughput_mbps",
    "latency_ms",
    "bler_pct",
    "rsrp_dbm",
    "handover_success_rate",
    "slice_utilisation_pct",
]

# Latent / proxy nodes that appear in the DAG but are not directly measured
PROXY_NODES: list[str] = [
    "backhaul_congestion",  # unmeasured confounder — see WHAT_WE_DIDNT_SOLVE §1
    "cross_cell_interference",  # unmeasured confounder — see WHAT_WE_DIDNT_SOLVE §3
]


@dataclass(frozen=True)
class DomainEdge:
    """One domain-constrained edge in the causal DAG."""

    source: str
    target: str
    direction: Literal["required", "forbidden"]
    rationale: str
    reference: str  # e.g. "[R2] 3GPP TS 38.214 §5.2"
    confidence: Literal["high", "medium"] = "high"


# ── Required edges (physically/protocolically fixed direction) ─────────────
#
# For required edges: (source, target) is the forced causal direction.
# The discovery algorithm must not invert these.

REQUIRED_EDGES: list[DomainEdge] = [
    DomainEdge(
        source="rsrp_dbm",
        target="bler_pct",
        direction="required",
        rationale=(
            "Weaker received power → higher channel-error probability → "
            "higher block-error rate. RSRP is a signal-quality input; "
            "BLER is a link-quality output. Direction cannot be reversed."
        ),
        reference="[R1] 3GPP TS 38.300 §16.10.3",
    ),
    DomainEdge(
        source="bler_pct",
        target="dl_throughput_mbps",
        direction="required",
        rationale=(
            "Higher BLER forces lower MCS (modulation-coding scheme) via "
            "link adaptation, reducing achievable DL throughput. "
            "Throughput cannot cause BLER at the link layer."
        ),
        reference="[R2] 3GPP TS 38.214 §5.2",
    ),
    DomainEdge(
        source="slice_utilisation_pct",
        target="latency_ms",
        direction="required",
        rationale=(
            "Higher slice utilisation → greater queuing delay (M/M/1 model: "
            "Lq = ρ²/(1−ρ) increases super-linearly near saturation). "
            "Latency is a consequence of load, not its cause in steady state."
        ),
        reference="[R3] O-RAN WG2 §7.2; [R4] Papadimitriou 2021 §IV-A",
    ),
    DomainEdge(
        source="slice_utilisation_pct",
        target="dl_throughput_mbps",
        direction="required",
        rationale=(
            "PRB saturation caps the achievable throughput per UE; "
            "slice_utilisation_pct is the proxy for PRB load (see "
            "WHAT_WE_DIDNT_SOLVE §2). Direction is load → capacity-limited throughput."
        ),
        reference="[R3] O-RAN WG2 §7.2; [R2] 3GPP TS 38.214 §5.2",
        confidence="medium",  # medium because proxy, not direct PRB measure
    ),
    DomainEdge(
        source="rsrp_dbm",
        target="handover_success_rate",
        direction="required",
        rationale=(
            "RSRP is the primary trigger metric for handover decisions "
            "(A3/A5 event thresholds). Weaker RSRP increases HO failure "
            "probability. HO outcomes feed back to UE context, not to RSRP."
        ),
        reference="[R1] 3GPP TS 38.300 §16.10.3",
    ),
    DomainEdge(
        source="latency_ms",
        target="dl_throughput_mbps",
        direction="required",
        rationale=(
            "TCP throughput is inversely proportional to RTT "
            "(Mathis equation: BW ≈ MSS / (RTT × √loss)). "
            "High latency degrades TCP-layer throughput. "
            "Note: in QUIC/UDP this is weaker — medium confidence."
        ),
        reference="[R4] Papadimitriou 2021 §III-B",
        confidence="medium",
    ),
]

# ── Forbidden edges (physically impossible directions) ─────────────────────
#
# For forbidden edges: (source, target) is explicitly disallowed.
# These prevent the discovery algorithm from finding spurious reverse paths.

FORBIDDEN_EDGES: list[DomainEdge] = [
    DomainEdge(
        source="dl_throughput_mbps",
        target="rsrp_dbm",
        direction="forbidden",
        rationale="Throughput is an outcome of RSRP, not a physical cause of signal quality.",
        reference="[R1] 3GPP TS 38.300 §16.10.3",
    ),
    DomainEdge(
        source="dl_throughput_mbps",
        target="bler_pct",
        direction="forbidden",
        rationale="BLER is determined by channel quality and MCS, not by throughput level.",
        reference="[R2] 3GPP TS 38.214 §5.2",
    ),
    DomainEdge(
        source="handover_success_rate",
        target="rsrp_dbm",
        direction="forbidden",
        rationale="HO success is a consequence of RSRP; it cannot raise or lower signal power.",
        reference="[R1] 3GPP TS 38.300 §16.10.3",
    ),
    DomainEdge(
        source="latency_ms",
        target="slice_utilisation_pct",
        direction="forbidden",
        rationale=(
            "In the causal order, load (utilisation) causes latency. "
            "Latency feeds back to TCP sender rate (application layer) "
            "but does not directly modify slice resource accounting."
        ),
        reference="[R3] O-RAN WG2 §7.2",
    ),
]


@dataclass
class DomainDAG:
    """
    Complete domain-constrained partial DAG for the ASTRA KPI space.

    Pass to causal-learn as forbidden_edges / required_edges to prevent
    the PC/NOTEARS algorithm from violating known telecom physics.
    """

    nodes: list[str] = field(default_factory=lambda: KPI_NODES + PROXY_NODES)
    required_edges: list[DomainEdge] = field(default_factory=lambda: list(REQUIRED_EDGES))
    forbidden_edges: list[DomainEdge] = field(default_factory=lambda: list(FORBIDDEN_EDGES))

    # Metadata for gate document
    references: list[str] = field(
        default_factory=lambda: [
            "[R1] 3GPP TS 38.300 v17.3.0 §16.10.3",
            "[R2] 3GPP TS 38.214 v17.3.0 §5.2",
            "[R3] O-RAN WG2 Near-RT RIC Architecture v03.00 §7.2",
            "[R4] Papadimitriou et al. IEEE COMST 2021 DOI:10.1109/COMST.2021.3070124",
        ]
    )

    def to_causal_learn_format(
        self,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """
        Return (required_edge_pairs, forbidden_edge_pairs) as (source, target) tuples.
        Use these with causal-learn PC's ``background_knowledge`` parameter.
        """
        req = [(e.source, e.target) for e in self.required_edges]
        forb = [(e.source, e.target) for e in self.forbidden_edges]
        return req, forb

    def to_dict(self) -> dict:
        """Serializable representation for dag_store."""
        return {
            "nodes": self.nodes,
            "required_edges": [asdict(e) for e in self.required_edges],
            "forbidden_edges": [asdict(e) for e in self.forbidden_edges],
            "references": self.references,
        }

    def save(self, path: str | Path) -> None:
        """Persist domain DAG to JSON (idempotent)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        log.info("Domain DAG saved to %s", p)

    @classmethod
    def load(cls, path: str | Path) -> "DomainDAG":
        """Load domain DAG from JSON."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        dag = cls(nodes=data["nodes"])
        dag.required_edges = [DomainEdge(**e) for e in data["required_edges"]]
        dag.forbidden_edges = [DomainEdge(**e) for e in data["forbidden_edges"]]
        dag.references = data.get("references", [])
        return dag

    def validate_against(self, discovered_edge_pairs: list[tuple[str, str]]) -> list[dict]:
        """
        Check a list of discovered (source, target) edges against forbidden constraints.
        Returns a list of violation dicts — each violation gets a hypothesis (Phase 3 gate).
        """
        violations = []
        forbidden_set = {(e.source, e.target) for e in self.forbidden_edges}
        for src, tgt in discovered_edge_pairs:
            if (src, tgt) in forbidden_set:
                violations.append(
                    {
                        "edge": (src, tgt),
                        "type": "forbidden_direction",
                        "hypothesis": (
                            f"Discovery found {src}→{tgt} which contradicts domain physics. "
                            "Possible causes: (a) confounding by unmeasured variable, "
                            "(b) feedback loop in time-aggregated data, "
                            "(c) insufficient sample size for faithful orientation."
                        ),
                        "action": "FLAG — edge rejected; domain constraint takes precedence.",
                    }
                )
        return violations

    def summary(self) -> str:
        """Human-readable summary for gate documents."""
        lines = [
            f"Domain DAG: {len(self.nodes)} nodes, "
            f"{len(self.required_edges)} required edges, "
            f"{len(self.forbidden_edges)} forbidden edges.",
            "",
            "Required edges (fixed direction):",
        ]
        for e in self.required_edges:
            lines.append(f"  {e.source} → {e.target}  [{e.confidence}]  {e.reference}")
        lines.append("\nForbidden edges (disallowed direction):")
        for e in self.forbidden_edges:
            lines.append(f"  {e.source} → {e.target}  {e.reference}")
        lines.append("\nReferences:")
        for r in self.references:
            lines.append(f"  {r}")
        return "\n".join(lines)


# Module-level singleton — import and use directly
DOMAIN_DAG = DomainDAG()
