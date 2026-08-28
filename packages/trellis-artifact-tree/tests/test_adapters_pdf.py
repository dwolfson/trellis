"""PDF mapping. No Docling, no PDF, no model download -- the conversion is
isolated in _convert() precisely so the mapping can be tested on its own.
"""
from __future__ import annotations

from trellis_artifact_tree.adapters_pdf import DocItem, PdfAdapter, tree_from_items
from trellis_artifact_tree.model import Provenance, Rung

PROV = Provenance(source_kind="doc", source_id="paper.pdf", fetched_at="t")

ITEMS = [
    DocItem("page_header", "running head"),
    DocItem("title", "A Paper"),
    DocItem("text", "abstract prose"),
    DocItem("section_header", "Method", level=1),
    DocItem("text", "we did things"),
    DocItem("section_header", "Detail", level=3),
    DocItem("text", "deeply"),
    DocItem("section_header", "Results", level=1),
    DocItem("table", "| a | b |"),
    DocItem("picture", ""),
]


def _tree():
    return tree_from_items("z", ITEMS, PROV, "inferred")


class TestStructure:
    def test_title_is_the_outermost_heading(self):
        t = _tree()
        title = next(n for n in t.nodes if n.title == "A Paper")
        assert title.parent_id == t.root.node_id

    def test_sections_nest_under_the_title(self):
        t = _tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["Method"].parent_id == by["A Paper"].node_id
        assert by["Results"].parent_id == by["A Paper"].node_id

    def test_level_skips_do_not_invent_nodes(self):
        """level 3 directly under level 1 becomes its child, as in markdown."""
        t = _tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["Detail"].parent_id == by["Method"].node_id

    def test_a_shallower_heading_closes_deeper_ones(self):
        t = _tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["Results"].parent_id != by["Detail"].node_id

    def test_content_attaches_to_the_open_section(self):
        t = _tree()
        by = {n.title: n for n in t.nodes if n.title}
        table = next(n for n in t.nodes if n.kind == "table")
        assert table.parent_id == by["Results"].node_id


class TestFiltering:
    def test_page_furniture_is_dropped(self):
        """A running header repeated on ninety pages is noise a packer would
        otherwise pay for ninety times."""
        assert not any("running head" in (n.rungs.get(Rung.FULL) or "") for n in _tree().nodes)

    def test_empty_items_are_dropped(self):
        assert not any(n.kind == "picture" for n in _tree().nodes)


class TestRungs:
    def test_sections_carry_identifiers_and_blocks_carry_full(self):
        """Giving sections a FULL rung too would store every byte twice. A
        packer wanting the whole section descends instead."""
        t = _tree()
        section = next(n for n in t.nodes if n.title == "Method")
        block = next(n for n in t.nodes if n.rungs.get(Rung.FULL) == "we did things")
        assert Rung.FULL not in section.rungs
        assert section.rungs[Rung.IDENTIFIERS] == "Method"
        assert Rung.IDENTIFIERS not in block.rungs


class TestContract:
    def test_fidelity_is_inferred_not_structural(self):
        """A PDF states layout, not structure. A reader deserves to know the
        hierarchy was reconstructed."""
        assert _tree().provenance.extraction_fidelity == "inferred"
        assert PdfAdapter().fidelity == "inferred"

    def test_handles(self):
        a = PdfAdapter()
        assert a.handles("pdf") and a.handles(".PDF") and a.handles("application/pdf")
        assert not a.handles("py")

    def test_non_path_fails_loudly(self):
        import pytest

        with pytest.raises(TypeError):
            PdfAdapter().parse("z", b"%PDF-1.4", PROV)

    def test_no_items_still_yields_a_valid_tree(self):
        t = tree_from_items("z", [], PROV)
        assert len(t.nodes) == 1


class FakeItem:
    def __init__(self, label, text, level=1):
        self.label = type("L", (), {"value": label})()
        self.text = text
        self.level = level


class FakeDoc:
    def __init__(self, items): self._items = items
    def iterate_items(self): return [(i, 0) for i in self._items]


class TestSharedConversion:
    """Conversion is the expensive step. A caller that already paid for it --
    RE converts each PDF once and feeds both its chunker and this builder --
    must not pay again."""

    def test_items_from_docling_needs_no_docling(self):
        from trellis_artifact_tree.adapters_pdf import items_from_docling

        items = items_from_docling(FakeDoc([
            FakeItem("title", "T"), FakeItem("section_header", "S", 2),
            FakeItem("text", "body"),
        ]))
        assert [(i.label, i.text, i.level) for i in items] == [
            ("title", "T", 1), ("section_header", "S", 2), ("text", "body", 1),
        ]

    def test_document_adapter_maps_without_converting(self):
        from trellis_artifact_tree.adapters_pdf import DoclingDocumentAdapter

        doc = FakeDoc([FakeItem("title", "T"), FakeItem("text", "body")])
        t = DoclingDocumentAdapter().parse("z", doc, PROV)
        assert [n.title for n in t.nodes if n.title] == ["paper.pdf", "T"]
        assert t.provenance.extraction_fidelity == "inferred"

    def test_document_adapter_rejects_a_path(self):
        import pytest

        from trellis_artifact_tree.adapters_pdf import DoclingDocumentAdapter

        with pytest.raises(TypeError, match="use PdfAdapter for a path"):
            DoclingDocumentAdapter().parse("z", "/tmp/x.pdf", PROV)
