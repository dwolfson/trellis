"""Tests for the GitHub-org discovery routes:
GET /api/projects/discover/{org} and POST /api/projects/discover/{org}/import.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from github import GithubException

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="already_here",
        display_name="Already Here",
        github_url="https://github.com/my-org/already-here",
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


_FAKE_REPOS = [
    {"full_name": "my-org/already-here", "html_url": "https://github.com/my-org/already-here",
     "description": "", "stars": 10, "language": "Python", "archived": False, "fork": False, "updated_at": ""},
    {"full_name": "my-org/new-repo", "html_url": "https://github.com/my-org/new-repo",
     "description": "brand new", "stars": 3, "language": "Go", "archived": False, "fork": False, "updated_at": ""},
]


class TestDiscoverRoute:
    def test_flags_already_registered_repos(self, client):
        with patch(
            "resource_explorer.github.client.GitHubClient.list_org_repos", return_value=_FAKE_REPOS,
        ):
            resp = client.get("/api/projects/discover/my-org")

        assert resp.status_code == 200
        data = {r["full_name"]: r for r in resp.json()}
        assert data["my-org/already-here"]["already_registered"] is True
        assert data["my-org/new-repo"]["already_registered"] is False

    def test_sorted_by_stars_descending(self, client):
        with patch(
            "resource_explorer.github.client.GitHubClient.list_org_repos", return_value=_FAKE_REPOS,
        ):
            resp = client.get("/api/projects/discover/my-org")

        stars = [r["stars"] for r in resp.json()]
        assert stars == sorted(stars, reverse=True)

    def test_org_not_found_returns_404(self, client):
        exc = GithubException(404, {"message": "Not Found"}, None)
        with patch("resource_explorer.github.client.GitHubClient.list_org_repos", side_effect=exc):
            resp = client.get("/api/projects/discover/no-such-org")

        assert resp.status_code == 404

    def test_rate_limit_error_returns_502(self, client):
        exc = GithubException(403, {"message": "rate limit exceeded"}, None)
        with patch("resource_explorer.github.client.GitHubClient.list_org_repos", side_effect=exc):
            resp = client.get("/api/projects/discover/my-org")

        assert resp.status_code == 502


class TestImportRoute:
    def test_skips_already_registered_repos(self, client):
        with patch("threading.Thread") as MockThread:
            resp = client.post("/api/projects/discover/my-org/import", json={
                "repos": [
                    {"github_url": "https://github.com/my-org/already-here", "display_name": "Already Here"},
                    {"github_url": "https://github.com/my-org/new-repo", "display_name": "New Repo"},
                ],
                "group_slug": "",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] == 1
        assert data["skipped"] == ["https://github.com/my-org/already-here"]
        MockThread.assert_called_once()

    def test_unknown_group_slug_returns_404(self, client):
        resp = client.post("/api/projects/discover/my-org/import", json={
            "repos": [{"github_url": "https://github.com/my-org/new-repo", "display_name": "New Repo"}],
            "group_slug": "no-such-group",
        })
        assert resp.status_code == 404

    def test_no_new_repos_starts_no_thread(self, client):
        with patch("threading.Thread") as MockThread:
            resp = client.post("/api/projects/discover/my-org/import", json={
                "repos": [{"github_url": "https://github.com/my-org/already-here", "display_name": "Already Here"}],
                "group_slug": "",
            })

        assert resp.status_code == 200
        assert resp.json()["queued"] == 0
        MockThread.assert_not_called()
