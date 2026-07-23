"""
cr2e/graph/dag_diff.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — DAG Diff: Domain vs. Discovered

Computes the structural diff between the domain-constrained DAG (Phase 2)
and the PC/NOTEARS-discovered DAG (Phase 3).

Output is a DagDiff object that can be serialised into PHASE_3_GATE.md.
Every disagreement gets a one-line hypothesis — no silent merges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cr2e.graph.domain_dag import DomainDAG, DomainEdge, DOMAIN_DAG
from cr2e.graph.discovery import DiscoveredDAG, DiscoveredEdge


@dataclass
class EdgeDiff:
    """One line in the diff between domain and discovered DAGs."""

    edge: tuple[str, str]
    status: str  # "AGREED" | "DOMAIN_ONLY" | "DISCOVERY_ONLY" | "DIRECTION_REVERSED" | "VIOLATION"
    domain_edge: Optional[DomainEdge] = None
    discovered_edge: Optional[DiscoveredEdge] = None
    hypothesis: str = ""
    action: str = ""  # "accept" | "flag" | "reject"


@dataclass
class DagDiff:
    """
    Full diff between domain DAG and discovered DAG.

    Attributes
    ----------
    agreed : list[EdgeDiff]
        Edges present in both with the same direction.
    domain_only : list[EdgeDiff]
        Required domain edges absent from discovery (may indicate low power).
    discovery_only : list[EdgeDiff]
        Edges found by discovery not in domain constraints (novel associations).
    reversed_edges : list[EdgeDiff]
        Discovery found the opposite direction of a domain-required edge (serious violation).
    violations : list[EdgeDiff]
        Discovery found a domain-forbidden edge direction (physical impossibility).
    data_provenance_tag : str
        Inherited from the DiscoveredDAG.
    """

    agreed: list[EdgeDiff] = field(default_factory=list)
    domain_only: list[EdgeDiff] = field(default_factory=list)
    discovery_only: list[EdgeDiff] = field(default_factory=list)
    reversed_edges: list[EdgeDiff] = field(default_factory=list)
    violations: list[EdgeDiff] = field(default_factory=list)
    data_provenance_tag: str = "[SYNTHETIC]"

    @property
    def has_critical_violations(self) -> bool:
        return len(self.violations) > 0 or len(self.reversed_edges) > 0

    def to_gate_markdown(self) -> str:
        """Render as PHASE_3_GATE.md content."""
        lines = [
            "## DAG Diff — Domain vs. Discovered",
            "",
            f"**Data provenance:** {self.data_provenance_tag}",
            f"**Agreed edges:** {len(self.agreed)}  |  "
            f"**Domain-only:** {len(self.domain_only)}  |  "
            f"**Discovery-only:** {len(self.discovery_only)}  |  "
            f"**Reversed:** {len(self.reversed_edges)}  |  "
            f"**Violations:** {len(self.violations)}",
            "",
        ]

        def _section(title: str, diffs: list[EdgeDiff]) -> None:
            if not diffs:
                return
            lines.append(f"### {title}")
            lines.append("")
            for d in diffs:
                src, tgt = d.edge
                lines.append(f"- **{src} → {tgt}** [{d.status}]")
                if d.hypothesis:
                    lines.append(f"  - *Hypothesis:* {d.hypothesis}")
                if d.action:
                    lines.append(f"  - *Action:* {d.action}")
            lines.append("")

        _section("✅ Agreed (domain + discovery)", self.agreed)
        _section("🔵 Domain-constrained only (not in discovery)", self.domain_only)
        _section("🟡 Discovery-only (novel, no domain prior)", self.discovery_only)
        _section("🔴 Direction reversed (serious violation)", self.reversed_edges)
        _section("⛔ Domain-forbidden edge found (physical impossibility)", self.violations)

        if not self.has_critical_violations:
            lines.append("**Gate status: PASSED** — no critical violations.")
        else:
            lines.append(
                "**Gate status: CONDITIONAL PASS** — critical violations flagged above. "
                "Domain constraints take precedence; flagged edges excluded from estimation."
            )
        return "\n".join(lines)


def compute_dag_diff(
    domain_dag: DomainDAG,
    discovered: DiscoveredDAG,
) -> DagDiff:
    """
    Compute the structural diff between `domain_dag` and `discovered`.

    Parameters
    ----------
    domain_dag : DomainDAG
    discovered : DiscoveredDAG

    Returns
    -------
    DagDiff
    """
    diff = DagDiff(data_provenance_tag=discovered.data_provenance_tag)

    domain_req = {(e.source, e.target): e for e in domain_dag.required_edges}
    domain_forb = {(e.source, e.target) for e in domain_dag.forbidden_edges}
    disc_directed = {(e.source, e.target): e for e in discovered.edges}

    # Agreed + domain-only
    for (src, tgt), de in domain_req.items():
        if (src, tgt) in disc_directed:
            diff.agreed.append(
                EdgeDiff(
                    edge=(src, tgt),
                    status="AGREED",
                    domain_edge=de,
                    discovered_edge=disc_directed[(src, tgt)],
                    action="accept",
                )
            )
        elif (tgt, src) in disc_directed:
            diff.reversed_edges.append(
                EdgeDiff(
                    edge=(src, tgt),
                    status="DIRECTION_REVERSED",
                    domain_edge=de,
                    discovered_edge=disc_directed[(tgt, src)],
                    hypothesis=(
                        f"Discovery returned {tgt}→{src}, but domain requires {src}→{tgt}. "
                        "Possible explanations: feedback loop in aggregated data, "
                        "reverse causation at a different time scale, or confounding. "
                        "Domain constraint takes precedence."
                    ),
                    action="flag — domain direction enforced",
                )
            )
        else:
            diff.domain_only.append(
                EdgeDiff(
                    edge=(src, tgt),
                    status="DOMAIN_ONLY",
                    domain_edge=de,
                    hypothesis=(
                        f"Required edge {src}→{tgt} not found by discovery. "
                        "Possible causes: insufficient sample size, collinearity, "
                        "or weak effect in current dataset. Edge added from domain prior."
                    ),
                    action="accept (domain override)",
                )
            )

    # Discovery-only (not in domain_req and not forbidden)
    for (src, tgt), disc_e in disc_directed.items():
        if (src, tgt) in domain_req:
            continue
        if (src, tgt) in domain_forb:
            diff.violations.append(
                EdgeDiff(
                    edge=(src, tgt),
                    status="VIOLATION",
                    discovered_edge=disc_e,
                    hypothesis=(
                        f"Discovery found forbidden edge {src}→{tgt}. "
                        "This direction is physically impossible per domain constraints. "
                        "Most likely a spurious correlation or unmeasured confounder."
                    ),
                    action="reject — forbidden by domain",
                )
            )
        else:
            # Novel edge — not constrained either way
            diff.discovery_only.append(
                EdgeDiff(
                    edge=(src, tgt),
                    status="DISCOVERY_ONLY",
                    discovered_edge=disc_e,
                    hypothesis=(
                        f"Novel discovered edge {src}→{tgt} not in domain priors. "
                        "Accepted if it passes refutation (Phase 4); "
                        "flagged if confidence interval contains zero."
                    ),
                    action="tentatively accept — subject to refutation",
                )
            )

    return diff
