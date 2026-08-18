"""Tests for /api/automate/* — Automate subscription routes (Discovery-tier
Part 4).
"""
from __future__ import annotations

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


class TestCreateSubscription:
    def test_create_returns_subscription(self, client):
        resp = client.post("/api/automate/subscriptions", json={
            "entity_type": "repo", "entity_slug": "myproj",
            "analysis_id": "license_classification", "label": "License risk changed",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_slug"] == "myproj"
        assert data["analysis_id"] == "license_classification"
        assert data["active"] is True
        assert data["notification_count"] == 0

    def test_unknown_repo_returns_404(self, client):
        resp = client.post("/api/automate/subscriptions", json={
            "entity_type": "repo", "entity_slug": "nope", "analysis_id": "maturity",
        })
        assert resp.status_code == 404


class TestListSubscriptions:
    def test_filters_by_query_params(self, client):
        client.post("/api/automate/subscriptions", json={
            "entity_type": "repo", "entity_slug": "myproj", "analysis_id": "maturity",
        })
        client.post("/api/automate/subscriptions", json={
            "entity_type": "repo", "entity_slug": "myproj", "analysis_id": "license_classification",
        })
        resp = client.get("/api/automate/subscriptions?entity_slug=myproj&analysis_id=maturity")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["analysis_id"] == "maturity"

    def test_active_only_filter(self, client):
        create_resp = client.post("/api/automate/subscriptions", json={
            "entity_type": "repo", "entity_slug": "myproj", "analysis_id": "maturity",
        })
        sub_id = create_resp.json()["id"]
        client.post(f"/api/automate/subscriptions/{sub_id}/deactivate")
        active = client.get("/api/automate/subscriptions?entity_slug=myproj&active_only=true").json()
        assert active == []
        all_subs = client.get("/api/automate/subscriptions?entity_slug=myproj&active_only=false").json()
        assert len(all_subs) == 1


class TestLifecycle:
    def test_deactivate_then_activate(self, client):
        create_resp = client.post("/api/automate/subscriptions", json={
            "entity_type": "repo", "entity_slug": "myproj", "analysis_id": "maturity",
        })
        sub_id = create_resp.json()["id"]

        deactivated = client.post(f"/api/automate/subscriptions/{sub_id}/deactivate")
        assert deactivated.status_code == 200
        assert deactivated.json()["active"] is False

        reactivated = client.post(f"/api/automate/subscriptions/{sub_id}/activate")
        assert reactivated.status_code == 200
        assert reactivated.json()["active"] is True

    def test_missing_subscription_404s(self, client):
        assert client.post("/api/automate/subscriptions/9999/deactivate").status_code == 404
        assert client.post("/api/automate/subscriptions/9999/activate").status_code == 404
