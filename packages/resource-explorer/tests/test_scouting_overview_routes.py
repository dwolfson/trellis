"""Tests for the Scouting/Analysis boundary Phase A routes:
GET /{slug}/scouting-overview, POST /{slug}/scouting-scan,
POST /{slug}/analyses/{analysis_id}/run.
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
        description="A test repo.",
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


class TestScoutingOverview:
    def test_unknown_repo_returns_404(self, client):
        resp = client.get("/api/projects/not-a-real-repo/scouting-overview")
        assert resp.status_code == 404

    def test_returns_description_and_lifecycle_state_with_no_stats_yet(self, client):
        resp = client.get("/api/projects/myproj/scouting-overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "A test repo."
        assert data["last_surveyed_at"] == ""
        assert data["is_published"] is False
        assert data["stars"] == 0  # no project_stats row yet — defaults, not a crash

    def test_surfaces_project_stats_when_present(self, client, registry):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_stats (project_slug, fetched_at, stars, forks, "
                "contributors_count, primary_language, last_pushed_at, repo_size_kb) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("myproj", "2026-08-01T00:00:00", 42, 7, 3, "Python", "2026-07-30T00:00:00", 1024),
            )
        resp = client.get("/api/projects/myproj/scouting-overview")
        data = resp.json()
        assert data["stars"] == 42
        assert data["primary_language"] == "Python"

    def test_reflects_survey_and_publish_state(self, client, registry):
        registry.update_project_surveyed_at("myproj")
        registry.set_egeria_asset_guid("myproj", "guid-1")
        resp = client.get("/api/projects/myproj/scouting-overview")
        data = resp.json()
        assert data["last_surveyed_at"] != ""
        assert data["is_published"] is True

    def test_defaults_to_undecided_disposition(self, client):
        resp = client.get("/api/projects/myproj/scouting-overview")
        data = resp.json()
        assert data["disposition"] == "undecided"

    def test_reflects_a_set_disposition(self, client, registry):
        registry.set_disposition(
            "https://github.com/test/myproj", "investigating", reason="looks promising",
        )
        resp = client.get("/api/projects/myproj/scouting-overview")
        data = resp.json()
        assert data["disposition"] == "investigating"
        assert data["disposition_reason"] == "looks promising"


class TestScoutingScan:
    def test_unknown_repo_returns_404(self, client):
        resp = client.post("/api/projects/not-a-real-repo/scouting-scan")
        assert resp.status_code == 404

    def test_dispatches_to_run_survey_definition_with_coarse_scout_ref(self, client):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN,
        )
        with patch(
            "resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
            return_value={"errors": []},
        ) as mock_run:
            resp = client.post("/api/projects/myproj/scouting-scan")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        _, kwargs = mock_run.call_args
        assert kwargs["survey_definition_ref"] == REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN

    def test_errors_are_surfaced_not_raised(self, client):
        with patch(
            "resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
            return_value={"errors": ["step failed"]},
        ):
            resp = client.post("/api/projects/myproj/scouting-scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "step failed" in data["error"]


class TestRunSingleAnalysis:
    def test_unknown_repo_returns_404(self, client):
        resp = client.post("/api/projects/not-a-real-repo/analyses/security_scan/run")
        assert resp.status_code == 404

    def test_unmapped_analysis_id_returns_400(self, client):
        resp = client.post("/api/projects/myproj/analyses/not_a_real_analysis/run")
        assert resp.status_code == 400

    def test_publish_action_id_is_rejected_not_run(self, client):
        # egeria_publish is intentionally absent from REPO_ANALYSIS_STEP_MAP
        resp = client.post("/api/projects/myproj/analyses/egeria_publish/run")
        assert resp.status_code == 400

    def test_dispatches_with_only_the_mapped_steps(self, client):
        fake_result = MagicMock(errors=[], annotations=["a", "b"])
        with patch(
            "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator"
        ) as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            resp = client.post("/api/projects/myproj/analyses/security_scan/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        MockOrch.return_value.run.assert_called_once_with("myproj", steps=["repo_security"])

    def test_ingest_action_id_dispatches_to_incremental_indexer_not_survey_orchestrator(self, client):
        # rag_ingestion (action:"ingest") isn't a SurveyOrchestrator step —
        # it re-embeds content into pgvector via IncrementalIndexer.
        with patch("resource_explorer.ingestion.incremental.IncrementalIndexer") as MockIndexer, \
             patch("resource_explorer.query_cache.QueryCache"), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            resp = client.post("/api/projects/myproj/analyses/rag_ingestion/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["analysis_id"] == "rag_ingestion"
        MockIndexer.return_value.refresh.assert_called_once()
        MockOrch.assert_not_called()

    def test_ingest_failure_is_surfaced_as_error_not_a_500(self, client):
        with patch(
            "resource_explorer.ingestion.incremental.IncrementalIndexer.refresh",
            side_effect=RuntimeError("clone missing"),
        ):
            resp = client.post("/api/projects/myproj/analyses/rag_ingestion/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "clone missing" in data["error"]
