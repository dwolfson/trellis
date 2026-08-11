"""Tests for the sub-resources routes — the "Select"/"Catalog" stages of
the repo scope-narrowing funnel (docs/repo-scope-narrowing-funnel.md,
D2/D3/D4): GET/{slug}/sub-resources, POST /{slug}/sub-resources/catalog,
DELETE /{slug}/sub-resources."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj", display_name="My Project",
        github_url="https://github.com/test/myproj", collections=[],
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


class TestListSubResources:
    def test_404_for_unknown_repo(self, client):
        resp = client.get("/api/projects/nope/sub-resources")
        assert resp.status_code == 404

    def test_empty_when_nothing_catalogued(self, client):
        resp = client.get("/api/projects/myproj/sub-resources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_catalogued_rows(self, client, registry):
        registry.catalog_sub_resource("repo", "myproj", "docs", "folder")
        resp = client.get("/api/projects/myproj/sub-resources")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["locator"] == "docs"
        assert data[0]["kind"] == "folder"
        assert data[0]["egeria_guid"] == ""


class TestCatalogRoute:
    def test_404_for_unknown_repo(self, client):
        resp = client.post("/api/projects/nope/sub-resources/catalog", json={
            "items": [{"locator": "docs", "kind": "folder"}], "publish_to_egeria": False,
        })
        assert resp.status_code == 404

    def test_400_when_no_items(self, client):
        resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
            "items": [], "publish_to_egeria": False,
        })
        assert resp.status_code == 400

    def test_catalogs_locally_without_egeria_when_unchecked(self, client, registry):
        """The sandbox-mode escape hatch (D3) — publish_to_egeria=False must
        never touch Egeria at all, a real regression guard, not just 'it
        works when checked'."""
        with patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
                "items": [{"locator": "docs", "kind": "folder"}],
                "publish_to_egeria": False,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["cataloged"] == ["docs"]
        assert data["published"] == {}
        MockPub.assert_not_called()
        rows = registry.list_sub_resources("repo", "myproj")
        assert len(rows) == 1
        assert rows[0]["egeria_guid"] == ""

    def test_409_when_publish_requested_but_repo_has_no_egeria_asset_yet(self, client):
        resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
            "items": [{"locator": "docs", "kind": "folder"}],
            "publish_to_egeria": True,
        })
        assert resp.status_code == 409

    def test_publishes_when_checked_and_repo_already_has_an_egeria_asset(self, client, registry):
        registry.set_egeria_asset_guid("myproj", "repo-asset-guid")
        with patch(
            "resource_explorer.surveyors.egeria_publisher.EgeriaPublisher"
        ) as MockPub:
            MockPub.return_value.publish_sub_resources.return_value = {"docs": "new-guid"}
            resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
                "items": [{"locator": "docs", "kind": "folder"}],
                "publish_to_egeria": True,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["published"] == {"docs": "new-guid"}
        MockPub.return_value.publish_sub_resources.assert_called_once_with(
            "myproj", "https://github.com/test/myproj", "repo-asset-guid", ["docs"],
        )

    def test_ancestor_folders_auto_included_for_a_selected_nested_file(self, client, registry):
        """D2's own guarantee, mirrored at catalog time: selecting a nested
        file without its ancestor folder must not silently produce an
        unpublishable state — NestedFile requires a FileFolder parent."""
        resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
            "items": [{"locator": "docs/SECURITY.md", "kind": "file"}],
            "publish_to_egeria": False,
        })
        assert resp.status_code == 200
        assert set(resp.json()["cataloged"]) == {"docs/SECURITY.md", "docs"}
        rows = {r["locator"]: r["kind"] for r in registry.list_sub_resources("repo", "myproj")}
        assert rows == {"docs/SECURITY.md": "file", "docs": "folder"}

    def test_root_level_file_auto_includes_synthetic_root_folder(self, client, registry):
        resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
            "items": [{"locator": "README.md", "kind": "file"}],
            "publish_to_egeria": False,
        })
        assert resp.status_code == 200
        assert set(resp.json()["cataloged"]) == {"README.md", ""}

    def test_recataloging_is_idempotent_via_the_route_too(self, client, registry):
        registry.catalog_sub_resource("repo", "myproj", "docs", "folder")
        registry.set_sub_resource_egeria_guid("repo", "myproj", "docs", "already-published-guid")
        resp = client.post("/api/projects/myproj/sub-resources/catalog", json={
            "items": [{"locator": "docs", "kind": "folder"}],
            "publish_to_egeria": False,
        })
        assert resp.status_code == 200
        rows = registry.list_sub_resources("repo", "myproj")
        assert rows[0]["egeria_guid"] == "already-published-guid"  # untouched


class TestUncatalogRoute:
    def test_404_for_unknown_repo(self, client):
        resp = client.delete("/api/projects/nope/sub-resources", params={"locator": "docs"})
        assert resp.status_code == 404

    def test_removes_the_row(self, client, registry):
        registry.catalog_sub_resource("repo", "myproj", "docs", "folder")
        resp = client.delete("/api/projects/myproj/sub-resources", params={"locator": "docs"})
        assert resp.status_code == 200
        assert registry.list_sub_resources("repo", "myproj") == []

    def test_root_locator_is_representable_via_query_param(self, client, registry):
        registry.catalog_sub_resource("repo", "myproj", "", "folder")
        resp = client.delete("/api/projects/myproj/sub-resources", params={"locator": ""})
        assert resp.status_code == 200
        assert registry.list_sub_resources("repo", "myproj") == []
