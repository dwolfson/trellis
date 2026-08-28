"""Adapter contract, nesting, and the degrade-never-block guarantee."""
from __future__ import annotations

from trellis_artifact_tree.adapters import (
    Adapter,
    AdapterRegistry,
    GenericTextAdapter,
    MarkdownAdapter,
)
from trellis_artifact_tree.model import Provenance, Rung

PROV = Provenance(source_kind="repo", source_id="README.md", fetched_at="2026-08-27T00:00:00")

DOC = """intro para

# Top
top body

## Sub A
a body

#### Deep
deep body

## Sub B
b body
"""


class TestMarkdownNesting:
    def _tree(self):
        return MarkdownAdapter().parse("a", DOC, PROV)

    def test_levels_not_document_order_define_nesting(self):
        t = self._tree()
        by_title = {n.title: n for n in t.nodes if n.title}
        assert by_title["Sub A"].parent_id == by_title["Top"].node_id
        assert by_title["Sub B"].parent_id == by_title["Top"].node_id

    def test_skipped_levels_do_not_invent_intermediate_nodes(self):
        """`####` directly under `##` becomes its child. Synthesising an
        intervening `###` would put a node in the tree the author never wrote."""
        t = self._tree()
        by_title = {n.title: n for n in t.nodes if n.title}
        assert by_title["Deep"].parent_id == by_title["Sub A"].node_id
        assert not any(n.title == "" and n.kind == "section" for n in t.nodes)

    def test_a_deeper_heading_closes_when_a_shallower_one_opens(self):
        """Sub B follows Deep in document order but is a sibling of Sub A, not
        a child of Deep."""
        t = self._tree()
        by_title = {n.title: n for n in t.nodes if n.title}
        assert by_title["Sub B"].parent_id != by_title["Deep"].node_id

    def test_preamble_is_kept(self):
        """Content before the first heading is usually the abstract. Dropping
        it is the classic markdown-parsing bug."""
        t = self._tree()
        pre = [n for n in t.nodes if n.kind == "preamble"]
        assert len(pre) == 1
        assert "intro para" in pre[0].rungs[Rung.FULL]

    def test_preamble_and_first_heading_have_distinct_ordinals(self):
        """Regression: both claimed ordinal 0 under the root, leaving sibling
        order to a node_id tiebreak rather than the document."""
        t = self._tree()
        root_kids = [n for n in t.nodes if n.parent_id == t.root.node_id]
        ordinals = [n.ordinal for n in root_kids]
        assert len(ordinals) == len(set(ordinals))
        assert [n.kind for n in t.children(t.root.node_id)] == ["preamble", "section"]

    def test_free_rungs_only(self):
        """FULL from the span and IDENTIFIERS from the title cost nothing.
        SUMMARY needs a summariser and is not an adapter's job."""
        t = self._tree()
        section = next(n for n in t.nodes if n.title == "Top")
        assert Rung.FULL in section.rungs and Rung.IDENTIFIERS in section.rungs
        assert Rung.SUMMARY not in section.rungs

    def test_fidelity_is_structural(self):
        assert self._tree().provenance.extraction_fidelity == "structural"


class TestGenericFallback:
    def test_flat_not_fabricated_hierarchy(self):
        """A flat tree honestly says 'structure was not recovered'. An invented
        hierarchy would not."""
        t = GenericTextAdapter().parse("b", "one\n\ntwo\n\nthree", PROV)
        assert [n.kind for n in t.nodes] == ["document", "block", "block", "block"]
        assert all(n.parent_id == t.root.node_id for n in t.nodes[1:])

    def test_fidelity_records_the_fallback(self):
        t = GenericTextAdapter().parse("b", "x", PROV)
        assert t.provenance.extraction_fidelity == "generic-text"

    def test_empty_input_still_yields_a_valid_tree(self):
        t = GenericTextAdapter().parse("b", "", PROV)
        assert t.root and len(t.nodes) == 1


class TestRegistry:
    def test_unknown_kind_degrades_rather_than_raising(self):
        t = AdapterRegistry().parse("c", "application/pdf", "a\n\nb", PROV)
        assert t.provenance.extraction_fidelity == "generic-text"

    def test_known_kind_uses_the_structural_adapter(self):
        for kind in ("md", "markdown", "text/markdown", ".MD"):
            assert AdapterRegistry().resolve(kind).name == "markdown"

    def test_resolve_never_returns_none(self):
        assert AdapterRegistry().resolve("something-nobody-wrote-yet") is not None

    def test_later_registration_wins(self):
        """An app registering a richer markdown adapter should not have to
        unregister the built-in first."""

        class Fancy:
            name, fidelity = "fancy-md", "structural"

            def handles(self, kind: str) -> bool:
                return kind == "md"

            def parse(self, artifact_id, text, provenance):
                return MarkdownAdapter().parse(artifact_id, text, provenance)

        reg = AdapterRegistry()
        reg.register(Fancy())
        assert reg.resolve("md").name == "fancy-md"

    def test_builtins_satisfy_the_protocol(self):
        assert isinstance(MarkdownAdapter(), Adapter)
        assert isinstance(GenericTextAdapter(), Adapter)
