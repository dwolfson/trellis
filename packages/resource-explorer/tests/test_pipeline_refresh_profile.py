"""Tests for IngestionPipeline.refresh_profile() — the combined, single-
zipball-download replacement for what used to be two independently-
downloading paths (IncrementalIndexer._run_profile_only + the old
extract_symbols_only body). See the "Repo Profile phase" plan.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        collections=["myproj_python_code"],
    ))
    return r


def _make_pipeline(registry):
    from resource_explorer.ingestion.pipeline import IngestionPipeline
    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.registry = registry
    pipeline.store = MagicMock()
    from rich.console import Console
    pipeline.console = Console()
    return pipeline


def _symbol_count(registry, slug):
    with registry._conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM project_code_symbols WHERE project_slug = ?", (slug,)
        ).fetchone()
        return row[0] if row else 0


def _make_local_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("def f(): pass\n")
    (root / "README.md").write_text("# hi\n")
    return root


class TestRefreshProfile:
    def test_downloads_zipball_exactly_once_regardless_of_include_symbols(self, registry, tmp_path):
        pipeline = _make_pipeline(registry)
        local_root = _make_local_root(tmp_path)
        client = MagicMock()
        client.download_zipball.return_value = local_root
        repo = MagicMock()

        pipeline.refresh_profile(
            "myproj", "https://github.com/test/myproj", ["myproj_python_code"],
            include_symbols=True, client=client, repo=repo,
        )

        assert client.download_zipball.call_count == 1
        client.get_repo.assert_not_called()  # repo was passed in — no redundant fetch

    def test_include_symbols_false_never_touches_code_symbols(self, registry, tmp_path):
        pipeline = _make_pipeline(registry)
        local_root = _make_local_root(tmp_path)
        client = MagicMock()
        client.download_zipball.return_value = local_root

        pipeline.refresh_profile(
            "myproj", "https://github.com/test/myproj", ["myproj_python_code"],
            include_symbols=False, client=client, repo=MagicMock(),
        )

        assert _symbol_count(registry, "myproj") == 0

    def test_include_symbols_true_populates_code_symbols(self, registry, tmp_path):
        pipeline = _make_pipeline(registry)
        local_root = _make_local_root(tmp_path)
        client = MagicMock()
        client.download_zipball.return_value = local_root

        result = pipeline.refresh_profile(
            "myproj", "https://github.com/test/myproj", ["myproj_python_code"],
            include_symbols=True, client=client, repo=MagicMock(),
        )

        count = _symbol_count(registry, "myproj")
        assert count > 0
        assert result.symbol_count == count

    def test_file_inventory_always_refreshed(self, registry, tmp_path):
        pipeline = _make_pipeline(registry)
        local_root = _make_local_root(tmp_path)
        client = MagicMock()
        client.download_zipball.return_value = local_root

        result = pipeline.refresh_profile(
            "myproj", "https://github.com/test/myproj", ["myproj_python_code"],
            include_symbols=False, client=client, repo=MagicMock(),
        )

        inventory = registry.get_file_inventory("myproj")
        assert len(inventory) == 2  # main.py + README.md
        assert result.file_count == 2

    def test_reuses_passed_in_client_and_repo_no_new_githubclient(self, registry, tmp_path):
        pipeline = _make_pipeline(registry)
        local_root = _make_local_root(tmp_path)
        client = MagicMock()
        client.download_zipball.return_value = local_root
        repo = MagicMock()

        with patch("resource_explorer.github.client.GitHubClient") as MockGHClient:
            pipeline.refresh_profile(
                "myproj", "https://github.com/test/myproj", [],
                client=client, repo=repo,
            )
            MockGHClient.assert_not_called()


class TestExtractSymbolsOnlyWrapper:
    def test_extract_symbols_only_delegates_to_refresh_profile(self, registry, tmp_path):
        """extract_symbols_only() is now a thin wrapper — same -> int contract,
        same symbol rows as before the refactor (regression guard)."""
        pipeline = _make_pipeline(registry)
        local_root = _make_local_root(tmp_path)
        client = MagicMock()
        client.download_zipball.return_value = local_root
        client.get_repo.return_value = MagicMock()

        with patch("resource_explorer.github.client.GitHubClient", return_value=client):
            total = pipeline.extract_symbols_only(
                "myproj", "https://github.com/test/myproj", ["myproj_python_code"],
            )

        assert isinstance(total, int)
        assert total > 0
        assert total == _symbol_count(registry, "myproj")
