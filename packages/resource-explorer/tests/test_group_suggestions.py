"""Tests for GET /api/projects/groups/suggestions — org-based group
suggestions for ungrouped repos. Surfaces (never auto-applies) a suggestion
when 2+ ungrouped repos share a GitHub org, e.g. importing
unitycatalog/unitycatalog, unitycatalog/unitycatalog-python, and
unitycatalog/unitycatalog-rs together from one org-scoped search."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry


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


def _add(registry, slug, github_url, group_slug=""):
    p = Project(slug=slug, display_name=slug, github_url=github_url, collections=[])
    registry.add(p)
    if group_slug:
        registry.set_project_group(slug, group_slug)
    return p


class TestGroupSuggestions:
    def test_two_ungrouped_repos_sharing_an_org_are_suggested(self, client, registry):
        _add(registry, "unitycatalog", "https://github.com/unitycatalog/unitycatalog")
        _add(registry, "unitycatalog_python", "https://github.com/unitycatalog/unitycatalog-python")
        _add(registry, "unitycatalog_rs", "https://github.com/unitycatalog/unitycatalog-rs")

        resp = client.get("/api/projects/groups/suggestions")
        assert resp.status_code == 200
        suggestions = resp.json()
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["org"] == "unitycatalog"
        assert s["repo_count"] == 3
        assert set(s["repo_slugs"]) == {"unitycatalog", "unitycatalog_python", "unitycatalog_rs"}

    def test_a_single_repo_in_an_org_is_not_suggested(self, client, registry):
        _add(registry, "sqlglot", "https://github.com/tobymao/sqlglot")

        resp = client.get("/api/projects/groups/suggestions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_already_grouped_repos_are_excluded(self, client, registry):
        registry.create_group("uc", "Unity Catalog", "")
        _add(registry, "unitycatalog", "https://github.com/unitycatalog/unitycatalog", group_slug="uc")
        _add(registry, "unitycatalog_rs", "https://github.com/unitycatalog/unitycatalog-rs", group_slug="uc")
        # A third, still-ungrouped repo alone in its org shouldn't surface either.
        _add(registry, "sqlglot", "https://github.com/tobymao/sqlglot")

        resp = client.get("/api/projects/groups/suggestions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_partial_grouping_still_suggests_the_remaining_ungrouped_repos(self, client, registry):
        registry.create_group("uc", "Unity Catalog", "")
        _add(registry, "unitycatalog", "https://github.com/unitycatalog/unitycatalog", group_slug="uc")
        _add(registry, "unitycatalog_python", "https://github.com/unitycatalog/unitycatalog-python")
        _add(registry, "unitycatalog_rs", "https://github.com/unitycatalog/unitycatalog-rs")

        resp = client.get("/api/projects/groups/suggestions")
        assert resp.status_code == 200
        suggestions = resp.json()
        assert len(suggestions) == 1
        assert set(suggestions[0]["repo_slugs"]) == {"unitycatalog_python", "unitycatalog_rs"}

    def test_suggestions_sorted_by_repo_count_descending(self, client, registry):
        _add(registry, "a1", "https://github.com/orga/repo1")
        _add(registry, "a2", "https://github.com/orga/repo2")
        _add(registry, "b1", "https://github.com/orgb/repo1")
        _add(registry, "b2", "https://github.com/orgb/repo2")
        _add(registry, "b3", "https://github.com/orgb/repo3")

        resp = client.get("/api/projects/groups/suggestions")
        assert resp.status_code == 200
        suggestions = resp.json()
        assert [s["org"] for s in suggestions] == ["orgb", "orga"]

    def test_empty_registry_returns_empty_list(self, client):
        resp = client.get("/api/projects/groups/suggestions")
        assert resp.status_code == 200
        assert resp.json() == []
