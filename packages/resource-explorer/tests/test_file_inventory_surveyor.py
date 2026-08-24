"""Tests for FileInventorySurveyor — the survey step that refreshes
project_file_inventory.

Exists because that table was written only by RAG ingestion, IncrementalIndexer
and refresh_profile(), never by a survey step, while six survey steps read it.
"Coarse Profile Survey" therefore reported whatever an earlier, unrelated run
had left behind — and a repo registered without ingestion (the org-import path
skips it) had no way to populate it at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from resource_explorer.registry import Project
from resource_explorer.surveyors.sub_surveyors.file_inventory import (
    STEP,
    FileInventorySurveyor,
)


def _project():
    return Project(slug="myproj", display_name="My Proj",
                   github_url="https://github.com/o/myproj", description="")


class TestFileInventorySurveyor:
    def test_refreshes_inventory_from_the_injected_zipball_root(self, tmp_path):
        with patch(
            "resource_explorer.ingestion.pipeline.IngestionPipeline._store_file_inventory",
            return_value=42,
        ) as store:
            s = FileInventorySurveyor(_project(), MagicMock(), local_path=str(tmp_path))
            anns = s.run()

        assert store.call_count == 1
        # slug and the injected root are what it must pass through
        assert store.call_args[0][1] == "myproj"
        assert str(store.call_args[0][2]) == str(tmp_path)
        assert anns[0].resource_properties["file_count"] == 42
        assert anns[0].analysis_step == STEP

    def test_delegates_rather_than_walking_the_tree_itself(self, tmp_path):
        """A second implementation of "what counts as a file" would drift from
        ingestion the way the three annotation-props builders did."""
        (tmp_path / "a.py").write_text("x = 1")
        with patch(
            "resource_explorer.ingestion.pipeline.IngestionPipeline._store_file_inventory",
            return_value=1,
        ) as store:
            FileInventorySurveyor(_project(), MagicMock(), local_path=str(tmp_path)).run()
        assert store.called

    def test_does_not_construct_a_vector_store(self, tmp_path):
        """IngestionPipeline's constructor eagerly builds a MultiCollectionStore
        (a pgvector connection). Opening one on every survey run would be a real
        cost for a step that only needs the registry."""
        with patch("resource_explorer.ingestion.pipeline.IngestionPipeline.__init__") as init, \
             patch("resource_explorer.ingestion.pipeline.IngestionPipeline._store_file_inventory",
                   return_value=0):
            FileInventorySurveyor(_project(), MagicMock(), local_path=str(tmp_path)).run()
        init.assert_not_called()

    def test_failure_is_reported_not_raised(self, tmp_path):
        """A failed refresh must not take the whole survey down: dependent steps
        degrade to the previous inventory, which is exactly today's behaviour."""
        with patch(
            "resource_explorer.ingestion.pipeline.IngestionPipeline._store_file_inventory",
            side_effect=RuntimeError("zipball gone"),
        ):
            anns = FileInventorySurveyor(_project(), MagicMock(), local_path=str(tmp_path)).run()

        assert len(anns) == 1
        assert anns[0].confidence == 0
        assert "zipball gone" in anns[0].explanation
        assert anns[0].resource_properties["file_count"] == 0
