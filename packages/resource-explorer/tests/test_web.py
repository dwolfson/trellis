"""Tests for FastAPI web routes — projects, stats, query endpoints."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_pygithub_available = pytest.mark.skipif(
    importlib.util.find_spec("github") is None, reason="PyGitHub not installed"
)

from resource_explorer.registry import Project, ProjectRegistry


# ── test app setup ─────────────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="A test project",
        collections=["myproj_python_code", "myproj_markdown_docs"],
    ))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    from resource_explorer.web.app import app
    return TestClient(app)


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self):
        from resource_explorer.web.app import app
        c = TestClient(app)
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── /api/projects ─────────────────────────────────────────────────────────────

class TestProjectsRouter:
    def test_list_projects(self, client):
        resp = client.get("/api/projects/")
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) == 1
        assert projects[0]["slug"] == "myproj"
        assert projects[0]["display_name"] == "My Project"

    def test_list_projects_includes_required_fields(self, client):
        resp = client.get("/api/projects/")
        p = resp.json()[0]
        assert "slug" in p
        assert "display_name" in p
        assert "github_url" in p
        assert "status" in p
        assert "collections" in p
        assert "last_indexed_at" in p

    def test_get_project_found(self, client):
        resp = client.get("/api/projects/myproj")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "myproj"

    def test_get_project_not_found(self, client):
        resp = client.get("/api/projects/ghost")
        assert resp.status_code == 404

    def test_delete_project(self, client):
        with patch("resource_explorer.multi_collection_store.MultiCollectionStore") as mock_store:
            mock_store.return_value.drop_collection = MagicMock()
            resp = client.delete("/api/projects/myproj")
        assert resp.status_code == 200
        assert resp.json()["removed"] == "myproj"

    def test_delete_project_not_found(self, client):
        resp = client.delete("/api/projects/ghost")
        assert resp.status_code == 404

    @_pygithub_available
    def test_refresh_project_returns_ok(self, client):
        with patch("resource_explorer.ingestion.incremental.IncrementalIndexer") as mock_idx, \
             patch("resource_explorer.query_cache.QueryCache") as mock_cache:
            mock_idx.return_value.refresh = MagicMock()
            mock_cache.return_value.invalidate_project = MagicMock(return_value=0)
            resp = client.post("/api/projects/myproj/refresh")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_refresh_project_not_found(self, client):
        resp = client.post("/api/projects/ghost/refresh")
        assert resp.status_code == 404


# ── /api/stats ────────────────────────────────────────────────────────────────

def _insert_stats(db_path, slug):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO project_stats
        (project_slug, fetched_at, stars, forks, watchers, open_issues,
         contributors_count, commits_30d, commits_90d, releases_count,
         latest_release, latest_release_at, primary_language, language_breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (slug, "2024-06-01T12:00:00", 1200, 150, 1200, 30,
          25, 15, 48, 10, "v2.0.0", "2024-05-01T00:00:00",
          "Python", json.dumps({"Python": 50000})))
    conn.commit()
    conn.close()


class TestStatsRouter:
    def test_get_stats_not_found_project(self, client):
        resp = client.get("/api/stats/ghost")
        assert resp.status_code == 404

    def test_get_stats_no_data_returns_404(self, client):
        resp = client.get("/api/stats/myproj")
        assert resp.status_code == 404

    def test_get_stats_with_data(self, client, registry):
        _insert_stats(registry.db_path, "myproj")
        resp = client.get("/api/stats/myproj")
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == "myproj"
        assert body["stats"]["stars"] == 1200
        assert body["stats"]["primary_language"] == "Python"
        assert isinstance(body["stats"]["language_breakdown"], dict)

    def test_get_history_valid_metric(self, client, registry):
        _insert_stats(registry.db_path, "myproj")
        resp = client.get("/api/stats/myproj/history?metric=stars")
        assert resp.status_code == 200
        body = resp.json()
        assert body["metric"] == "stars"
        assert len(body["data"]) == 1
        assert body["data"][0]["value"] == 1200

    def test_get_history_invalid_metric(self, client):
        resp = client.get("/api/stats/myproj/history?metric=banana")
        assert resp.status_code == 400

    def test_get_history_not_found_project(self, client):
        resp = client.get("/api/stats/ghost/history")
        assert resp.status_code == 404


# ── /api/query ────────────────────────────────────────────────────────────────

class TestQueryRouter:
    def test_query_endpoint(self, client):
        with patch("resource_explorer.rag_system.RAGSystem") as mock_rag_cls:
            mock_rag_cls.return_value.query.return_value = "mocked response"
            resp = client.post("/api/query/", json={"query": "what is this project?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["response"] == "mocked response"
        assert "intent" in body

    def test_query_with_project_scope(self, client):
        with patch("resource_explorer.rag_system.RAGSystem") as mock_rag_cls:
            rag_mock = mock_rag_cls.return_value
            rag_mock.query.return_value = "scoped response"
            resp = client.post("/api/query/", json={
                "query": "what is this project?",
                "project_slug": "myproj",
            })
        assert resp.status_code == 200
        rag_mock.query.assert_called_once_with("what is this project?", project_slug="myproj")


# ── /api/activity/rfas + PATCH /api/activity/rfas/{rfa_id} ─────────────────────

def _write_rfa_activity_entry(registry, entry_id="entry-1", num_rfas=1, extra_annotations=None):
    from resource_explorer.registry import ActivityEntry
    annotations = [
        {"annotation_type": "RequestForActionAnnotation", "analysis_name": "Security Scan",
         "count": 1, "summary": f"Finding {i}", "status": "local"}
        for i in range(num_rfas)
    ]
    if extra_annotations:
        annotations.extend(extra_annotations)
    registry.write_activity(ActivityEntry(
        id=entry_id, ts="2026-08-01T00:00:00", operation="survey", intent="assessment",
        entity_type="repo", entity_slug="myproj", entity_name="My Project",
        annotations=annotations,
    ))


class TestRfaRouter:
    def test_list_rfas_defaults_to_open(self, client, registry):
        _write_rfa_activity_entry(registry)
        resp = client.get("/api/activity/rfas")
        assert resp.status_code == 200
        rfas = resp.json()
        assert len(rfas) == 1
        assert rfas[0]["id"] == "entry-1::0"
        assert rfas[0]["rfa_status"] == "open"
        assert rfas[0]["assignee"] == ""

    def test_ids_are_stable_and_positional(self, client, registry):
        _write_rfa_activity_entry(registry, num_rfas=3, extra_annotations=[
            {"annotation_type": "ClassificationAnnotation", "summary": "not an rfa"},
        ])
        rfas = client.get("/api/activity/rfas").json()
        assert [r["id"] for r in rfas] == ["entry-1::0", "entry-1::1", "entry-1::2"]

    def test_patch_defer_persists_and_overlays_on_relist(self, client, registry):
        _write_rfa_activity_entry(registry)
        resp = client.patch("/api/activity/rfas/entry-1::0", json={
            "status": "deferred", "defer_until": "2026-09-01",
        })
        assert resp.status_code == 200
        assert resp.json()["rfa_status"] == "deferred"

        rfas = client.get("/api/activity/rfas").json()
        assert rfas[0]["rfa_status"] == "deferred"
        assert rfas[0]["defer_until"] == "2026-09-01"
        assert rfas[0]["action_updated_at"]  # timestamp recorded

    def test_patch_reassign_persists_assignee(self, client, registry):
        _write_rfa_activity_entry(registry)
        client.patch("/api/activity/rfas/entry-1::0", json={
            "status": "reassigned", "assignee": "dwolfson",
        })
        rfas = client.get("/api/activity/rfas").json()
        assert rfas[0]["rfa_status"] == "reassigned"
        assert rfas[0]["assignee"] == "dwolfson"

    def test_patch_complete_with_resolution_note(self, client, registry):
        _write_rfa_activity_entry(registry)
        client.patch("/api/activity/rfas/entry-1::0", json={
            "status": "completed", "resolution_note": "Fixed in PR #42",
        })
        rfas = client.get("/api/activity/rfas").json()
        assert rfas[0]["rfa_status"] == "completed"
        assert rfas[0]["resolution_note"] == "Fixed in PR #42"

    def test_patch_reopen_from_completed(self, client, registry):
        _write_rfa_activity_entry(registry)
        client.patch("/api/activity/rfas/entry-1::0", json={"status": "completed"})
        resp = client.patch("/api/activity/rfas/entry-1::0", json={"status": "open"})
        assert resp.status_code == 200
        rfas = client.get("/api/activity/rfas").json()
        assert rfas[0]["rfa_status"] == "open"

    def test_patch_rejects_invalid_status(self, client, registry):
        _write_rfa_activity_entry(registry)
        resp = client.patch("/api/activity/rfas/entry-1::0", json={"status": "bogus"})
        assert resp.status_code == 400

    def test_patch_rejects_malformed_id(self, client, registry):
        resp = client.patch("/api/activity/rfas/not-a-valid-id", json={"status": "completed"})
        assert resp.status_code == 400

    def test_patch_404s_for_unknown_entry(self, client, registry):
        resp = client.patch("/api/activity/rfas/nonexistent-entry::0", json={"status": "completed"})
        assert resp.status_code == 404

    def test_other_rfas_in_same_entry_unaffected(self, client, registry):
        _write_rfa_activity_entry(registry, num_rfas=2)
        client.patch("/api/activity/rfas/entry-1::0", json={"status": "completed"})
        rfas = {r["id"]: r for r in client.get("/api/activity/rfas").json()}
        assert rfas["entry-1::0"]["rfa_status"] == "completed"
        assert rfas["entry-1::1"]["rfa_status"] == "open"


# ── /api/analyses/{resource_type} + /perspectives + /egeria-status ─────────────

class TestAnalysisCatalogRouter:
    def test_list_analyses_for_database(self, client):
        resp = client.get("/api/analyses/database")
        assert resp.status_code == 200
        ids = {a["id"] for a in resp.json()}
        assert "schema_inventory" in ids

    def test_filters_by_intent(self, client):
        resp = client.get("/api/analyses/database?intent=curate")
        assert resp.status_code == 200
        ids = {a["id"] for a in resp.json()}
        assert ids == {"egeria_db_survey"}

    def test_list_perspectives_route_reachable(self, client):
        # Regression guard: /perspectives must be declared before /{resource_type}
        # or Starlette's declaration-order matching swallows it.
        resp = client.get("/api/analyses/perspectives")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert "perspectives" not in resp.json()  # i.e. it wasn't routed as resource_type="perspectives"

    def test_egeria_status_route(self, client):
        client.get("/api/analyses/database")  # populate the status this route reflects
        resp = client.get("/api/analyses/database/egeria-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["resource_type"] == "database"
        assert body["status"] in {"not_applicable", "unavailable", "ok", "unknown"}

    def test_egeria_status_not_applicable_for_unmapped_resource_type(self, client):
        client.get("/api/analyses/repo")
        resp = client.get("/api/analyses/repo/egeria-status")
        assert resp.json()["status"] == "not_applicable"


# ── /api/analyses/annotation-types ─────────────────────────────────────────────

class TestAnnotationTypesRouter:
    def test_list_annotation_types(self, client):
        resp = client.get("/api/analyses/annotation-types")
        assert resp.status_code == 200
        types = resp.json()
        assert len(types) >= 7  # Prepopulated default count
        # Check one of the default types is present
        assert any(t["type"] == "ResourceMeasureAnnotation" for t in types)

    def test_register_and_get_and_update_and_delete_annotation_type(self, client):
        # 1. Register a new type
        new_type = {
            "type": "CustomTestAnnotation",
            "display_name": "Custom Test",
            "description": "Used for testing CRUD",
            "properties": ["field1", "field2"],
            "egeria_type": "CustomEgeriaClass",
            "python_class": "CustomPythonClass"
        }
        res_post = client.post("/api/analyses/annotation-types", json=new_type)
        assert res_post.status_code == 200
        assert res_post.json() == {"status": "success"}

        # 2. Get the registered type
        res_get = client.get("/api/analyses/annotation-types/CustomTestAnnotation")
        assert res_get.status_code == 200
        body = res_get.json()
        assert body["type"] == "CustomTestAnnotation"
        assert body["display_name"] == "Custom Test"
        assert body["properties"] == ["field1", "field2"]

        # 3. Update the type
        updated = {
            "display_name": "Custom Test Updated",
            "description": "Updated description",
            "properties": ["field1", "field2", "field3"],
            "egeria_type": "CustomEgeriaClassUpdated",
            "python_class": "CustomPythonClassUpdated"
        }
        res_put = client.put("/api/analyses/annotation-types/CustomTestAnnotation", json=updated)
        assert res_put.status_code == 200
        assert res_put.json() == {"status": "success"}

        # Verify updates
        res_get_updated = client.get("/api/analyses/annotation-types/CustomTestAnnotation")
        assert res_get_updated.status_code == 200
        body_up = res_get_updated.json()
        assert body_up["display_name"] == "Custom Test Updated"
        assert body_up["properties"] == ["field1", "field2", "field3"]

        # 4. Delete the type
        res_del = client.delete("/api/analyses/annotation-types/CustomTestAnnotation")
        assert res_del.status_code == 200
        assert res_del.json() == {"status": "success"}

        # Verify 404 on get
        res_get_deleted = client.get("/api/analyses/annotation-types/CustomTestAnnotation")
        assert res_get_deleted.status_code == 404


class TestEgeriaRules:
    def test_get_dataclass_rules_fallback(self, client):
        import os
        with patch.dict(os.environ, {}, clear=False):
            if "EGERIA_PLATFORM_URL" in os.environ:
                del os.environ["EGERIA_PLATFORM_URL"]
            resp = client.get("/api/egeria/rules/dataclasses")
            assert resp.status_code == 200
            rules = resp.json()
            assert len(rules) == 6
            assert any(r["name"] == "EmailAddress" and r["source"] == "Local Fallback" for r in rules)

    def test_get_dataclass_rules_mocked_egeria(self, client):
        import os
        from unittest import mock
        
        mock_find_response = [
            {
                "properties": {
                    "qualifiedName": "ValidValueDefinition::EmailAddressKeyword::custom_secret",
                    "displayName": "custom_secret",
                    "preferredValue": "custom_secret"
                }
            }
        ]
        
        with mock.patch.dict(os.environ, {
            "EGERIA_PLATFORM_URL": "http://localhost:9443",
            "EGERIA_VIEW_SERVER": "view-server",
            "EGERIA_USER": "steward",
            "EGERIA_USER_PASSWORD": "steward"
        }):
            with mock.patch("pyegeria.omvs.reference_data.ReferenceDataManager") as MockRD, \
                 mock.patch("pyegeria.omvs.data_designer.DataDesigner") as MockDD:
                
                MockRD.return_value.find_valid_value_definitions.return_value = mock_find_response
                MockDD.return_value.get_guid_for_name.return_value = "dummy-guid"
                
                resp = client.get("/api/egeria/rules/dataclasses")
                assert resp.status_code == 200
                rules = resp.json()
                
                # Check email address rules has been fetched dynamically
                email_rule = next(r for r in rules if r["name"] == "EmailAddress")
                assert email_rule["source"] == "Egeria (Active)"
                assert "custom_secret" in email_rule["keywords"]


