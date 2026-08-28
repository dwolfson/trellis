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


class TestOcrIsAChoice:
    """OCR is off by default because Docling's DEFAULT ENGINE is broken here,
    not because OCR is unwanted. Tables and headings extract without it; text
    that exists only as pixels does not.
    """

    def test_off_by_default(self):
        a = PdfAdapter()
        assert a.ocr is False
        assert a.ocr_engine == "easyocr", "the default engine must not be rapidocr"

    def test_table_extraction_does_not_depend_on_ocr(self):
        """do_table_structure is a separate Docling stage. Conflating them
        would mean turning OCR on just to read a table."""
        import inspect

        src = inspect.getsource(PdfAdapter._convert)
        assert "do_table_structure = True" in src

    def test_unknown_engine_is_named(self):
        import pytest

        with pytest.raises(ValueError, match="unknown OCR engine"):
            PdfAdapter(ocr=True, ocr_engine="nope")._ocr_options()

    def test_missing_engine_says_which_package_and_why_not_rapidocr(self):
        """The failure a user actually hits: OCR requested, engine not
        installed. An ImportError from three libraries down would not say
        which package, and would not warn that the obvious choice is the
        broken one."""
        import importlib.util

        import pytest

        if importlib.util.find_spec("easyocr") is not None:
            pytest.skip("easyocr installed; this covers the not-installed path")
        with pytest.raises(ImportError) as exc:
            PdfAdapter(ocr=True, ocr_engine="easyocr")._ocr_options()
        assert "easyocr" in str(exc.value)
        assert "rapidocr" in str(exc.value), "must warn the default engine is unusable"

    def test_engines_cover_the_portable_and_mac_paths(self):
        assert {"easyocr", "ocrmac"} <= set(PdfAdapter._ENGINES)


class TestDiagnostics:
    """A conversion can succeed, produce a valid tree, and say nothing useful.
    From the outside that looks identical to a short document."""

    def _tree(self, nodes, fidelity="inferred"):
        """Defaults to a PDF's fidelity: these diagnostics exist for sources
        where sparse text may mean a FAILED extraction rather than a short
        document."""
        from dataclasses import replace

        from trellis_artifact_tree.model import ArtifactTree
        return ArtifactTree(
            "a", replace(PROV, extraction_fidelity=fidelity), tuple(nodes)
        )

    def test_a_rasterised_page_is_flagged(self):
        from trellis_artifact_tree.model import Node
        from trellis_artifact_tree.diagnostics import diagnose

        t = self._tree([Node("r", "a", "document"),
                        Node("s", "a", "text", parent_id="r",
                             rungs={Rung.FULL: "page 1 of 9"})])
        d = diagnose(t)
        assert d.near_empty and "OCR" in d.finding

    def test_node_count_is_not_the_signal(self):
        """egeria-docs concept pages have a MEDIAN of one content node each and
        are perfectly good documents. An earlier '<= 1 node' rule flagged every
        one of them."""
        from trellis_artifact_tree.model import Node
        from trellis_artifact_tree.diagnostics import diagnose

        t = self._tree([Node("r", "a", "document"),
                        Node("s", "a", "section", parent_id="r",
                             rungs={Rung.FULL: "x" * 500})], fidelity="structural")
        assert not diagnose(t).near_empty

    def test_structureless_is_distinct_from_near_empty(self):
        """The OmniGraffle case: 49 content nodes and 6,765 characters of real
        diagram labels, and zero sections. Usable, but a packer cannot cut it
        by depth."""
        from trellis_artifact_tree.model import Node
        from trellis_artifact_tree.diagnostics import diagnose

        t = self._tree([Node("r", "a", "document")] + [
            Node(f"n{i}", "a", "text", parent_id="r", ordinal=i,
                 rungs={Rung.FULL: "label " * 20})
            for i in range(20)
        ])
        d = diagnose(t)
        assert not d.near_empty and d.structureless
        assert "cut it by depth" in d.finding

    def test_short_markdown_is_not_a_finding(self):
        """20% of 15,983 artifacts are near-empty and almost all are short
        markdown stubs -- 49% of one corpus. Nothing can be done about a short
        file, and reporting 3,177 of them would bury the case that matters."""
        from dataclasses import replace

        from trellis_artifact_tree.model import ArtifactTree, Node
        from trellis_artifact_tree.diagnostics import diagnose

        nodes = (Node("r", "a", "document"),
                 Node("s", "a", "section", parent_id="r", rungs={Rung.FULL: "tiny"}))
        structural = ArtifactTree("a", replace(PROV, extraction_fidelity="structural"), nodes)
        inferred = ArtifactTree("a", replace(PROV, extraction_fidelity="inferred"), nodes)

        assert diagnose(structural).near_empty          # still true
        assert diagnose(structural).finding == ""       # but not reported
        assert diagnose(inferred).finding != ""         # this one is
