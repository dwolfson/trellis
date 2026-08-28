"""The ingestion bridge to trellis-artifact-tree.

Two properties matter more than the happy path: OFF must mean today's behaviour
byte for byte (no connection, no table, no work), and ON must never be able to
cost the corpus -- a broken tree build leaves ingestion with its chunks.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.ingestion import artifact_tree_sink as sink


@pytest.fixture(autouse=True)
def _reset():
    sink._reset_for_tests()
    yield
    sink._reset_for_tests()


def _cfg(enabled: bool):
    cfg = MagicMock()
    cfg.artifact_tree.enabled = enabled
    cfg.artifact_tree.schema_name = "artifact_tree"
    cfg.pgvector.host = "h"
    cfg.pgvector.port = 5442
    cfg.pgvector.dbname = "egeria_advisor"
    cfg.pgvector.db_user = "u"
    cfg.pgvector.password = "p"
    return cfg


FILES = [("docs/a.md", "# A\nbody"), ("docs/b.md", "# B\nbody")]


class TestDisabledIsTodaysBehaviour:
    def test_returns_zero_and_touches_nothing(self):
        """Off must not open a connection or create a table -- otherwise
        'off by default' still changes what a deployment does."""
        with patch.object(sink, "_store") as store, \
             patch("resource_explorer.config.get_config", return_value=_cfg(False)):
            result = sink.build_trees(FILES, "amundsen")
            assert result.status == "disabled"
            assert result.stored == 0
            store.assert_not_called()


class TestEnabled:
    def test_stores_one_tree_per_file(self):
        store = MagicMock()
        with patch.object(sink, "_store", return_value=store), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            assert sink.build_trees(FILES, "amundsen").stored == 2
        assert store.put.call_count == 2
        ids = [c.args[0].artifact_id for c in store.put.call_args_list]
        assert ids == ["amundsen:docs/a.md", "amundsen:docs/b.md"]

    def test_schema_created_once_per_process(self):
        store = MagicMock()
        with patch.object(sink, "_store", return_value=store), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            sink.build_trees(FILES, "amundsen")
            sink.build_trees(FILES, "other")
        assert store.create_schema.call_count == 1

    def test_provenance_carries_path_and_version(self):
        store = MagicMock()
        with patch.object(sink, "_store", return_value=store), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            sink.build_trees(FILES[:1], "amundsen", source_version="abc123")
        prov = store.put.call_args.args[0].provenance
        assert prov.source_id == "docs/a.md"
        assert prov.source_version == "abc123"
        assert prov.fetched_at
        # stamped by the adapter that ran, not by the caller
        assert prov.extraction_fidelity == "structural"


class TestFailSoft:
    def test_setup_failure_does_not_raise(self):
        """A tree is an optimisation over a working pipeline. A broken one must
        not cost the corpus."""
        with patch.object(sink, "_store", side_effect=RuntimeError("no db")), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            result = sink.build_trees(FILES, "amundsen")
        assert result.status == "unavailable"
        assert result.stored == 0
        # distinguishable from "off" and from "nothing to do" -- the whole
        # point of not returning a bare 0 (tests/test_no_silent_success.py)
        assert "RuntimeError" in result.reason

    def test_one_bad_file_does_not_abandon_the_rest(self):
        store = MagicMock()
        store.put.side_effect = [RuntimeError("bad"), None]
        with patch.object(sink, "_store", return_value=store), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            result = sink.build_trees(FILES, "amundsen")
        assert (result.status, result.stored, result.skipped) == ("partial", 1, 1)
        assert store.put.call_count == 2


class TestCodeTrees:
    def test_unsupported_language_is_named_once_not_skipped_per_file(self):
        """go_code is a real collection here and the tree package has no Go
        grammar. A thousand identical per-file warnings would be noise hiding
        one fact, so the gap is checked up front and named."""
        with patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            result = sink.build_code_trees(FILES, "amundsen", "go")
        assert result.status == "unsupported"
        assert "go" in result.reason and "python" in result.reason
        assert result.stored == 0

    def test_supported_language_pins_one_adapter(self):
        store = MagicMock()
        py_files = [("a.py", "class A:\n    def m(self):\n        pass\n")]
        with patch.object(sink, "_store", return_value=store), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            result = sink.build_code_trees(py_files, "amundsen", "python")
        assert (result.status, result.stored) == ("stored", 1)
        tree = store.put.call_args.args[0]
        assert {n.kind for n in tree.nodes} == {"module", "class", "function"}

    def test_disabled_short_circuits_before_importing_the_adapter(self):
        with patch("resource_explorer.config.get_config", return_value=_cfg(False)):
            assert sink.build_code_trees(FILES, "amundsen", "python").status == "disabled"


class TestPdfTrees:
    def test_display_path_keys_the_artifact_not_the_absolute_path(self):
        """An absolute path is a property of this checkout, not of the
        document -- keying on it would make the same PDF a different artifact
        on every host."""
        store = MagicMock()
        adapter = MagicMock()
        adapter.parse.return_value = "tree-sentinel"
        with patch.object(sink, "_store", return_value=store), \
             patch("trellis_artifact_tree.adapters_pdf.PdfAdapter", return_value=adapter), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            sink.build_pdf_trees([("docs/paper.pdf", "/tmp/x/docs/paper.pdf")], "amundsen")
        artifact_id, source, prov = adapter.parse.call_args.args
        assert artifact_id == "amundsen:docs/paper.pdf"
        assert source == "/tmp/x/docs/paper.pdf"   # the adapter still opens the real file
        assert prov.source_id == "docs/paper.pdf"

    def test_disabled_short_circuits(self):
        with patch("resource_explorer.config.get_config", return_value=_cfg(False)):
            assert sink.build_pdf_trees([], "amundsen").status == "disabled"


class TestEmptyIsNotAFailure:
    def test_no_files_is_a_clean_run(self):
        """A collection with nothing to parse is not the same as a broken one,
        and must not open a connection to discover that."""
        with patch.object(sink, "_store") as store, \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)):
            assert sink.build_trees([], "amundsen").status == "stored"
            store.assert_not_called()


class TestSharedDoclingConversion:
    """Docling conversion is the expensive step in a PDF ingest. Converting
    once for chunks and again for the tree doubles the cost of a PDF-heavy
    repo for no benefit."""

    def test_documents_are_passed_through_without_reconversion(self):
        store = MagicMock()
        document = object()
        with patch.object(sink, "_store", return_value=store), \
             patch("resource_explorer.config.get_config", return_value=_cfg(True)), \
             patch("docling.document_converter.DocumentConverter") as conv:
            result = sink.build_pdf_trees_from_documents(
                [("docs/paper.pdf", document)], "amundsen",
            )
        conv.assert_not_called()
        assert result.status in ("stored", "partial")

    def test_parse_pdf_with_a_document_does_not_convert(self):
        from resource_explorer.ingestion.doc_parser import DocParser

        document = MagicMock()
        document.export_to_markdown.return_value = "# T\nbody text here"
        with patch("docling.document_converter.DocumentConverter") as conv:
            chunks = DocParser(50, 5).parse_pdf("/tmp/x.pdf", "amundsen", document=document)
        conv.assert_not_called()
        document.export_to_markdown.assert_called_once()
        assert chunks and chunks[0].metadata["type"] == "pdf"


class TestIngestPdfsConvertsOncePerFile:
    """The end-to-end property: one DocumentConverter for the collection, and
    one conversion per file feeding both the chunker and the tree."""

    def test_one_converter_and_one_conversion_per_file(self, tmp_path):
        from resource_explorer.ingestion.pipeline import IngestionPipeline

        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.pdf").write_bytes(b"%PDF-1.4")

        document = MagicMock()
        document.export_to_markdown.return_value = "# T\nbody"
        converter = MagicMock()
        converter.convert.return_value = MagicMock(document=document)

        ctype = MagicMock(chunk_size=50, chunk_overlap=5)
        with patch("resource_explorer.registry.ProjectRegistry"), \
             patch("resource_explorer.vector_store_pg.MultiCollectionStore"), \
             patch("docling.document_converter.DocumentConverter",
                   return_value=converter) as conv_cls, \
             patch("resource_explorer.config.get_config", return_value=_cfg(False)):
            pipeline = IngestionPipeline.__new__(IngestionPipeline)
            pipeline.console = MagicMock()
            chunks = pipeline._ingest_pdfs(tmp_path, "amundsen", ctype)

        assert conv_cls.call_count == 1, "one converter for the whole collection"
        assert converter.convert.call_count == 2, "one conversion per file, not two"
        assert chunks
