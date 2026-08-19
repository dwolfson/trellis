"""Tests for POST /api/projects/{slug}/profile-scan.

API-level on-demand coarse-profile refresh. Note there is no UI caller:
coarse profiling is surfaced as the "Coarse Profile Survey" Survey
Definition, run from Scouting's Survey sub-tab. The route is retained as
a scriptable trigger and mirrors what the scheduler does directly.
Downloads the zipball once via IngestionPipeline.refresh_profile(), refreshes
project_file_inventory/project_data_profiles (+ optionally project_code_symbols),
then auto-chains the language_file_classification survey against the freshly
refreshed inventory so the tab has something real to display."""
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


def _patch_refresh(file_count=5, symbol_count=0):
    fake_result = MagicMock(file_count=file_count, symbol_count=symbol_count)
    return patch(
        "resource_explorer.ingestion.pipeline.IngestionPipeline.refresh_profile",
        return_value=fake_result,
    )


def _patch_orchestrator(errors=None):
    fake_survey_result = MagicMock(errors=errors or [])
    return patch(
        "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator"
    ), fake_survey_result


class TestProfileScanRoute:
    def test_unknown_repo_returns_404(self, client):
        resp = client.post("/api/projects/not-a-real-repo/profile-scan")
        assert resp.status_code == 404

    def test_default_include_symbols_false(self, client):
        with _patch_refresh(file_count=5, symbol_count=0) as mock_refresh, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = MagicMock(errors=[])
            resp = client.post("/api/projects/myproj/profile-scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["file_count"] == 5
        assert data["symbol_count"] == 0
        _, kwargs = mock_refresh.call_args
        assert kwargs["include_symbols"] is False

    def test_include_symbols_true_passed_through(self, client):
        with _patch_refresh(file_count=5, symbol_count=42) as mock_refresh, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = MagicMock(errors=[])
            resp = client.post("/api/projects/myproj/profile-scan", json={"include_symbols": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol_count"] == 42
        assert "42 symbol" in data["message"]
        _, kwargs = mock_refresh.call_args
        assert kwargs["include_symbols"] is True

    def test_refresh_failure_surfaced_as_error_not_500(self, client):
        with patch(
            "resource_explorer.ingestion.pipeline.IngestionPipeline.refresh_profile",
            side_effect=RuntimeError("rate limited"),
        ):
            resp = client.post("/api/projects/myproj/profile-scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "rate limited" in data["error"]


class TestProfileScanAutoChainsClassification:
    def test_successful_refresh_auto_runs_classification(self, client):
        with _patch_refresh() as _, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = MagicMock(errors=[])
            resp = client.post("/api/projects/myproj/profile-scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["classified"] is True
        assert data["classification_error"] is None
        assert "Classification updated" in data["message"]
        from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP
        MockOrch.return_value.run.assert_called_once_with(
            "myproj", steps=REPO_ANALYSIS_STEP_MAP["language_file_classification"],
        )

    def test_classification_failure_does_not_fail_the_whole_request(self, client):
        """Refresh succeeded — classification failing shouldn't undo that or
        turn the response into a 500/error status."""
        with _patch_refresh() as _, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("classifier exploded")
            resp = client.post("/api/projects/myproj/profile-scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"  # refresh itself still succeeded
        assert data["classified"] is False
        assert "classifier exploded" in data["classification_error"]

    def test_classification_survey_errors_are_surfaced_not_swallowed(self, client):
        with _patch_refresh() as _, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = MagicMock(errors=["language survey failed"])
            resp = client.post("/api/projects/myproj/profile-scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["classified"] is False
        assert "language survey failed" in data["classification_error"]


class TestProfileScanRecordsLastProfiledAt:
    def test_successful_refresh_updates_last_profiled_at(self, client, registry):
        assert registry.get("myproj").last_profiled_at == ""
        with _patch_refresh() as _, \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = MagicMock(errors=[])
            resp = client.post("/api/projects/myproj/profile-scan")

        assert resp.status_code == 200
        assert registry.get("myproj").last_profiled_at != ""

    def test_failed_refresh_does_not_update_last_profiled_at(self, client, registry):
        with patch(
            "resource_explorer.ingestion.pipeline.IngestionPipeline.refresh_profile",
            side_effect=RuntimeError("rate limited"),
        ):
            client.post("/api/projects/myproj/profile-scan")

        assert registry.get("myproj").last_profiled_at == ""
