"""Tests for POST /api/projects/{slug}/analyses/{analysis_id}/run's auto-publish
(projects.py's _run_single_analysis_sync, invoked from the background thread
run_single_analysis's route starts — see test_scouting_overview_routes.py's
TestRunSingleAnalysisBackground for why the dispatch logic is exercised there
rather than through the live route) — gated on
ProjectRegistry.has_assigned_egeria_project(), same gate
survey_definition_executor.py's Survey Definition path uses. Confirmed live
2026-08-27 this route never published at all before that change.
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


def _run_background(registry, analysis_id="fake_analysis"):
    """Starts the 'running' row run_single_analysis's route would, then runs
    the background function synchronously (in-thread, not backgrounded) — see
    test_scouting_overview_routes.py's TestRunSingleAnalysisBackground for why
    dispatch is exercised this way rather than through the live route."""
    from resource_explorer.activity_logger import log_analysis_run
    from resource_explorer.web.routes.projects import _run_single_analysis_background

    activity_id = log_analysis_run(
        registry, "repo", "myproj", "My Project", "running",
        f"Running '{analysis_id}' on myproj…", analysis_id,
    )
    with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
        _run_single_analysis_background("myproj", analysis_id, activity_id)
    return registry.get_activity(activity_id)


class TestAutoPublishOnAnalysisRun:
    def test_unassigned_project_does_not_publish(self, client, registry):
        registry.set_project_context("repo", "myproj", status="unset")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result()
            entry = _run_background(registry)

        assert entry["status"] == "ok"
        MockPub.assert_not_called()

    def test_assigned_project_auto_publishes(self, client, registry):
        registry.set_project_context("repo", "myproj", status="linked", egeria_project_guid="g-1")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result()
            entry = _run_background(registry)

        assert entry["status"] == "ok"
        MockPub.assert_called_once()
        MockPub.return_value.publish.assert_called_once()

    def test_a_survey_with_errors_never_reaches_publish(self, client, registry):
        registry.set_project_context("repo", "myproj", status="linked", egeria_project_guid="g-1")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result(errors=["boom"])
            entry = _run_background(registry)

        assert entry["status"] == "error"
        MockPub.assert_not_called()

    def test_publish_failure_does_not_turn_a_successful_run_into_an_error(self, client, registry):
        registry.set_project_context("repo", "myproj", status="linked", egeria_project_guid="g-1")
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result()
            MockPub.return_value.publish.side_effect = RuntimeError("egeria unreachable")
            entry = _run_background(registry)

        assert entry["status"] == "ok"
        assert "egeria unreachable" in entry["summary"]

        # Backs the ☁ Publish button staying visible as a retry action —
        # see registry.py's get_analysis_last_run() / TestAnalysisLastRun
        # PublishFailedFlag in test_registry.py for the unit-level coverage.
        activity = registry.get_analysis_last_run("repo", "myproj")
        assert activity["fake_analysis"]["last_publish_failed"] is True
