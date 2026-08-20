"""Tests for GitStatisticsSurveyor — the step that refreshes project_stats.

project_stats is the most widely read table in the repo survey set (eight
sub-surveyors read it), and exactly one of them — HealthSurveyor — used to
refresh it, as an internal side effect. So licence classification, maturity,
security-feature and homepage results were fresh only when repo_health happened
to be in the same survey and happened to run first; an ordering nothing declared
and nothing enforced. Making the refresh a declared step gives every reader the
same guarantee and gives the refresh its own results.

The fast-flag assertions here moved with the fetch, from
tests/test_health_surveyor.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.git_statistics import (
    STEP,
    GitStatisticsSurveyor,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="myproj", display_name="My Proj",
                github_url="https://github.com/o/myproj", description="")
    registry.add(p)
    return p


def _seed(registry, slug, stars=7):
    """Same direct insert tests/test_health_surveyor.py uses — there is no
    public upsert for project_stats; StatsFetcher owns the write path."""
    with registry._conn() as conn:
        conn.execute(
            "INSERT INTO project_stats (project_slug, stars, forks, contributors_count, "
            "commits_30d, commits_90d, commits_365d, releases_count, "
            "avg_release_interval_days, last_pushed_at, repo_created_at, fetched_at) "
            "VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, '', '', '')",
            (slug, stars),
        )


class TestRefresh:
    def test_refreshes_then_reports(self, registry, project):
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch") as fetch:
            fetch.side_effect = lambda slug, **_k: _seed(registry, slug, stars=99)
            anns = GitStatisticsSurveyor(project, registry).run()

        fetch.assert_called_once_with("myproj", fetch_diff_stats=True)
        assert anns[0].analysis_step == STEP
        assert anns[0].resource_properties["stars"] == 99
        assert anns[0].resource_properties["refreshed"] is True

    def test_fast_true_skips_diff_stats(self, registry, project):
        """The Coarse Scout slowness fix: fast=True skips StatsFetcher's
        per-commit diff-stats calls — several hundred sequential API calls for
        an active repo's 90-day history."""
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch") as fetch:
            fetch.side_effect = lambda slug, **_k: _seed(registry, slug)
            GitStatisticsSurveyor(project, registry, fast=True).run()
        fetch.assert_called_once_with("myproj", fetch_diff_stats=False)

    def test_fast_false_is_the_default(self, registry, project):
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch") as fetch:
            fetch.side_effect = lambda slug, **_k: _seed(registry, slug)
            GitStatisticsSurveyor(project, registry).run()
        fetch.assert_called_once_with("myproj", fetch_diff_stats=True)


class TestDegradation:
    def test_fetch_failure_reports_stored_stats_rather_than_failing(self, registry, project):
        """A GitHub hiccup must not fail the survey — readers fall back to the
        stored row, which is what they did before this step existed."""
        _seed(registry, "myproj", stars=5)
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
                   side_effect=RuntimeError("rate limited")):
            anns = GitStatisticsSurveyor(project, registry).run()

        assert anns[0].resource_properties["stars"] == 5
        assert anns[0].resource_properties["refreshed"] is False
        assert anns[0].confidence == 50          # reported, not silently passed off as fresh
        assert "rate limited" in anns[0].explanation

    def test_no_stats_at_all_is_reported_not_raised(self, registry, project):
        with patch("resource_explorer.github.stats_fetcher.StatsFetcher.fetch",
                   side_effect=RuntimeError("boom")):
            anns = GitStatisticsSurveyor(project, registry).run()
        assert len(anns) == 1
        assert anns[0].confidence == 0
        assert anns[0].resource_properties["refreshed"] is False


class TestOrdering:
    def test_runs_before_every_step_that_reads_project_stats(self):
        """STEP_REGISTRY order is also 'Repo Full Survey' order, so a refresh
        placed after its readers leaves them on the previous run's numbers."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        order = list(STEP_REGISTRY)
        idx = order.index("repo_git_statistics")
        readers = ["repo_health", "repo_maturity", "repo_language", "repo_file_structure",
                   "repo_license_classification", "repo_security_features", "repo_homepage"]
        for r in readers:
            if r in order:
                assert idx < order.index(r), f"repo_git_statistics must precede {r}"
