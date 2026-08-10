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


class TestHealthSurveyorRefreshesStats:
    def test_calls_stats_fetcher_before_reading(self, registry, project):
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch") as mock_fetch:
            mock_fetch.side_effect = lambda slug: _seed_stats(registry, slug, stars=99)
            results = HealthSurveyor(project, registry).run()

        mock_fetch.assert_called_once_with("myproj")
        assert len(results) == 1
        assert isinstance(results[0], QualityScoreAnnotation)
        assert results[0].json_properties["stars"] == 99

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

    def test_no_stats_ever_and_fetch_fails_warns(self, registry, project):
        with patch(
            "resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
            side_effect=RuntimeError("rate limited"),
        ):
            results = HealthSurveyor(project, registry).run()

        assert len(results) == 1
        assert "No stats row found" in results[0].explanation
