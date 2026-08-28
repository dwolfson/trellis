"""Tests for POST /api/projects/{slug}/analyses/{analysis_id}/run's auto-publish
(projects.py's run_single_analysis) — gated on ProjectRegistry.has_assigned_egeria_
project(), same gate survey_definition_executor.py's Survey Definition path uses.
Confirmed live 2026-08-27 this route never published at all before this change.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    monkeypatch.setattr(
        "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_STEP_MAP",
        {"fake_analysis": ["fake_step"]},
    )
    from resource_explorer.web.app import app
    return TestClient(app)


def _fake_survey_result(errors=None, with_annotation=True):
    from resource_explorer.surveyors.survey_report import SurveyResult
    result = SurveyResult(
        resource_slug="myproj", project_display_name="My Project",
        github_url="https://github.com/test/myproj",
    )
    result.errors = errors or []
    if with_annotation:
        result.annotations = [MagicMock()]
    return result


class TestAutoPublishOnAnalysisRun:
    def test_unassigned_project_does_not_publish(self, client, registry):
        registry.set_project_context("repo", "myproj", status="unset")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result()
            r = client.post("/api/projects/myproj/analyses/fake_analysis/run")

        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        MockPub.assert_not_called()

    def test_assigned_project_auto_publishes(self, client, registry):
        registry.set_project_context("repo", "myproj", status="linked", egeria_project_guid="g-1")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result()
            r = client.post("/api/projects/myproj/analyses/fake_analysis/run")

        assert r.status_code == 200
        MockPub.assert_called_once()
        MockPub.return_value.publish.assert_called_once()

    def test_a_survey_with_errors_never_reaches_publish(self, client, registry):
        registry.set_project_context("repo", "myproj", status="linked", egeria_project_guid="g-1")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result(errors=["boom"])
            r = client.post("/api/projects/myproj/analyses/fake_analysis/run")

        assert r.json()["status"] == "error"
        MockPub.assert_not_called()

    def test_publish_failure_does_not_turn_a_successful_run_into_an_error(self, client, registry):
        registry.set_project_context("repo", "myproj", status="linked", egeria_project_guid="g-1")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result()
            MockPub.return_value.publish.side_effect = RuntimeError("egeria unreachable")
            r = client.post("/api/projects/myproj/analyses/fake_analysis/run")

        body = r.json()
        assert body["status"] == "ok"
        assert "egeria unreachable" in body["message"]

        # Backs the ☁ Publish button staying visible as a retry action —
        # see registry.py's get_analysis_last_run() / TestAnalysisLastRun
        # PublishFailedFlag in test_registry.py for the unit-level coverage.
        activity = registry.get_analysis_last_run("repo", "myproj")
        assert activity["fake_analysis"]["last_publish_failed"] is True
