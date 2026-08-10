"""Regression test for StatsFetcher — it must write through registry._conn(),
not a raw sqlite3.connect(self.registry.db_path) connection.

Before this fix, StatsFetcher wrote directly to a leftover local SQLite file
via sqlite3.connect(self.registry.db_path) — a path that predates the
registry's Postgres cutover. Every registry read goes through registry._conn(),
which routes to whichever backend is actually configured, so every "refresh
stats" call silently wrote into an orphaned file nobody read: last_pushed_at
(and stars/forks/commits) stayed frozen no matter how many times fetch() ran.
Confirmed live against a real repo before this fix landed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
    ))
    return r


def _make_fake_repo():
    repo = MagicMock()
    repo.stargazers_count = 42
    repo.forks_count = 7
    repo.watchers_count = 42
    repo.open_issues_count = 3
    repo.get_contributors.return_value.totalCount = 5
    repo.get_commits.return_value.totalCount = 10
    repo.get_releases.return_value = []
    repo.language = "Python"
    repo.get_languages.return_value = {"Python": 1000}
    repo.size = 512
    repo.get_topics.return_value = []
    repo.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    repo.pushed_at = datetime(2026, 8, 9, 19, 32, 9, tzinfo=timezone.utc)
    repo.get_licenses if False else None
    repo.get_license = MagicMock(side_effect=Exception("no license"))
    repo.get_git_tree.return_value.tree = []
    return repo


def _make_fetcher(registry, repo):
    from resource_explorer.github.stats_fetcher import StatsFetcher
    fetcher = StatsFetcher.__new__(StatsFetcher)
    fetcher.registry = registry
    fetcher.client = MagicMock()
    fetcher.client.get_repo.return_value = repo
    fetcher.client.check_rate_limit.return_value = {"remaining": 5000}
    return fetcher


class TestStatsFetcherWritesThroughRegistryConn:
    def test_fetch_no_longer_uses_raw_sqlite3(self):
        import inspect
        from resource_explorer.github import stats_fetcher
        source = inspect.getsource(stats_fetcher)
        assert "sqlite3.connect" not in source, (
            "stats_fetcher.py must not use a raw sqlite3.connect() — it "
            "bypasses the registry's actual backend (Postgres in "
            "production). Use self.registry._conn() instead."
        )

    def test_fetch_result_is_immediately_visible_via_registry_read(self, registry):
        """The real regression: a write via fetch() must be visible through
        the SAME connection path get_latest_project_stats() uses — not a
        different, orphaned database."""
        repo = _make_fake_repo()
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats is not None
        assert stats["last_pushed_at"] == "2026-08-09T19:32:09+00:00"
        assert stats["stars"] == 42

    def test_repeated_fetch_updates_the_visible_row_not_a_stale_copy(self, registry):
        repo = _make_fake_repo()
        fetcher = _make_fetcher(registry, repo)
        fetcher.fetch("myproj")

        repo.stargazers_count = 100
        repo.pushed_at = datetime(2026, 8, 9, 20, 0, 0, tzinfo=timezone.utc)
        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["stars"] == 100
        assert stats["last_pushed_at"] == "2026-08-09T20:00:00+00:00"
