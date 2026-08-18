"""Tests for POST /api/databases/{slug}/analyses/{analysis_id}/run — the
database per-card dispatch fix (D6 prerequisite, docs/repo-scope-narrowing-
funnel.md). Only runs the DatabaseSurveyor step(s) the clicked analysis_id
actually needs, via DATABASE_ANALYSIS_STEP_MAP."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import DatabaseEntity, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.register_database(DatabaseEntity(
        slug="mydb", display_name="My DB", db_type="postgresql",
        host="localhost", port=5432, database_name="mydb",
        db_user="admin", db_password="secret",
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


class TestRunSingleDatabaseAnalysis:
    def test_404_for_unknown_database(self, client):
        resp = client.post("/api/databases/nope/analyses/schema_inventory/run")
        assert resp.status_code == 404

    def test_400_for_unmapped_analysis_id(self, client):
        # egeria_db_survey is Egeria-native (publish action) — not local-survey-dispatchable.
        resp = client.post("/api/databases/mydb/analyses/egeria_db_survey/run")
        assert resp.status_code == 400
        assert "no local survey step" in resp.json()["detail"]

    def test_400_for_unknown_analysis_id(self, client):
        resp = client.post("/api/databases/mydb/analyses/not_a_real_id/run")
        assert resp.status_code == 400

    def test_400_when_no_stored_credentials(self, client, registry):
        registry.register_database(DatabaseEntity(
            slug="nocreds", display_name="No Creds", db_type="postgresql",
            host="localhost", port=5432, database_name="nocreds",
        ))
        resp = client.post("/api/databases/nocreds/analyses/schema_inventory/run")
        assert resp.status_code == 400
        assert "No stored database credentials" in resp.json()["detail"]

    def test_dispatches_only_mapped_steps(self, client):
        with patch(
            "resource_explorer.surveyors.database.database_surveyor.run_database_survey",
        ) as mock_run:
            mock_run.return_value = {"annotations": [1, 2], "errors": []}
            resp = client.post("/api/databases/mydb/analyses/schema_inventory/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["analysis_id"] == "schema_inventory"
        _, kwargs = mock_run.call_args
        assert kwargs["steps"] == ["schema", "views"]
        assert kwargs["credentials"] == {"user": "admin", "password": "secret"}

    def test_row_count_snapshot_dispatches_statistics_step(self, client):
        with patch(
            "resource_explorer.surveyors.database.database_surveyor.run_database_survey",
        ) as mock_run:
            mock_run.return_value = {"annotations": [], "errors": []}
            resp = client.post("/api/databases/mydb/analyses/row_count_snapshot/run")

        assert resp.status_code == 200
        _, kwargs = mock_run.call_args
        assert kwargs["steps"] == ["schema", "statistics"]

    def test_survey_exception_returns_error_status(self, client):
        with patch(
            "resource_explorer.surveyors.database.database_surveyor.run_database_survey",
        ) as mock_run:
            mock_run.side_effect = RuntimeError("connection refused")
            resp = client.post("/api/databases/mydb/analyses/schema_inventory/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "connection refused" in data["error"]
