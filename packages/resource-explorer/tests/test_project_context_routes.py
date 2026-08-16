"""Tests for /api/project-context/* — the Egeria Project context picker's
backend (Discovery-tier Part 5).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestGetProjectContext:
    def test_never_decided_returns_unset_not_404(self, client):
        resp = client.get("/api/project-context/repo/myproj")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unset"
        assert data["entity_type"] == "repo"
        assert data["entity_slug"] == "myproj"


class TestSetProjectContext:
    def test_personal_just_exploring(self, client):
        resp = client.post("/api/project-context/repo/myproj", json={"status": "personal"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "personal"

        follow_up = client.get("/api/project-context/repo/myproj")
        assert follow_up.json()["status"] == "personal"

    def test_declined_is_explicit_not_same_as_unset(self, client):
        resp = client.post("/api/project-context/repo/myproj", json={"status": "declined"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "declined"

    def test_deferred_requires_free_text_name(self, client):
        resp = client.post("/api/project-context/repo/myproj", json={"status": "deferred"})
        assert resp.status_code == 400

        resp2 = client.post(
            "/api/project-context/repo/myproj",
            json={"status": "deferred", "free_text_name": "Q3 Migration"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["free_text_name"] == "Q3 Migration"

    def test_linked_requires_egeria_project_guid(self, client):
        resp = client.post("/api/project-context/repo/myproj", json={"status": "linked"})
        assert resp.status_code == 400

        resp2 = client.post(
            "/api/project-context/repo/myproj",
            json={
                "status": "linked",
                "egeria_project_guid": "guid-1",
                "egeria_project_qualified_name": "Project::Foo::1.0",
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["egeria_project_guid"] == "guid-1"

    def test_invalid_status_rejected(self, client):
        resp = client.post("/api/project-context/repo/myproj", json={"status": "bogus"})
        assert resp.status_code == 400

    def test_entity_types_are_independent(self, client):
        client.post("/api/project-context/repo/myproj", json={"status": "personal"})
        client.post("/api/project-context/database/myproj", json={"status": "declined"})
        assert client.get("/api/project-context/repo/myproj").json()["status"] == "personal"
        assert client.get("/api/project-context/database/myproj").json()["status"] == "declined"


class TestSearchCandidates:
    def test_success_returns_normalized_candidates(self, client):
        with patch(
            "resource_explorer.surveyors.egeria_project_finder.EgeriaProjectFinder"
        ) as MockFinder:
            MockFinder.return_value.search_projects.return_value = [
                {"guid": "g1", "qualified_name": "Project::Foo::1.0", "display_name": "Foo", "description": "d"},
            ]
            resp = client.get("/api/project-context/search/candidates?q=Foo")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["display_name"] == "Foo"

    def test_connection_failure_is_fail_soft_empty_list(self, client):
        from resource_explorer.surveyors.egeria_project_finder import EgeriaProjectFinderError

        with patch(
            "resource_explorer.surveyors.egeria_project_finder.EgeriaProjectFinder"
        ) as MockFinder:
            MockFinder.return_value.search_projects.side_effect = EgeriaProjectFinderError("boom")
            resp = client.get("/api/project-context/search/candidates?q=Foo")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_route_does_not_collide_with_entity_type_slug_pattern(self, client):
        # /search/candidates must resolve to the search route, not be
        # swallowed by /{entity_type}/{slug} treating "search" as a type
        # and "candidates" as a slug.
        with patch(
            "resource_explorer.surveyors.egeria_project_finder.EgeriaProjectFinder"
        ) as MockFinder:
            MockFinder.return_value.search_projects.return_value = []
            resp = client.get("/api/project-context/search/candidates")
        assert resp.status_code == 200
        assert resp.json() == []
