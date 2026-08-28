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
