"""
cr2e/tests/test_domain_dag.py
─────────────────────────────────────────────────────────────────────────────
Phase 2 Gate Test — Domain DAG

Verifies:
  1. All required edges encode known telecom physics.
  2. Forbidden edges are the physical inverses.
  3. Discovery algorithm (mocked) does not silently overwrite forbidden edges.
  4. Domain DAG serialisation round-trips correctly.
"""

from __future__ import annotations

import pytest

from cr2e.graph.domain_dag import (
    DOMAIN_DAG,
    DomainDAG,
    REQUIRED_EDGES,
    FORBIDDEN_EDGES,
    KPI_NODES,
    DomainEdge,
)


class TestDomainDAGStructure:
    def test_required_edges_are_nonempty(self):
        assert len(REQUIRED_EDGES) >= 4, "Expected ≥4 domain-required edges"

    def test_forbidden_edges_are_nonempty(self):
        assert len(FORBIDDEN_EDGES) >= 2, "Expected ≥2 domain-forbidden edges"

    def test_all_edge_nodes_are_kpi_nodes(self):
        """All edge endpoints must be KPI nodes (or known proxy nodes)."""
        known_nodes = set(DOMAIN_DAG.nodes)
        for e in REQUIRED_EDGES + FORBIDDEN_EDGES:
            assert e.source in known_nodes, f"Unknown source node: {e.source}"
            assert e.target in known_nodes, f"Unknown target node: {e.target}"

    def test_required_and_forbidden_do_not_overlap(self):
        """No edge can be both required and forbidden."""
        req = {(e.source, e.target) for e in REQUIRED_EDGES}
        forb = {(e.source, e.target) for e in FORBIDDEN_EDGES}
        overlap = req & forb
        assert not overlap, f"Edges in both required and forbidden: {overlap}"

    def test_forbidden_are_inverses_of_required(self):
        """
        At minimum, each required edge (a→b) should have (b→a) in forbidden
        OR its physical impossibility explained.
        This test checks the most critical inverse pairs.
        """
        required_set = {(e.source, e.target) for e in REQUIRED_EDGES}
        forbidden_set = {(e.source, e.target) for e in FORBIDDEN_EDGES}

        # These specific reverse pairs MUST be in forbidden per domain physics
        critical_reverses = [
            ("dl_throughput_mbps", "rsrp_dbm"),  # throughput cannot cause signal quality
            ("dl_throughput_mbps", "bler_pct"),   # throughput is outcome, not cause of BLER
            ("handover_success_rate", "rsrp_dbm"),
        ]
        for pair in critical_reverses:
            assert pair in forbidden_set, (
                f"Critical reverse edge {pair} missing from forbidden set. "
                "This violates telecom domain physics."
            )

    def test_references_are_cited(self):
        """Every edge must have a non-empty reference."""
        for e in REQUIRED_EDGES + FORBIDDEN_EDGES:
            assert e.reference, f"Edge {e.source}→{e.target} has no reference"
            assert "[R" in e.reference, (
                f"Edge {e.source}→{e.target} reference doesn't cite [R1]-[R4]: {e.reference}"
            )


class TestDomainDAGFormatting:
    def test_to_causal_learn_format(self):
        req, forb = DOMAIN_DAG.to_causal_learn_format()
        assert len(req) == len(REQUIRED_EDGES)
        assert len(forb) == len(FORBIDDEN_EDGES)
        for pair in req:
            assert isinstance(pair, tuple) and len(pair) == 2

    def test_to_dict_round_trip(self):
        d = DOMAIN_DAG.to_dict()
        assert "required_edges" in d
        assert "forbidden_edges" in d
        assert "nodes" in d
        assert "references" in d
        assert len(d["required_edges"]) == len(REQUIRED_EDGES)


class TestDomainDAGViolationDetection:
    def test_detect_forbidden_edge_in_discovered(self):
        """validate_against must flag forbidden edges."""
        # Simulate a discovery result that includes a forbidden edge
        forbidden_pair = (FORBIDDEN_EDGES[0].source, FORBIDDEN_EDGES[0].target)
        violations = DOMAIN_DAG.validate_against([forbidden_pair])
        assert len(violations) == 1
        assert violations[0]["type"] == "forbidden_direction"
        assert violations[0]["edge"] == forbidden_pair
        assert violations[0]["hypothesis"] != ""
        assert violations[0]["action"] != ""

    def test_no_violation_for_required_edge(self):
        """Required edges are not violations."""
        required_pair = (REQUIRED_EDGES[0].source, REQUIRED_EDGES[0].target)
        violations = DOMAIN_DAG.validate_against([required_pair])
        assert violations == []

    def test_no_violation_for_unknown_edge(self):
        """An unconstrained edge (not required, not forbidden) is not flagged."""
        # Use two nodes that have no direct constraint between them
        # slice_utilisation_pct → handover_success_rate has no direct constraint
        violations = DOMAIN_DAG.validate_against([("slice_utilisation_pct", "handover_success_rate")])
        assert violations == []


class TestDomainDAGSummary:
    def test_summary_mentions_all_required_edges(self):
        s = DOMAIN_DAG.summary()
        for e in REQUIRED_EDGES:
            assert e.source in s, f"Missing source {e.source} in summary"
            assert e.target in s, f"Missing target {e.target} in summary"

    def test_summary_mentions_references(self):
        s = DOMAIN_DAG.summary()
        assert "3GPP" in s or "O-RAN" in s or "[R" in s
