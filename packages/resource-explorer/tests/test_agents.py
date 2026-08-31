"""Tests for StatsAgent and HealthAgent — SQLite-backed, no LLM or GitHub calls."""
from __future__ import annotations

import json
import sqlite3

import pytest

from resource_explorer.registry import Project, ProjectRegistry, ProjectStatus


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
    )
    registry.add(p)
    return p


def _insert_stats(db_path: str, slug: str, **overrides):
    defaults = dict(
        resource_slug=slug,
        fetched_at="2024-06-01T12:00:00",
        stars=1500,
        forks=200,
        watchers=1500,
        open_issues=45,
        contributors_count=32,
        commits_30d=28,
        commits_90d=87,
        releases_count=14,
        latest_release="v2.3.1",
        latest_release_at="2024-05-15T00:00:00",
        primary_language="Python",
        language_breakdown=json.dumps({"Python": 85000, "Shell": 3000}),
    )
    row = {**defaults, **overrides}
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO project_stats
        (project_slug, fetched_at, stars, forks, watchers, open_issues,
         contributors_count, commits_30d, commits_90d, releases_count,
         latest_release, latest_release_at, primary_language, language_breakdown)
        VALUES (:resource_slug, :fetched_at, :stars, :forks, :watchers, :open_issues,
                :contributors_count, :commits_30d, :commits_90d, :releases_count,
                :latest_release, :latest_release_at, :primary_language, :language_breakdown)
    """, row)
    conn.commit()
    conn.close()


# ── StatsAgent ────────────────────────────────────────────────────────────────

class TestStatsAgentFetchStats:
    def test_returns_empty_string_with_no_slug(self, registry, monkeypatch):
        from resource_explorer.agents.stats_agent import StatsAgent
        monkeypatch.setattr("resource_explorer.agents.stats_agent.ProjectRegistry", lambda: registry)
        agent = StatsAgent()
        assert agent._fetch_stats(None) == ""

    def test_returns_empty_string_when_no_stats_row(self, registry, project, monkeypatch):
        from resource_explorer.agents.stats_agent import StatsAgent
        monkeypatch.setattr("resource_explorer.agents.stats_agent.ProjectRegistry", lambda: registry)
        agent = StatsAgent()
        assert agent._fetch_stats("myproj") == ""

    def test_returns_formatted_stats(self, registry, project, monkeypatch):
        from resource_explorer.agents.stats_agent import StatsAgent
        _insert_stats(registry.db_path, "myproj")
        monkeypatch.setattr("resource_explorer.agents.stats_agent.ProjectRegistry", lambda: registry)
        agent = StatsAgent()
        result = agent._fetch_stats("myproj")
        assert "1500" in result
        assert "200" in result
        assert "32" in result
        assert "28" in result
        assert "Python" in result

    def test_includes_trend_when_multiple_rows(self, registry, project, monkeypatch):
        from resource_explorer.agents.stats_agent import StatsAgent
        _insert_stats(registry.db_path, "myproj", fetched_at="2024-01-01T00:00:00", stars=1000)
        _insert_stats(registry.db_path, "myproj", fetched_at="2024-06-01T00:00:00", stars=1500)
        monkeypatch.setattr("resource_explorer.agents.stats_agent.ProjectRegistry", lambda: registry)
        agent = StatsAgent()
        result = agent._fetch_stats("myproj")
        assert "Trends" in result
        assert "+500" in result


# ── HealthAgent ───────────────────────────────────────────────────────────────

class TestHealthAgentFetchHealth:
    def test_returns_empty_string_with_no_slug(self, registry, monkeypatch):
        from resource_explorer.agents.health_agent import HealthAgent
        monkeypatch.setattr("resource_explorer.agents.health_agent.ProjectRegistry", lambda: registry)
        agent = HealthAgent()
        assert agent._fetch_health(None) == ""

    def test_returns_empty_string_when_project_not_found(self, registry, monkeypatch):
        from resource_explorer.agents.health_agent import HealthAgent
        monkeypatch.setattr("resource_explorer.agents.health_agent.ProjectRegistry", lambda: registry)
        agent = HealthAgent()
        assert agent._fetch_health("ghost") == ""

    def test_returns_empty_string_when_no_stats(self, registry, project, monkeypatch):
        from resource_explorer.agents.health_agent import HealthAgent
        monkeypatch.setattr("resource_explorer.agents.health_agent.ProjectRegistry", lambda: registry)
        agent = HealthAgent()
        # _github_health will fail (no real API) — that's OK, we just want the base
        result = agent._fetch_health("myproj")
        assert result == ""

    def test_returns_health_report(self, registry, project, monkeypatch):
        from resource_explorer.agents.health_agent import HealthAgent
        _insert_stats(registry.db_path, "myproj")
        monkeypatch.setattr("resource_explorer.agents.health_agent.ProjectRegistry", lambda: registry)
        # Suppress GitHub API call
        monkeypatch.setattr(
            "resource_explorer.agents.health_agent.HealthAgent._github_health",
            lambda self, proj: [],
        )
        agent = HealthAgent()
        result = agent._fetch_health("myproj")
        assert "Activity:" in result
        assert "Very active" in result  # 28 commits_30d → Very active (>20 threshold)
        assert "Community:" in result
        assert "Bus Factor:" in result
        assert "Maintenance:" in result

    @pytest.mark.parametrize("commits_30d,expected_status", [
        (25, "Very active"),
        (10, "Active"),
        (2, "Low activity"),
        (0, "Inactive"),
    ])
    def test_activity_status_thresholds(self, registry, project, monkeypatch, commits_30d, expected_status):
        from resource_explorer.agents.health_agent import HealthAgent
        _insert_stats(registry.db_path, "myproj", commits_30d=commits_30d)
        monkeypatch.setattr("resource_explorer.agents.health_agent.ProjectRegistry", lambda: registry)
        monkeypatch.setattr(
            "resource_explorer.agents.health_agent.HealthAgent._github_health",
            lambda self, proj: [],
        )
        agent = HealthAgent()
        result = agent._fetch_health("myproj")
        assert expected_status in result

    @pytest.mark.parametrize("contributors,expected_risk", [
        (25, "Low risk"),
        (8, "Moderate risk"),
        (3, "Elevated risk"),
        (1, "High risk"),
    ])
    def test_bus_factor_thresholds(self, registry, project, monkeypatch, contributors, expected_risk):
        from resource_explorer.agents.health_agent import HealthAgent
        _insert_stats(registry.db_path, "myproj", contributors_count=contributors)
        monkeypatch.setattr("resource_explorer.agents.health_agent.ProjectRegistry", lambda: registry)
        monkeypatch.setattr(
            "resource_explorer.agents.health_agent.HealthAgent._github_health",
            lambda self, proj: [],
        )
        agent = HealthAgent()
        result = agent._fetch_health("myproj")
        assert expected_risk in result
