"""Model invariants for the containment tree.

Every failure checked here surfaces downstream as something much harder to
read -- a cut that silently omits a subtree, or a walk that does not
terminate -- which is why they are raised at construction.
"""
from __future__ import annotations

import pytest

from trellis_artifact_tree.model import (
    ArtifactTree,
    Node,
    Provenance,
    Rung,
    TreeError,
)

PROV = Provenance(source_kind="repo", source_id="amundsen", fetched_at="2026-08-27T00:00:00")


def tree(*nodes: Node) -> ArtifactTree:
    return ArtifactTree("a", PROV, tuple(nodes))


class TestValidation:
    def test_orphan_is_named_as_an_orphan(self):
        """Regression: the root-count check used to run first, so an orphan
        reported 'expected exactly one root, found 0' -- true, useless, and
        pointing at the wrong thing."""
        with pytest.raises(TreeError, match="missing parent"):
            tree(Node("x", "a", "section", parent_id="nope"))

    def test_cycle_is_named_as_a_cycle(self):
        """Same regression: a pure cycle has no root, so root-count-first
        reported the absence of a root rather than the cycle causing it."""
        with pytest.raises(TreeError, match="cycle"):
            tree(
                Node("c1", "a", "section", parent_id="c2"),
                Node("c2", "a", "section", parent_id="c1"),
            )

    def test_two_roots(self):
        with pytest.raises(TreeError, match="exactly one root"):
            tree(Node("r1", "a", "document"), Node("r2", "a", "document"))

    def test_duplicate_ids(self):
        with pytest.raises(TreeError, match="duplicate"):
            tree(Node("d", "a", "document"), Node("d", "a", "section"))

    def test_empty(self):
        with pytest.raises(TreeError, match="no nodes"):
            tree()

    def test_foreign_artifact(self):
        with pytest.raises(TreeError, match="other artifact"):
            tree(Node("r", "a", "document"), Node("s", "OTHER", "section", parent_id="r"))


class TestCut:
    def _doc(self) -> ArtifactTree:
        return tree(
            Node("r", "a", "document"),
            Node("s1", "a", "section", parent_id="r", ordinal=0),
            Node("s2", "a", "section", parent_id="r", ordinal=1),   # shallow leaf
            Node("s1a", "a", "para", parent_id="s1", ordinal=0),
        )

    def test_cut_at_depth(self):
        assert [n.node_id for n in self._doc().cut(1)] == ["s1", "s2"]

    def test_cut_includes_shallower_leaves(self):
        """s2 has no children, so a depth-2 cut must still carry it. Dropping
        it would silently lose content whose only fault is having no deeper
        structure -- a cut is a rung boundary, not a depth filter."""
        assert [n.node_id for n in self._doc().cut(2)] == ["s2", "s1a"]

    def test_cut_is_ordered_and_stable(self):
        ids = [n.node_id for n in self._doc().cut(1)]
        assert ids == sorted(ids)  # ordinal 0,1 -> s1,s2


class TestRungLadder:
    def test_ordering_is_increasing_compression(self):
        assert Rung.FULL < Rung.SUMMARY < Rung.IDENTIFIERS
        assert not Rung.FULL.is_lossy
        assert Rung.SUMMARY.is_lossy and Rung.IDENTIFIERS.is_lossy

    def test_returns_richest_that_still_fits(self):
        t = tree(
            Node("r", "a", "document"),
            Node("s", "a", "section", parent_id="r",
                 rungs={Rung.FULL: "full", Rung.SUMMARY: "sum"}),
        )
        assert t.best_rung("s", Rung.SUMMARY) == (Rung.SUMMARY, "sum")
        # budget allows FULL, and FULL exists -- take it
        assert t.best_rung("s", Rung.FULL) == (Rung.FULL, "full")

    def test_returns_none_when_nothing_is_compressed_enough(self):
        """The packer must decide to drop or descend. Silently handing back a
        richer rung than the budget allows defeats the hard ceiling, which
        every other guarantee rests on."""
        t = tree(
            Node("r", "a", "document"),
            Node("s", "a", "section", parent_id="r", rungs={Rung.FULL: "full"}),
        )
        assert t.best_rung("s", Rung.IDENTIFIERS) is None

    def test_coarser_than_budget_is_acceptable(self):
        """Only IDENTIFIERS exists but FULL was affordable: return what there
        is rather than nothing. Under-spending a budget is not a violation."""
        t = tree(
            Node("r", "a", "document"),
            Node("s", "a", "section", parent_id="r", rungs={Rung.IDENTIFIERS: "ids"}),
        )
        assert t.best_rung("s", Rung.FULL) == (Rung.IDENTIFIERS, "ids")


class TestProvenance:
    def test_fetched_at_and_source_timestamp_are_distinct_fields(self):
        """When the fact was true vs when we read it. Collapsing them loses the
        ability to tell an old fact from a stale read."""
        p = Provenance(
            source_kind="egeria", source_id="guid-1",
            fetched_at="2026-08-27T10:00:00", source_timestamp="2026-05-18T00:00:00",
            source_version="12",
        )
        assert p.fetched_at != p.source_timestamp

    def test_fidelity_defaults_to_structural_and_is_recordable(self):
        assert PROV.extraction_fidelity == "structural"
        degraded = Provenance(
            source_kind="pdf", source_id="x.pdf", fetched_at="t",
            extraction_fidelity="generic-text",
        )
        assert degraded.extraction_fidelity == "generic-text"
