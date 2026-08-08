"""Tests for the live-Egeria repo survey/annotation read routes:
GET /api/egeria/{slug}/egeria-surveys and .../egeria-surveys/{report_guid}/annotations.

These generalize the same ReportSubject/ReportedAnnotation relationship-walk
pattern already used for databases (tests/test_databases_egeria_surveys.py)
to repos, via EgeriaPublisher's thin wrapper methods.
"""
from __future__ import annotations

from unittest.mock import patch

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
    r.set_egeria_asset_guid("myproj", "repo-asset-guid-1")
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestRepoEgeriaSurveyReports:
    def test_unknown_repo_returns_404(self, client):
        resp = client.get("/api/egeria/not-a-real-repo/egeria-surveys")
        assert resp.status_code == 404

    def test_returns_live_reports(self, client):
        fake_reports = [{
            "guid": "report-guid-1",
            "qualified_name": "SurveyReport::GitHubRepo::myproj::2026-07-09T00:00:00",
            "display_name": "Survey: My Project",
            "surveyed_at": "2026-07-09T00:00:00",
            "annotation_count": 5,
            "schema_count": 0,
            "table_count": 0,
            "column_count": 0,
            "description": "Automated survey",
        }]
        with patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher.get_survey_reports_by_guid",
            return_value=fake_reports,
        ) as mock_get:
            resp = client.get("/api/egeria/myproj/egeria-surveys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["guid"] == "report-guid-1"
        mock_get.assert_called_once_with("repo-asset-guid-1")

    def test_not_yet_cataloged_returns_empty_list(self, client, registry):
        registry.set_egeria_asset_guid("myproj", "")
        resp = client.get("/api/egeria/myproj/egeria-surveys")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_egeria_unreachable_returns_503(self, client):
        from resource_explorer.surveyors.egeria_publisher import EgeriaConnectionError
        with patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher.get_survey_reports_by_guid",
            side_effect=EgeriaConnectionError("EGERIA_PLATFORM_URL is not set."),
        ):
            resp = client.get("/api/egeria/myproj/egeria-surveys")
        assert resp.status_code == 503


class TestRepoEgeriaAnnotations:
    def test_unknown_repo_returns_404(self, client):
        resp = client.get("/api/egeria/not-a-real-repo/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 404

    def test_returns_annotations(self, client):
        fake_annotations = [{
            "guid": "ann-guid-1",
            "annotation_type": "QualityScoreAnnotation",
            "summary": "Health score: 82",
            "confidence": 100,
            "analysis_step": "HealthSurvey",
            "explanation": "",
            "expression": "",
            "json_properties": {},
        }]
        with patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher.get_annotations_by_report_guid",
            return_value=fake_annotations,
        ) as mock_get:
            resp = client.get("/api/egeria/myproj/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["summary"] == "Health score: 82"
        mock_get.assert_called_once_with("report-guid-1")

    def test_egeria_unreachable_returns_503(self, client):
        from resource_explorer.surveyors.egeria_publisher import EgeriaConnectionError
        with patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher.get_annotations_by_report_guid",
            side_effect=EgeriaConnectionError("Could not connect to Egeria"),
        ):
            resp = client.get("/api/egeria/myproj/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 503
