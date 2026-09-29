"""Route-level tests for /api/doc-sources — BRIEF-DATABASE-DOCUMENTATION-
SOURCES.md slice 1. Uses the same registry-sharing fixture pattern as
tests/test_databases_egeria_surveys.py (monkeypatch ProjectRegistry.__init__
to share one test registry's __dict__ across every ProjectRegistry() call
the routes make), and monkeypatches the probe/egeria functions so these run
with no network and no real Egeria platform.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from resource_explorer.doc_source_probe import ProbeResult
from resource_explorer.registry import DatabaseEntity, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.register_database(DatabaseEntity(
        slug="adventureworks", display_name="AdventureWorks", db_type="postgresql",
        host="localhost", port=5432, database_name="adventureworks",
        egeria_url="https://egeria.example", egeria_server="view1",
        egeria_user="u", egeria_password="p",
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


def _fake_probe(state="reachable", status_code=200):
    return ProbeResult(state=state, status_code=status_code, elapsed_ms=42,
                        title="A Page", byte_count=1234)


class TestAddAndProbe:
    def test_add_probes_immediately_and_returns_the_state(self, client, monkeypatch):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe("reachable", 200))

        resp = client.post("/api/doc-sources/database/adventureworks",
                            json={"url": "https://docs.example/dict", "label": "Data dict",
                                  "source_type": "data_dictionary"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["probe_state"] == "reachable"
        assert body["probe_status_code"] == 200
        assert body["probe_ms"] == 42
        assert body["label"] == "Data dict"

    def test_add_rejects_a_non_http_url(self, client):
        resp = client.post("/api/doc-sources/database/adventureworks",
                            json={"url": "not-a-url"})
        assert resp.status_code == 400

    def test_add_against_unknown_database_is_404(self, client):
        resp = client.post("/api/doc-sources/database/nope", json={"url": "https://x"})
        assert resp.status_code == 404

    @pytest.mark.parametrize("state,status", [
        ("reachable", 200), ("needs_sign_in", 401), ("not_found", 404), ("blocked", 503),
    ])
    def test_all_four_probe_states_pass_through(self, client, monkeypatch, state, status):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe(state, status))
        resp = client.post("/api/doc-sources/database/adventureworks",
                            json={"url": f"https://docs.example/{state}"})
        assert resp.json()["probe_state"] == state
        assert resp.json()["probe_status_code"] == status


class TestListAndPublishState:
    def test_local_only_when_not_published(self, client, monkeypatch):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        client.post("/api/doc-sources/database/adventureworks", json={"url": "https://x"})

        resp = client.get("/api/doc-sources/database/adventureworks")

        assert resp.status_code == 200
        body = resp.json()
        assert body["published"] is False
        assert len(body["sources"]) == 1

    def test_published_true_once_asset_guid_is_set(self, client, monkeypatch, registry):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.read_back_doc_sources",
                             lambda *a, **kw: [])
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")

        resp = client.get("/api/doc-sources/database/adventureworks")

        assert resp.json()["published"] is True

    def test_read_back_folds_in_a_source_declared_only_in_egeria(self, client, monkeypatch, registry):
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")
        monkeypatch.setattr(
            "resource_explorer.web.routes.doc_sources.read_back_doc_sources",
            lambda *a, **kw: [{"ref_guid": "guid-x", "url": "https://declared-in-egeria.example",
                                "label": "From Egeria"}],
        )

        resp = client.get("/api/doc-sources/database/adventureworks")

        body = resp.json()
        assert body["published"] is True
        urls = [s["url"] for s in body["sources"]]
        assert "https://declared-in-egeria.example" in urls
        matched = next(s for s in body["sources"] if s["url"] == "https://declared-in-egeria.example")
        assert matched["origin"] == "egeria"


class TestRecheck:
    def test_recheck_reruns_the_probe(self, client, monkeypatch):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe("blocked", 500))
        added = client.post("/api/doc-sources/database/adventureworks",
                             json={"url": "https://x"}).json()

        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe("reachable", 200))
        resp = client.post(f"/api/doc-sources/database/adventureworks/{added['id']}/recheck")

        assert resp.json()["probe_state"] == "reachable"

    def test_recheck_unknown_source_is_404(self, client):
        resp = client.post("/api/doc-sources/database/adventureworks/nope/recheck")
        assert resp.status_code == 404


class TestRemoval:
    def test_remove_deletes_the_local_row(self, client, monkeypatch):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        added = client.post("/api/doc-sources/database/adventureworks",
                             json={"url": "https://x"}).json()

        resp = client.delete(f"/api/doc-sources/database/adventureworks/{added['id']}")

        assert resp.status_code == 200
        assert resp.json()["removed"] is True
        assert client.get("/api/doc-sources/database/adventureworks").json()["sources"] == []

    def test_remove_of_a_catalogued_source_queues_an_outbox_unpublish(
        self, client, monkeypatch, registry,
    ):
        # Egeria publish-state fix (2026-09-29): removal no longer calls
        # unpublish_doc_source synchronously (a one-shot best-effort attempt
        # with no retry if Egeria happened to be unreachable at that exact
        # moment) — it queues a doc_source_unpublish row through the SAME
        # outbox the publish side uses, so a transient failure gets retried.
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")
        added = client.post("/api/doc-sources/database/adventureworks",
                             json={"url": "https://x"}).json()
        registry.set_doc_source_egeria_ref("database", "adventureworks", added["id"], "ref-guid-1")

        resp = client.delete(f"/api/doc-sources/database/adventureworks/{added['id']}")

        assert resp.status_code == 200
        assert resp.json()["egeria_unpublish"] == "queued"
        rows = registry.list_outbox_elements(entity_slug="adventureworks")
        unpublish_rows = [r for r in rows if r["element_kind"] == "doc_source_unpublish"]
        assert len(unpublish_rows) == 1
        payload = json.loads(unpublish_rows[0]["payload_json"])
        assert payload["ref_guid"] == "ref-guid-1"
        assert payload["entity_type"] == "database"
        assert payload["entity_slug"] == "adventureworks"

    def test_remove_of_a_local_only_source_queues_nothing(self, client, monkeypatch, registry):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        added = client.post("/api/doc-sources/database/adventureworks",
                             json={"url": "https://x"}).json()

        resp = client.delete(f"/api/doc-sources/database/adventureworks/{added['id']}")

        assert resp.status_code == 200
        assert resp.json()["egeria_unpublish"] == "not_applicable"
        rows = registry.list_outbox_elements(entity_slug="adventureworks")
        assert [r for r in rows if r["element_kind"] == "doc_source_unpublish"] == []

    def test_remove_unknown_source_is_404(self, client):
        resp = client.delete("/api/doc-sources/database/adventureworks/nope")
        assert resp.status_code == 404


class TestEgeriaPublishStateFix:
    """Egeria publish-state fix (2026-09-29) — the bug found live on 8813:
    `add_doc_source` only ever saved locally, so a source added to an
    ALREADY-published resource stayed local-only until the next full
    re-publish, with nothing on the row saying so. Covers both required
    route behaviors plus the four-state vocabulary this fix introduces."""

    def test_add_on_an_already_published_resource_queues_an_outbox_publish(
        self, client, monkeypatch, registry,
    ):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.read_back_doc_sources",
                             lambda *a, **kw: [])

        resp = client.post("/api/doc-sources/database/adventureworks",
                            json={"url": "https://docs.example/dict"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["egeria_state"] == "publishing"
        assert body["egeria_external_ref_guid"] == ""
        rows = registry.list_outbox_elements(entity_slug="adventureworks")
        publish_rows = [r for r in rows if r["element_kind"] == "doc_source_publish"]
        assert len(publish_rows) == 1
        payload = json.loads(publish_rows[0]["payload_json"])
        assert payload["source_id"] == body["id"]
        assert publish_rows[0]["qualified_name"] == "ExternalReference::https://docs.example/dict"

    def test_add_on_an_unpublished_resource_stays_local_and_queues_nothing(
        self, client, monkeypatch, registry,
    ):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())

        resp = client.post("/api/doc-sources/database/adventureworks",
                            json={"url": "https://docs.example/dict"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["egeria_state"] == "local_only"
        rows = registry.list_outbox_elements(entity_slug="adventureworks")
        assert [r for r in rows if r["element_kind"] == "doc_source_publish"] == []

    def test_list_reports_catalogued_when_the_ref_guid_is_set(self, client, monkeypatch, registry):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.read_back_doc_sources",
                             lambda *a, **kw: [])
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")
        added = client.post("/api/doc-sources/database/adventureworks",
                             json={"url": "https://x"}).json()
        registry.set_doc_source_egeria_ref("database", "adventureworks", added["id"], "ref-guid-9")

        resp = client.get("/api/doc-sources/database/adventureworks")

        body = resp.json()
        row = next(s for s in body["sources"] if s["id"] == added["id"])
        assert row["egeria_state"] == "catalogued"
        assert row["egeria_state_detail"] == "ref-guid-9"
        assert body["in_egeria_count"] == 1
        assert body["local_count"] == 0

    def test_list_reports_publish_failed_with_the_real_reason(self, client, monkeypatch, registry):
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.run_probe",
                             lambda url: _fake_probe())
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.read_back_doc_sources",
                             lambda *a, **kw: [])
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")
        added = client.post("/api/doc-sources/database/adventureworks",
                             json={"url": "https://x"}).json()
        outbox_rows = registry.list_outbox_elements(entity_slug="adventureworks")
        row_id = next(r["id"] for r in outbox_rows if r["element_kind"] == "doc_source_publish")
        registry.mark_outbox_failed(row_id, "Egeria unreachable: connection refused")

        resp = client.get("/api/doc-sources/database/adventureworks")

        row = next(s for s in resp.json()["sources"] if s["id"] == added["id"])
        assert row["egeria_state"] == "publish_failed"
        assert "connection refused" in row["egeria_state_detail"]

    def test_list_self_heals_a_source_stranded_by_the_pre_fix_bug(self, client, monkeypatch, registry):
        # The exact bug found live on 8813: a doc_sources row added while the
        # resource was already published, with no egeria_external_ref_guid
        # AND no outbox row ever queued for it (this fix didn't exist yet).
        # A read must not render it as an unexplained gap forever — it
        # queues the missing publish right here.
        monkeypatch.setattr("resource_explorer.web.routes.doc_sources.read_back_doc_sources",
                             lambda *a, **kw: [])
        registry.set_database_egeria_guid("adventureworks", "asset-guid-1")
        stranded = registry.add_doc_source("database", "adventureworks", "https://stranded.example")

        resp = client.get("/api/doc-sources/database/adventureworks")

        row = next(s for s in resp.json()["sources"] if s["id"] == stranded["id"])
        assert row["egeria_state"] == "publishing"
        rows = registry.list_outbox_elements(entity_slug="adventureworks")
        publish_rows = [r for r in rows if r["element_kind"] == "doc_source_publish"]
        assert len(publish_rows) == 1


class TestPublishHook:
    def test_publish_local_doc_sources_skips_already_published_rows(self, monkeypatch, registry):
        from resource_explorer.web.routes.doc_sources import publish_local_doc_sources

        registry.add_doc_source("database", "adventureworks", "https://x")
        row2 = registry.add_doc_source("database", "adventureworks", "https://y")
        registry.set_doc_source_egeria_ref("database", "adventureworks", row2["id"], "already-there")

        calls = []
        monkeypatch.setattr(
            "resource_explorer.web.routes.doc_sources.publish_doc_source",
            lambda row, asset_guid, **kw: calls.append(row["url"]) or {"ok": True, "ref_guid": "new-guid", "link_guid": ""},
        )

        results = publish_local_doc_sources("database", "adventureworks", "asset-guid-1", registry=registry)

        assert calls == ["https://x"]  # only the unpublished one was published
        skipped = next(r for r in results if r["id"] == row2["id"])
        assert skipped.get("skipped") == "already published"
