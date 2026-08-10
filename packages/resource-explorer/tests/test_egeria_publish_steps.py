"""Tests for phase-scoped Egeria publish: POST /api/egeria/{slug}/publish's
optional `steps` field, threaded into SurveyOrchestrator.run(steps=...).

steps=None (the default/omitted case) must remain byte-for-byte the existing
full-survey behavior — this is the regression guard for that. A non-empty
steps list scopes both the survey and the published SurveyReport to just
those step keys (the mechanism the Scouting "Profile" tab's phase-scoped
publish buttons rely on).
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
    from resource_explorer.web.app import app
    return TestClient(app)


def _fake_result():
    result = MagicMock()
    result.annotations = ["a", "b"]
    result.errors = []
    result.surveyed_at.isoformat.return_value = "2026-08-09T00:00:00"
    return result


class TestPublishStepsParam:
    def test_omitted_steps_defaults_to_full_survey(self, client):
        with patch(
            "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator"
        ) as MockOrch, patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher"
        ) as MockPub:
            MockOrch.return_value.run.return_value = _fake_result()
            MockPub.return_value.publish.return_value = "report-guid-1"
            resp = client.post("/api/egeria/myproj/publish", json={})

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        MockOrch.return_value.run.assert_called_once_with("myproj", steps=None)

    def test_no_body_also_defaults_to_full_survey(self, client):
        with patch(
            "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator"
        ) as MockOrch, patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher"
        ) as MockPub:
            MockOrch.return_value.run.return_value = _fake_result()
            MockPub.return_value.publish.return_value = "report-guid-1"
            resp = client.post("/api/egeria/myproj/publish")

        assert resp.status_code == 200
        MockOrch.return_value.run.assert_called_once_with("myproj", steps=None)

    def test_explicit_steps_scope_the_survey(self, client):
        with patch(
            "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator"
        ) as MockOrch, patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher"
        ) as MockPub:
            MockOrch.return_value.run.return_value = _fake_result()
            MockPub.return_value.publish.return_value = "report-guid-2"
            resp = client.post("/api/egeria/myproj/publish", json={"steps": ["repo_health"]})

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        MockOrch.return_value.run.assert_called_once_with("myproj", steps=["repo_health"])

    def test_zone_names_still_pass_through_alongside_steps(self, client):
        with patch(
            "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator"
        ) as MockOrch, patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher"
        ) as MockPub:
            MockOrch.return_value.run.return_value = _fake_result()
            MockPub.return_value.publish.return_value = "report-guid-3"
            resp = client.post(
                "/api/egeria/myproj/publish",
                json={"steps": ["repo_language", "repo_file_classification", "repo_file_structure", "repo_data_profiling"],
                      "zone_names": ["data-lake"]},
            )

        assert resp.status_code == 200
        MockOrch.return_value.run.assert_called_once_with(
            "myproj",
            steps=["repo_language", "repo_file_classification", "repo_file_structure", "repo_data_profiling"],
        )
