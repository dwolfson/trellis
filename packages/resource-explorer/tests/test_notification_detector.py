"""Tests for notification_detector.py — generic change detection between
an analysis kind's latest two runs (Discovery-tier Part 4).
"""
from __future__ import annotations

import pytest

from resource_explorer.notification_detector import detect_change
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


class TestFindingsShapedKinds:
    @pytest.fixture(autouse=True)
    def _register_myproj(self, registry):
        # upsert_finding() now rejects an unregistered slug (2026-08-23,
        # project_analysis_findings_project_slug_fkey incident) — register
        # "myproj" so this class's findings calls still exercise
        # detect_change() rather than the new guard.
        registry.add(Project(slug="myproj", display_name="My Project",
                              github_url="https://github.com/test/myproj"))

    def test_no_history_is_not_changed(self, registry):
        result = detect_change(registry, "myproj", "license_classification")
        assert result.changed is False

    def test_single_run_is_not_changed(self, registry):
        registry.upsert_finding(
            "myproj", "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive", "summary": "MIT"}],
            surveyed_at="2026-08-01T00:00:00",
        )
        result = detect_change(registry, "myproj", "license_classification")
        assert result.changed is False

    def test_identical_second_run_is_not_changed(self, registry):
        for ts in ("2026-08-01T00:00:00", "2026-08-02T00:00:00"):
            registry.upsert_finding(
                "myproj", "license_classification",
                [{"check_name": "license_risk_tier", "label": "permissive", "summary": "MIT"}],
                surveyed_at=ts,
            )
        result = detect_change(registry, "myproj", "license_classification")
        assert result.changed is False

    def test_label_change_is_detected(self, registry):
        registry.upsert_finding(
            "myproj", "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive", "summary": "MIT"}],
            surveyed_at="2026-08-01T00:00:00",
        )
        registry.upsert_finding(
            "myproj", "license_classification",
            [{"check_name": "license_risk_tier", "label": "strong_copyleft", "summary": "GPL-3.0"}],
            surveyed_at="2026-08-02T00:00:00",
        )
        result = detect_change(registry, "myproj", "license_classification")
        assert result.changed is True
        assert "license_risk_tier" in result.summary
        assert "permissive" in result.summary
        assert "strong_copyleft" in result.summary

    def test_only_compares_latest_two_batches(self, registry):
        # A change three runs ago that's since reverted must not re-fire —
        # only the most recent transition matters.
        for ts, label in [
            ("2026-08-01T00:00:00", "permissive"),
            ("2026-08-02T00:00:00", "strong_copyleft"),
            ("2026-08-03T00:00:00", "permissive"),
        ]:
            registry.upsert_finding(
                "myproj", "license_classification",
                [{"check_name": "license_risk_tier", "label": label}],
                surveyed_at=ts,
            )
        result = detect_change(registry, "myproj", "license_classification")
        assert result.changed is True  # 08-02 -> 08-03 is still a real transition
        assert "strong_copyleft" in result.summary and "permissive" in result.summary

    def test_new_check_appearing_counts_as_change(self, registry):
        registry.upsert_finding(
            "myproj", "repo_conventions",
            [{"check_name": "automated_build", "label": "gap"}],
            surveyed_at="2026-08-01T00:00:00",
        )
        registry.upsert_finding(
            "myproj", "repo_conventions",
            [
                {"check_name": "automated_build", "label": "gap"},
                {"check_name": "catalog_info", "label": "present"},
            ],
            surveyed_at="2026-08-02T00:00:00",
        )
        result = detect_change(registry, "myproj", "repo_conventions")
        assert result.changed is True
        assert "catalog_info" in result.summary


class TestMetricsShapedKinds:
    @pytest.fixture(autouse=True)
    def _register_project(self, registry):
        """Same fixture the sibling findings class needs. Both classes relied on
        SQLite silently ignoring the FK to projects.slug; with the pragma on
        (and on Postgres all along) an unregistered slug is rejected."""
        from resource_explorer.registry import Project
        if registry.get("myproj") is None:
            registry.add(Project(slug="myproj", display_name="My Project",
                                 github_url="https://github.com/test/myproj",
                                 collections=[]))

    def test_no_metrics_history_is_not_changed(self, registry):
        result = detect_change(registry, "myproj", "api_structure")
        assert result.changed is False

    def test_metric_value_change_is_detected(self, registry):
        registry.upsert_metric("myproj", "api_structure", {"symbol_count": 100}, surveyed_at="2026-08-01T00:00:00")
        registry.upsert_metric("myproj", "api_structure", {"symbol_count": 150}, surveyed_at="2026-08-02T00:00:00")
        result = detect_change(registry, "myproj", "api_structure")
        assert result.changed is True
        assert "symbol_count" in result.summary
        assert "100" in result.summary and "150" in result.summary

    def test_unchanged_metric_value_is_not_changed(self, registry):
        registry.upsert_metric("myproj", "api_structure", {"symbol_count": 100}, surveyed_at="2026-08-01T00:00:00")
        registry.upsert_metric("myproj", "api_structure", {"symbol_count": 100}, surveyed_at="2026-08-02T00:00:00")
        result = detect_change(registry, "myproj", "api_structure")
        assert result.changed is False
