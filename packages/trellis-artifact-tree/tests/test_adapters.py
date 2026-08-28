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


class TestHtmlAdapter:
    """HTML states a hierarchy. Letting it fall through to the generic
    fallback would flatten a documentation site into blank-line blocks and
    discard structure the document actually declares."""

    HTML = (
        "<html><head><style>body{color:red}</style></head><body>"
        "<h1>Top</h1><p>intro text</p>"
        "<h2>Sub A</h2><p>a body</p>"
        "<h4>Deep</h4><p>deep body</p>"
        "<h2>Sub B</h2><p>b body</p>"
        "<script>var x=1;</script>"
        "</body></html>"
    )

    def _tree(self):
        from trellis_artifact_tree.adapters import HtmlAdapter

        return HtmlAdapter().parse("w", self.HTML, PROV)

    def test_headings_nest_by_level(self):
        t = self._tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["Sub A"].parent_id == by["Top"].node_id
        assert by["Sub B"].parent_id == by["Top"].node_id

    def test_level_skips_do_not_invent_nodes(self):
        t = self._tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["Deep"].parent_id == by["Sub A"].node_id

    def test_script_and_style_content_is_excluded(self):
        """Otherwise a packer pays tokens for CSS and JavaScript."""
        blob = " ".join(
            v for n in self._tree().nodes for v in n.rungs.values()
        )
        assert "color:red" not in blob and "var x" not in blob

    def test_body_text_attaches_to_the_open_section(self):
        t = self._tree()
        by = {n.title: n for n in t.nodes if n.title}
        body = next(n for n in t.nodes if "a body" in " ".join(n.rungs.values()))
        assert body.parent_id == by["Sub A"].node_id

    def test_registry_prefers_it_over_the_generic_fallback(self):
        for kind in ("html", ".HTM", "text/html", "web"):
            assert AdapterRegistry().resolve(kind).name == "html"

    def test_shares_one_containment_algorithm_with_pdf(self):
        """Three implementations of 'headings nest by level, and levels skip'
        would be three places to fix the same bug."""
        import inspect

        from trellis_artifact_tree.adapters import HtmlAdapter

        assert "tree_from_items" in inspect.getsource(HtmlAdapter.parse)


class TestHtmlSegmentation:
    """Found by running the adapter on real pages rather than by review.

    A 170KB Javadoc class index produced FOUR nodes, one of them a 27,229-char
    blob — parsed without error, and unusable for budgeting because a packer
    cannot cut it.
    """

    def _nodes(self, html):
        """Content nodes only — the root and heading nodes carry an IDENTIFIERS
        rung of their own, and counting them hides what is being measured."""
        from trellis_artifact_tree.adapters import HtmlAdapter
        from trellis_artifact_tree.model import Rung

        t = HtmlAdapter().parse("x", html, PROV)
        return [n for n in t.nodes if Rung.FULL in n.rungs]

    def test_list_items_become_their_own_nodes(self):
        nodes = self._nodes("<h1>T</h1><ul><li>alpha</li><li>beta</li><li>gamma</li></ul>")
        texts = [list(n.rungs.values())[0] for n in nodes]
        assert "alpha" in texts and "beta" in texts and "gamma" in texts

    def test_unclosed_tags_still_split(self):
        """Unclosed <li> and <p> are legal HTML and common in generated pages.
        Waiting for the end tag loses the boundary entirely."""
        nodes = self._nodes("<h1>T</h1><ul><li>alpha<li>beta<li>gamma</ul>")
        assert len(nodes) >= 3

    def test_table_rows_are_the_unit_not_cells(self):
        """A node per cell is finer than any packer needs and buries a table's
        shape in its contents."""
        nodes = self._nodes(
            "<h1>T</h1><table><tr><td>a1</td><td>a2</td></tr>"
            "<tr><td>b1</td><td>b2</td></tr></table>"
        )
        texts = [list(n.rungs.values())[0] for n in nodes]
        assert any("a1" in t and "a2" in t for t in texts), "cells should stay together"

    def test_a_runaway_run_is_capped(self):
        """The safety net for markup the tag set does not describe. Modern
        Javadoc renders its class index as nested <div>s, which no reasonable
        block-tag list covers."""
        from trellis_artifact_tree.adapters import HtmlAdapter

        blob = "<div>" + ("word " * 4000) + "</div>"
        nodes = self._nodes(f"<h1>T</h1>{blob}")
        assert len(nodes) > 2, "a single enormous run must be broken up"
        largest = max(len(list(n.rungs.values())[0]) for n in nodes)
        assert largest <= HtmlAdapter._MAX_RUN_CHARS + 200

    def test_the_cap_does_not_touch_well_formed_pages(self):
        """Adding `div` to the block set fixed the pathological page and ruined
        every other one: 755 nodes with a median of 32 characters. The cap is a
        limit, not the mechanism — ordinary pages must segment on tags alone."""
        html = "<h1>T</h1>" + "".join(f"<p>paragraph {i}</p>" for i in range(5))
        nodes = self._nodes(html)
        assert len(nodes) == 5
        assert all(len(list(n.rungs.values())[0]) < 60 for n in nodes)
