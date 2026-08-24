"""Tests for HealthSurveyor's stats-refresh fix — previously it only ever
read whatever StatsFetcher wrote at registration time (wizard.py/
org_importer.py, never called again), so "Repository Health" silently
scored stale stars/forks/commit-activity data no matter how often it was
run on-demand or scheduled. It now refreshes project_stats itself before
reading it, best-effort (a fetch failure falls back to existing data
rather than failing the whole health check)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.health import HealthSurveyor
from resource_explorer.surveyors.survey_report import QualityScoreAnnotation


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(
        slug="myproj", display_name="My Project",
        github_url="https://github.com/test/myproj", collections=[],
    )
    registry.add(p)
    return p


def _seed_stats(registry, slug, stars=10):
    with registry._conn() as conn:
        conn.execute(
            "INSERT INTO project_stats (project_slug, stars, forks, contributors_count, "
            "commits_30d, commits_90d, commits_365d, releases_count, "
            "avg_release_interval_days, last_pushed_at, repo_created_at, fetched_at) "
            "VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, '', '', '')",
            (slug, stars),
        )


class TestHealthSurveyorReadsStats:
    def test_does_not_refresh_stats_itself(self, registry, project):
        """The refresh moved out to the repo_git_statistics step. It was this
        surveyor's private side effect, which meant the seven *other* steps
        reading project_stats were fresh only when repo_health happened to be in
        the same run and happened to precede them — an ordering nothing declared
        and nothing enforced."""
        _seed_stats(registry, "myproj", stars=99)
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch") as mock_fetch:
            results = HealthSurveyor(project, registry).run()

        mock_fetch.assert_not_called()
        assert len(results) == 1
        assert isinstance(results[0], QualityScoreAnnotation)
        assert results[0].json_properties["stars"] == 99

    def test_persists_scores_so_the_results_card_can_populate(self, registry, project):
        """Previously it produced annotations only, so repository_health had no
        stored results and its Survey Results card was permanently empty."""
        _seed_stats(registry, "myproj", stars=99)
        HealthSurveyor(project, registry).run()

        metrics = registry.query_metrics("myproj", "repository_health")
        assert metrics.get("overall") is not None
        for component in ("activity", "community", "release_cadence", "freshness"):
            assert component in metrics

    def test_fetch_failure_falls_back_to_existing_stats(self, registry, project):
        _seed_stats(registry, "myproj", stars=5)
        with patch(
            "resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
            side_effect=RuntimeError("rate limited"),
        ):
            results = HealthSurveyor(project, registry).run()

        assert len(results) == 1
        assert isinstance(results[0], QualityScoreAnnotation)
        assert results[0].json_properties["stars"] == 5


class TestFastFlag:
    """The actual Coarse Scout slowness fix: fast=True skips StatsFetcher's
    per-commit diff-stats calls entirely (see StatsFetcher._fetch_commits'
    own docstring for the confirmed root cause — several hundred sequential
    API calls for an active repo's 90-day history, no cap on count or
    elapsed time)."""

    # The fast=True/False -> fetch_diff_stats assertions moved to
    # tests/test_git_statistics_surveyor.py along with the fetch itself.

    def test_no_stats_ever_and_fetch_fails_warns(self, registry, project):
        with patch(
            "resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
            side_effect=RuntimeError("rate limited"),
        ):
            results = HealthSurveyor(project, registry).run()

        assert len(results) == 1
        assert "No stats row found" in results[0].explanation


def _seed_full_stats(registry, slug):
    """Seed every column HealthSurveyor's json_properties now reads —
    the "persist everything, publish everything" attributes added
    alongside deployments/environments/security_and_analysis."""
    with registry._conn() as conn:
        conn.execute(
            "INSERT INTO project_stats (project_slug, stars, forks, contributors_count, "
            "commits_30d, commits_90d, commits_365d, releases_count, "
            "avg_release_interval_days, last_pushed_at, repo_created_at, fetched_at, "
            "archived, disabled, is_fork, is_template, default_branch, "
            "has_issues, has_wiki, has_discussions, has_projects, has_pages, "
            "network_count, subscribers_count, visibility, is_private, homepage, "
            "mirror_url, parent_full_name, allow_merge_commit, allow_squash_merge, "
            "allow_rebase_merge, allow_auto_merge, allow_update_branch, "
            "delete_branch_on_merge, security_and_analysis_json, environments_json, "
            "deployments_count, latest_deployment_at, latest_deployment_environment, "
            "latest_deployment_ref) "
            "VALUES (?, 10, 2, 3, 1, 2, 3, 1, 30, '', '', '', "
            "1, 0, 0, 0, 'main', 1, 1, 0, 1, 0, 5, 9, 'public', 0, 'https://example.com', "
            "'', '', 1, 1, 0, 0, 0, 0, '{\"secret_scanning\": \"enabled\"}', '[\"prod\"]', "
            "2, '2026-08-01T00:00:00', 'prod', 'main')",
            (slug,),
        )


class TestHealthSurveyorPublishesAllPersistedAttributes:
    """Explicit instruction: 'include all of the attributes in the survey
    results we publish to egeria' — every column stats_fetcher.py now
    persists must show up in QualityScoreAnnotation.json_properties, not
    just the subset used for scoring."""

    def test_json_properties_includes_lifecycle_and_config_fields(self, registry, project):
        _seed_full_stats(registry, "myproj")
        with patch(
            "resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
            side_effect=RuntimeError("no network in test"),
        ):
            results = HealthSurveyor(project, registry).run()

        props = results[0].json_properties
        assert props["archived"] is True
        assert props["disabled"] is False
        assert props["default_branch"] == "main"
        assert props["has_issues"] is True
        assert props["network_count"] == 5
        assert props["subscribers_count"] == 9
        assert props["visibility"] == "public"
        assert props["homepage"] == "https://example.com"
        assert props["allow_merge_commit"] is True
        assert props["allow_rebase_merge"] is False

    def test_json_properties_includes_security_and_deployments(self, registry, project):
        _seed_full_stats(registry, "myproj")
        with patch(
            "resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
            side_effect=RuntimeError("no network in test"),
        ):
            results = HealthSurveyor(project, registry).run()

        props = results[0].json_properties
        assert props["security_and_analysis"] == {"secret_scanning": "enabled"}
        assert props["environments"] == ["prod"]
        assert props["deployments_count"] == 2
        assert props["latest_deployment_environment"] == "prod"
        assert props["latest_deployment_ref"] == "main"

    def test_malformed_json_columns_degrade_gracefully(self, registry, project):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_stats (project_slug, stars, forks, contributors_count, "
                "commits_30d, commits_90d, commits_365d, releases_count, "
                "avg_release_interval_days, last_pushed_at, repo_created_at, fetched_at, "
                "security_and_analysis_json, environments_json) "
                "VALUES ('myproj', 1, 0, 0, 0, 0, 0, 0, 0, '', '', '', 'not-json', 'also-not-json')"
            )
        with patch(
            "resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
            side_effect=RuntimeError("no network in test"),
        ):
            results = HealthSurveyor(project, registry).run()

        props = results[0].json_properties
        assert props["security_and_analysis"] == {}
        assert props["environments"] == []
