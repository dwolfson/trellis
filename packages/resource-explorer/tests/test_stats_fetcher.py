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
    repo.archived = False
    repo.disabled = False
    repo.fork = False
    repo.is_template = False
    repo.default_branch = "main"
    repo.has_issues = True
    repo.has_wiki = True
    repo.has_discussions = False
    repo.has_projects = True
    repo.has_pages = False
    repo.network_count = 3
    repo.subscribers_count = 9
    repo.visibility = "public"
    repo.private = False
    repo.homepage = ""
    repo.mirror_url = None
    repo.parent = None
    repo.allow_merge_commit = True
    repo.allow_squash_merge = True
    repo.allow_rebase_merge = False
    repo.allow_auto_merge = False
    repo.allow_update_branch = False
    repo.delete_branch_on_merge = False
    repo.security_and_analysis = None
    repo.get_environments.return_value = []
    repo.get_deployments.return_value = MagicMock(totalCount=0)
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


class TestExtendedAttributesPersisted:
    """'persist them all and also the get_deployments/get_environments' —
    the free GitHub-API attributes plus deployments/environments must
    land in project_stats even though only a subset is displayed."""

    def test_lifecycle_and_config_flags_persisted(self, registry):
        repo = _make_fake_repo()
        repo.archived = True
        repo.default_branch = "trunk"
        repo.homepage = "https://example.org"
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["archived"] == 1
        assert stats["default_branch"] == "trunk"
        assert stats["homepage"] == "https://example.org"
        assert stats["network_count"] == 3
        assert stats["visibility"] == "public"

    def test_fork_persists_parent_full_name(self, registry):
        repo = _make_fake_repo()
        repo.fork = True
        repo.parent = MagicMock(full_name="upstream/original")
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["is_fork"] == 1
        assert stats["parent_full_name"] == "upstream/original"

    def test_non_fork_parent_full_name_empty(self, registry):
        repo = _make_fake_repo()
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["parent_full_name"] == ""

    def test_security_and_analysis_serialized(self, registry):
        repo = _make_fake_repo()
        feature = MagicMock(status="enabled")
        repo.security_and_analysis = MagicMock(
            advanced_security=feature,
            dependabot_security_updates=None,
            secret_scanning=feature,
            secret_scanning_ai_detection=None,
            secret_scanning_non_provider_patterns=None,
            secret_scanning_push_protection=None,
            secret_scanning_validity_checks=None,
        )
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        import json
        parsed = json.loads(stats["security_and_analysis_json"])
        assert parsed["advanced_security"] == "enabled"
        assert parsed["dependabot_security_updates"] is None

    def test_security_and_analysis_none_yields_empty_json(self, registry):
        repo = _make_fake_repo()
        repo.security_and_analysis = None
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["security_and_analysis_json"] == "{}"

    def test_environments_and_deployments_persisted(self, registry):
        repo = _make_fake_repo()
        env1, env2 = MagicMock(), MagicMock()
        env1.name = "prod"
        env2.name = "staging"
        repo.get_environments.return_value = [env1, env2]
        deployment = MagicMock(
            environment="prod", ref="main",
            updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        deployments = MagicMock(totalCount=2)
        deployments.__getitem__ = MagicMock(return_value=deployment)
        repo.get_deployments.return_value = deployments
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        import json
        assert json.loads(stats["environments_json"]) == ["prod", "staging"]
        assert stats["deployments_count"] == 2
        assert stats["latest_deployment_environment"] == "prod"
        assert stats["latest_deployment_ref"] == "main"
        assert stats["latest_deployment_at"] == "2026-08-01T00:00:00+00:00"

    def test_no_deployments_yields_zero_count(self, registry):
        repo = _make_fake_repo()
        repo.get_deployments.return_value = MagicMock(totalCount=0)
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["deployments_count"] == 0
        assert stats["latest_deployment_at"] == ""

    def test_environments_fetch_failure_degrades_to_empty_list(self, registry):
        repo = _make_fake_repo()
        repo.get_environments.side_effect = Exception("404 not accessible")
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["environments_json"] == "[]"

    def test_deployments_fetch_failure_degrades_to_empty(self, registry):
        repo = _make_fake_repo()
        repo.get_deployments.side_effect = Exception("404 not accessible")
        fetcher = _make_fetcher(registry, repo)

        fetcher.fetch("myproj")

        stats = registry.get_latest_project_stats("myproj")
        assert stats["deployments_count"] == 0
