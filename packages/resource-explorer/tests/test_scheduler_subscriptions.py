"""Tests for scheduler.py's Automate integration (Discovery-tier Part 4) —
after a scheduled run completes cleanly, active subscriptions watching that
exact (entity, analysis_id) get checked, and an RFA is written iff
notification_detector reports a real change.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer import scheduler


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def registered_project(registry):
    registry.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="",
    ))
    return "myproj"


def _make_due(registry, entity_type, slug, analysis_id):
    registry.save_schedule(entity_type, slug, analysis_id, "daily", True)
    with registry._conn() as conn:
        conn.execute(
            "UPDATE resource_schedules SET next_run = '2020-01-01T00:00:00+00:00' "
            "WHERE entity_type=? AND entity_slug=? AND analysis_id=?",
            (entity_type, slug, analysis_id),
        )


class TestSubscriptionDelivery:
    def test_no_subscription_no_rfa(self, registry, registered_project):
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert rfas == []

    def test_subscription_with_no_change_no_rfa(self, registry, registered_project):
        registry.create_subscription("repo", registered_project, "license_classification", "License risk changed")
        for ts in ("2026-08-01T00:00:00", "2026-08-02T00:00:00"):
            registry.upsert_finding(
                registered_project, "license_classification",
                [{"check_name": "license_risk_tier", "label": "permissive"}],
                surveyed_at=ts,
            )
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert rfas == []

        sub = registry.list_subscriptions(entity_slug=registered_project)[0]
        assert sub["last_checked_at"]
        assert sub["notification_count"] == 0

    def test_subscription_with_real_change_writes_rfa(self, registry, registered_project):
        registry.create_subscription("repo", registered_project, "license_classification", "License risk changed")
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive"}],
            surveyed_at="2026-08-01T00:00:00",
        )
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "strong_copyleft"}],
            surveyed_at="2026-08-02T00:00:00",
        )
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert len(rfas) == 1
        assert "License risk changed" in rfas[0]["summary"]
        assert "strong_copyleft" in rfas[0]["detail"]

        sub = registry.list_subscriptions(entity_slug=registered_project)[0]
        assert sub["notification_count"] == 1
        assert sub["last_notified_at"]

    def test_inactive_subscription_never_checked(self, registry, registered_project):
        sub = registry.create_subscription("repo", registered_project, "license_classification")
        registry.set_subscription_active(sub["id"], False)
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive"}], surveyed_at="2026-08-01T00:00:00",
        )
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "strong_copyleft"}], surveyed_at="2026-08-02T00:00:00",
        )
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        assert registry.get_subscription(sub["id"])["last_checked_at"] == ""
        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert rfas == []

    def test_failed_scheduled_run_never_checks_subscriptions(self, registry, registered_project):
        registry.create_subscription("repo", registered_project, "license_classification")
        _make_due(registry, "repo", registered_project, "license_classification")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("boom")
            scheduler._run_due()

        sub = registry.list_subscriptions(entity_slug=registered_project)[0]
        assert sub["last_checked_at"] == ""
