"""Tests for the live-Egeria database survey/annotation read routes:
GET /api/databases/{slug}/egeria-surveys and .../egeria-surveys/{report_guid}/annotations.

Both walk real Egeria relationships (ReportSubject / ReportedAnnotation) via
AssetMaker.get_asset_by_guid(guid, body={"graphQueryDepth": 1}) rather than
guessing a qualifiedName naming convention — this is what lets them see reports
created by Egeria's own native survey engine, not just ones RE published itself.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import DatabaseEntity, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.register_database(DatabaseEntity(
        slug="mydb",
        display_name="My DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="mydb",
    ))
    r.set_database_egeria_guid("mydb", "db-asset-guid-1")
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestEgeriaSurveyReports:
    def test_unknown_database_returns_404(self, client):
        resp = client.get("/api/databases/not-a-real-db/egeria-surveys")
        assert resp.status_code == 404

    def test_returns_live_reports(self, client):
        fake_reports = [{
            "guid": "report-guid-1",
            "qualified_name": "SurveyReport::PostgreSQL::mydb::2026-07-08T00:00:00",
            "display_name": "Survey: My DB",
            "surveyed_at": "2026-07-08T00:00:00",
            "annotation_count": 3,
            "schema_count": 1,
            "table_count": 5,
            "column_count": 20,
            "description": "Automated survey",
        }]
        with patch(
            "resource_explorer.surveyors.database.egeria_database_surveyor.EgeriaDatabaseSurveyor.get_survey_reports_by_guid",
            return_value=fake_reports,
        ) as mock_get:
            resp = client.get("/api/databases/mydb/egeria-surveys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["guid"] == "report-guid-1"
        assert data[0]["annotation_count"] == 3
        mock_get.assert_called_once_with("db-asset-guid-1")

    def test_not_yet_cataloged_returns_empty_list(self, client, registry):
        registry.set_database_egeria_guid("mydb", "")
        resp = client.get("/api/databases/mydb/egeria-surveys")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_egeria_unreachable_returns_503(self, client):
        from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyorError
        with patch(
            "resource_explorer.surveyors.database.egeria_database_surveyor.EgeriaDatabaseSurveyor.get_survey_reports_by_guid",
            side_effect=EgeriaDatabaseSurveyorError("EGERIA_PLATFORM_URL is not set."),
        ):
            resp = client.get("/api/databases/mydb/egeria-surveys")
        assert resp.status_code == 503


class TestEgeriaAnnotations:
    def test_unknown_database_returns_404(self, client):
        resp = client.get("/api/databases/not-a-real-db/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 404

    def test_returns_annotations(self, client):
        fake_annotations = [{
            "guid": "ann-guid-1",
            "annotation_type": "SchemaAnalysisAnnotation",
            "summary": "Found 5 tables",
            "confidence": 100,
            "analysis_step": "postgres_schema_and_stats",
            "explanation": "",
            "expression": "",
            "json_properties": {},
        }]
        with patch(
            "resource_explorer.surveyors.database.egeria_database_surveyor.EgeriaDatabaseSurveyor.get_annotations_by_report_guid",
            return_value=fake_annotations,
        ) as mock_get:
            resp = client.get("/api/databases/mydb/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["summary"] == "Found 5 tables"
        mock_get.assert_called_once_with("report-guid-1")

    def test_egeria_unreachable_returns_503(self, client):
        from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyorError
        with patch(
            "resource_explorer.surveyors.database.egeria_database_surveyor.EgeriaDatabaseSurveyor.get_annotations_by_report_guid",
            side_effect=EgeriaDatabaseSurveyorError("Could not connect to Egeria"),
        ):
            resp = client.get("/api/databases/mydb/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 503
