"""Tests for the live-Egeria filesystem survey/annotation read routes:
GET /api/filesystems/{slug}/egeria-surveys and .../egeria-surveys/{report_guid}/annotations.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import FileSystemEntity, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.register_filesystem(FileSystemEntity(
        slug="myfs",
        display_name="My Filesystem",
        local_mount_point="/data/myfs",
        egeria_asset_guid="fs-asset-guid-1",
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


class TestFilesystemEgeriaSurveyReports:
    def test_unknown_filesystem_returns_404(self, client):
        resp = client.get("/api/filesystems/not-a-real-fs/egeria-surveys")
        assert resp.status_code == 404

    def test_returns_live_reports(self, client):
        fake_reports = [{
            "guid": "report-guid-1",
            "qualified_name": "SurveyReport::FileSystem::myfs::2026-07-09T00:00:00",
            "display_name": "Survey: My Filesystem",
            "surveyed_at": "2026-07-09T00:00:00",
            "annotation_count": 2,
            "schema_count": 0,
            "table_count": 0,
            "column_count": 0,
            "description": "Automated survey",
        }]
        with patch(
            "resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor.EgeriaFileSystemSurveyor.get_survey_reports_by_guid",
            return_value=fake_reports,
        ) as mock_get:
            resp = client.get("/api/filesystems/myfs/egeria-surveys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["guid"] == "report-guid-1"
        mock_get.assert_called_once_with("fs-asset-guid-1")

    def test_not_yet_cataloged_returns_empty_list(self, client, registry):
        registry.set_filesystem_egeria_guid("myfs", "")
        resp = client.get("/api/filesystems/myfs/egeria-surveys")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_egeria_unreachable_returns_503(self, client):
        from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyorError
        with patch(
            "resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor.EgeriaFileSystemSurveyor.get_survey_reports_by_guid",
            side_effect=EgeriaFileSystemSurveyorError("EGERIA_PLATFORM_URL is not set."),
        ):
            resp = client.get("/api/filesystems/myfs/egeria-surveys")
        assert resp.status_code == 503


class TestFilesystemEgeriaAnnotations:
    def test_unknown_filesystem_returns_404(self, client):
        resp = client.get("/api/filesystems/not-a-real-fs/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 404

    def test_returns_annotations(self, client):
        fake_annotations = [{
            "guid": "ann-guid-1",
            "annotation_type": "ResourceMeasureAnnotation",
            "summary": "3 data files profiled",
            "confidence": 100,
            "analysis_step": "DataProfiling",
            "explanation": "",
            "expression": "",
            "json_properties": {},
        }]
        with patch(
            "resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor.EgeriaFileSystemSurveyor.get_annotations_by_report_guid",
            return_value=fake_annotations,
        ) as mock_get:
            resp = client.get("/api/filesystems/myfs/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["summary"] == "3 data files profiled"
        mock_get.assert_called_once_with("report-guid-1")

    def test_egeria_unreachable_returns_503(self, client):
        from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyorError
        with patch(
            "resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor.EgeriaFileSystemSurveyor.get_annotations_by_report_guid",
            side_effect=EgeriaFileSystemSurveyorError("Could not connect to Egeria"),
        ):
            resp = client.get("/api/filesystems/myfs/egeria-surveys/report-guid-1/annotations")
        assert resp.status_code == 503
