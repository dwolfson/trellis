"""Tests for IncrementalIndexer — SHA comparison and changed-file routing."""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry, ProjectStatus

_pygithub_available = pytest.mark.skipif(
    importlib.util.find_spec("github") is None, reason="PyGitHub not installed"
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        collections=["myproj_python_code", "myproj_markdown_docs"],
    )
    registry.add(p)
    return p


@_pygithub_available
class TestIncrementalIndexer:
    def _make_indexer(self, registry):
        from resource_explorer.ingestion.incremental import IncrementalIndexer
        indexer = IncrementalIndexer.__new__(IncrementalIndexer)
        indexer.registry = registry
        indexer.client = MagicMock()
        return indexer

    def test_no_op_when_sha_unchanged(self, registry, project, capsys):
        indexer = self._make_indexer(registry)
        registry.update_commit_sha("myproj", "abc123")
        indexer.client.get_repo.return_value = MagicMock()
        indexer.client.get_latest_commit_sha.return_value = "abc123"

        indexer.refresh(project)
        captured = capsys.readouterr()
        assert "No changes" in captured.out

    def test_get_last_sha_returns_empty_for_fresh_project(self, registry, project):
        indexer = self._make_indexer(registry)
        assert indexer._get_last_sha("myproj") == ""

    def test_get_last_sha_returns_stored_value(self, registry, project):
        indexer = self._make_indexer(registry)
        registry.update_commit_sha("myproj", "deadbeef")
        assert indexer._get_last_sha("myproj") == "deadbeef"

    def test_store_last_sha_persists(self, registry, project):
        indexer = self._make_indexer(registry)
        indexer._store_last_sha("myproj", "newsha123")
        assert registry.get("myproj").last_commit_sha == "newsha123"

    def test_get_changed_files_returns_empty_when_no_old_sha(self, registry, project):
        indexer = self._make_indexer(registry)
        repo = MagicMock()
        result = indexer._get_changed_files(repo, "", "newsha")
        assert result == []
        repo.compare.assert_not_called()

    def test_get_changed_files_calls_github_compare(self, registry, project):
        indexer = self._make_indexer(registry)
        repo = MagicMock()
        f1, f2 = MagicMock(filename="src/main.py"), MagicMock(filename="README.md")
        repo.compare.return_value.files = [f1, f2]
        result = indexer._get_changed_files(repo, "old", "new")
        assert result == ["src/main.py", "README.md"]
        repo.compare.assert_called_once_with("old", "new")

    def test_get_changed_files_handles_github_exception(self, registry, project):
        indexer = self._make_indexer(registry)
        repo = MagicMock()
        repo.compare.side_effect = Exception("GitHub API error")
        result = indexer._get_changed_files(repo, "old", "new")
        assert result == []

    def test_refresh_stores_new_sha_after_no_changes(self, registry, project, capsys):
        indexer = self._make_indexer(registry)
        repo = MagicMock()
        repo.compare.return_value.files = []
        indexer.client.get_repo.return_value = repo
        indexer.client.get_latest_commit_sha.return_value = "newsha"
        registry.update_commit_sha("myproj", "oldsha")

        indexer.refresh(project)
        assert registry.get("myproj").last_commit_sha == "newsha"

    def test_refresh_identifies_affected_collections(self, registry, project, capsys):
        indexer = self._make_indexer(registry)
        repo = MagicMock()
        # Changed: one Python file → affects python_code collection
        f = MagicMock(filename="src/main.py")
        repo.compare.return_value.files = [f]
        indexer.client.get_repo.return_value = repo
        indexer.client.get_latest_commit_sha.return_value = "newsha"
        registry.update_commit_sha("myproj", "oldsha")

        with patch("resource_explorer.ingestion.incremental.IngestionPipeline") as MockPipeline, \
             patch("resource_explorer.ingestion.incremental.MultiCollectionStore") as MockStore, \
             patch("resource_explorer.ingestion.incremental.ProjectRegistry", return_value=registry):
            mock_pipeline = MagicMock()
            mock_pipeline._ingest_collection.return_value = 10
            mock_pipeline._count_repo_stats.return_value = (42, 1000)
            MockPipeline.return_value = mock_pipeline
            mock_store = MagicMock()
            MockStore.return_value = mock_store

            indexer.refresh(project)

            # Should have dropped and re-indexed affected collections
            assert mock_store.drop_collection.called
            assert mock_pipeline._ingest_collection.called
